"""Live public Nigerian fact-check retrieval (Dubawa & FactCheckHub) + resilient optional LLM adapter."""

from __future__ import annotations

import html
import os
import re
import time
from dataclasses import dataclass

import httpx

from ..schemas import PublicRecordCitation

_PIDGIN_STOPWORDS = {
    "them", "dem", "they", "say", "said", "hear", "talk", "don", "wey", "abi", "na", "for", "from",
    "this", "that", "true", "false", "fake", "real", "check", "please", "abeg", "verify", "tell",
    "about", "what", "when", "where", "how", "is", "are", "was", "the", "a", "an", "in", "on", "of",
}

_CACHE: dict[str, tuple[float, list[PublicRecordCitation]]] = {}
_CACHE_TTL_SECONDS = 600.0


@dataclass(frozen=True)
class _SourceEndpoint:
    name: str
    api_url: str
    doc_prefix: str


_SOURCES: tuple[_SourceEndpoint, ...] = (
    _SourceEndpoint(
        name="Dubawa Nigeria",
        api_url="https://dubawa.org/wp-json/wp/v2/posts",
        doc_prefix="DUBAWA",
    ),
    _SourceEndpoint(
        name="FactCheckHub",
        api_url="https://factcheckhub.com/wp-json/wp/v2/posts",
        doc_prefix="FCH",
    ),
)


def extract_search_query(raw_text: str) -> str:
    """Distill Pidgin/informal rumor phrasing into clean fact-check search keywords."""
    tokens = re.findall(r"[A-Za-z0-9']+", raw_text)
    kept = [t for t in tokens if len(t) >= 2 and t.lower() not in _PIDGIN_STOPWORDS]
    if not kept:
        kept = tokens[:4]
    return " ".join(kept[:5]).strip()


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def search_live_factchecks(query_text: str, max_per_source: int = 2) -> list[PublicRecordCitation]:
    """Query public JSON endpoints on Dubawa and FactCheckHub with caching & graceful offline fallback."""
    search_q = extract_search_query(query_text)
    if not search_q:
        return []

    now = time.monotonic()
    cached = _CACHE.get(search_q.lower())
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    results: list[PublicRecordCitation] = []
    for src in _SOURCES:
        try:
            resp = httpx.get(
                src.api_url,
                params={"search": search_q, "per_page": max_per_source},
                timeout=3.5,
                follow_redirects=True,
                headers={"User-Agent": "VeriShieldNG/0.3 (+https://ai4elections.risenetworks.org)"},
            )
            if resp.status_code != 200 or "json" not in resp.headers.get("content-type", "").lower():
                continue
            for post in resp.json()[:max_per_source]:
                title = _strip_html((post.get("title") or {}).get("rendered", ""))
                excerpt = _strip_html((post.get("excerpt") or {}).get("rendered", ""))
                link = str(post.get("link") or src.api_url)
                date_str = str(post.get("date") or "")[:10] or "Recent"
                if title:
                    results.append(
                        PublicRecordCitation(
                            doc_id=f"{src.doc_prefix}-{post.get('id', 'POST')}",
                            title=f"[{src.name}] {title}",
                            published_date=date_str,
                            source_url=link,
                            summary=excerpt[:220] + ("..." if len(excerpt) > 220 else ""),
                        )
                    )
        except Exception:
            continue

    _CACHE[search_q.lower()] = (now, results)
    return results


def synthesize_with_optional_llm(
    user_query: str,
    grounded_facts: list[str],
    language_name: str,
) -> str | None:
    """Optionally polish grounded facts via local Ollama or Gemini if available & within quota.

    Never crashes on missing keys or 429 rate/token limits—returns None so local NLP handles it.
    """
    prompt = (
        "You are VeriShield NG, a warm, simple, strictly nonpartisan Nigerian civic helper speaking to an elderly voter. "
        f"Reply in simple {language_name} in at most 3 short sentences based ONLY on these verified facts:\n"
        + "\n".join(f"- {f}" for f in grounded_facts)
        + f"\nUser message: {user_query}\n"
        "Never guess election results or endorse any candidate."
    )

    # 1. Prefer free local Ollama if configured and running
    ollama_model = os.getenv("OLLAMA_MODEL", "").strip()
    if ollama_model:
        ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
        try:
            r = httpx.post(
                ollama_url,
                json={"model": ollama_model, "prompt": prompt, "stream": False},
                timeout=4.0,
            )
            if r.status_code == 200:
                txt = str(r.json().get("response") or "").strip()
                if txt:
                    return txt
        except Exception:
            pass

    # 2. Optional Gemini API fallback (respects quota limits gracefully on 429/errors)
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            r = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}",
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=5.0,
            )
            if r.status_code == 200:
                candidates = r.json().get("candidates") or []
                parts = (((candidates[0] if candidates else {}).get("content") or {}).get("parts")) or []
                txt = str((parts[0] if parts else {}).get("text") or "").strip()
                if txt:
                    return txt
        except Exception:
            pass

    return None
