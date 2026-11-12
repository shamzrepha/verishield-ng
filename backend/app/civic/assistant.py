"""Grandparent-friendly Conversational Civic AI: Nigerian-Pidgin intent detection, live fact-checking & public doc Q&A."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from ..config import LANGUAGE_NAMES, SupportedLanguage, VerdictCode
from ..schemas import (
    ChatAssistantResponse,
    ChatIntent,
    PublicRecordCitation,
    SpokenVerdict,
    VerificationResponse,
)
from .factcheck import search_live_factchecks, synthesize_with_optional_llm
from .multilingual import build_spoken_verdict
from .notices import OFFICIAL_NOTICES, match_claim_against_notices
from .polling_units import POLLING_UNITS


@dataclass(frozen=True)
class PublicDocumentEntry:
    """Grounded public electoral/governance record for plain-language citizen Q&A."""

    doc_id: str
    title: str
    published_date: str
    source_url: str
    keywords: tuple[str, ...]
    plain_answer: str
    summary: str


PUBLIC_DOCUMENT_RECORDS: tuple[PublicDocumentEntry, ...] = (
    PublicDocumentEntry(
        doc_id="DOC-INEC-2027-DATES",
        title="INEC Official 2027 General Election Timetable",
        published_date="2026-02-26",
        source_url="https://www.inecnigeria.org",
        keywords=("date", "when", "january", "february", "2027", "timetable", "presidential", "governorship", "schedule"),
        plain_answer=(
            "According to INEC's published 2027 timetable: the Presidential & National Assembly elections are scheduled "
            "for Saturday, January 16, 2027, and Governorship & State Assembly elections are scheduled for Saturday, "
            "February 6, 2027. Polls have NOT been postponed."
        ),
        summary="Official 2027 Nigeria General Election dates: Jan 16, 2027 (Presidential/NASS) and Feb 6, 2027 (Governorship/State).",
    ),
    PublicDocumentEntry(
        doc_id="DOC-ELECTORAL-ACT-2022-PWD",
        title="Electoral Act 2022 — Section 54 (Accessibility for Blind, Elderly & PWD Voters)",
        published_date="2022-02-25",
        source_url="https://www.inecnigeria.org",
        keywords=("blind", "old", "elderly", "disability", "pwd", "braille", "assist", "help", "wheelchair", "section 54"),
        plain_answer=(
            "Under Section 54 of the Electoral Act 2022, INEC provides assistive tools (such as Braille ballot guides "
            "and magnifying glasses) where applicable, and a visually impaired or incapacitated voter may be accompanied "
            "to the voting cubicle by a trusted person of their choice."
        ),
        summary="Section 54 guarantees assistive materials and trusted-companion support for blind, elderly, and PWD voters.",
    ),
    PublicDocumentEntry(
        doc_id="DOC-ELECTORAL-ACT-2022-BVAS-IREV",
        title="Electoral Act 2022 & INEC Guidelines — PVC, BVAS Accreditation & IReV",
        published_date="2026-06-15",
        source_url="https://www.inecnigeria.org",
        keywords=("bvas", "pvc", "irev", "accredit", "vote", "card", "thumbprint", "online", "sms"),
        plain_answer=(
            "To vote in Nigeria, you must go in person to your assigned polling unit with your valid Permanent Voter's Card "
            "(PVC). Officials verify you using the BVAS device—there is NO voting by WhatsApp, SMS, or website."
        ),
        summary="In-person voting with valid PVC and BVAS accreditation at polling units; online/SMS voting is false.",
    ),
    PublicDocumentEntry(
        doc_id="DOC-CIVIC-TRANSCRIPT-RECORDS",
        title="Verified Public Governance, Legislative & Manifesto Records Guide",
        published_date="2026-09-10",
        source_url="https://nass.gov.ng",
        keywords=("achievement", "transcript", "record", "manifesto", "bill", "budget", "candidate", "document", "track record", "promise"),
        plain_answer=(
            "To check any officeholder or candidate's real achievements without bias, look only at signed official public records—"
            "such as National Assembly Hansard/bill trackers (nass.gov.ng), audited federal/state budget releases, and "
            "INEC-published candidate filings (inecnigeria.org). VeriShield NG stays strictly nonpartisan and never "
            "fabricates or promotes unverified campaign claims."
        ),
        summary="Nonpartisan guide to verifying public legislative transcripts, official budgets, and published candidate records.",
    ),
)

_LOCALIZED_PREFIXES: dict[SupportedLanguage, str] = {
    SupportedLanguage.ENGLISH: "",
    SupportedLanguage.PIDGIN: "In simple Pidgin: ",
    SupportedLanguage.IGBO: "N'okwu dị mfe (Igbo): ",
    SupportedLanguage.YORUBA: "Ní èdè Yorùbá rọrùn: ",
    SupportedLanguage.HAUSA: "A sauƙaƙen Hausa: ",
}

_CANDIDATE_WITHDRAWAL_CUES = (
    "drop", "dropped", "drop out", "step down", "stepped down", "withdraw", "withdrew",
    "withdrawn", "disqualif", "dead", "died", "passed away", "sick bed", "pulled out",
    "ban", "banned", "resign", "no dey contest", "comot for election",
)


def classify_user_intent(
    text: str,
    has_audio: bool = False,
    has_image: bool = False,
) -> str:
    """Detect citizen intent from natural text, Nigerian Pidgin, and typos."""
    q = text.lower().strip()

    if any(w in q for w in ("who won", "who is winning", "winner", "who should i vote", "best party", "support apc", "support pdp", "support lp")):
        return ChatIntent.PARTISAN_OR_RESULTS_GUARDRAIL

    if any(w in q for w in ("danger", "shake", "attack", "thugs", "gun", "fight", "scared", "help me", "emergency", "i am safe", "i'm safe")):
        return ChatIntent.SAFETY_OR_INCIDENT

    if any(w in q for w in ("polling unit", "poling", "where do i vote", "where i go vote", "register location", "my ward", "my lga")):
        return ChatIntent.POLLING_UNIT_LOOKUP

    if has_audio or has_image:
        return ChatIntent.VERIFY_MEDIA_OR_RUMOR

    rumor_cues = (
        "fake", "true", "rumor", "rumour", "whatsapp", "them say", "dem say", "dem talk",
        "they said", "i hear say", "forwarded", "postpon", "shift", "cancel", "no pvc",
        "sms", "moved", "closed", "check this", "verify", "news", *_CANDIDATE_WITHDRAWAL_CUES,
    )
    if any(cue in q for cue in rumor_cues) or any(m.contradiction_found for m in match_claim_against_notices(text)):
        return ChatIntent.VERIFY_MEDIA_OR_RUMOR

    return ChatIntent.PUBLIC_RECORD_OR_FACT_QA


def _build_chat_spoken_verdict(friendly_text: str, language: SupportedLanguage, fallback_verdict: VerdictCode) -> SpokenVerdict:
    if fallback_verdict != VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS:
        return build_spoken_verdict(fallback_verdict, language)

    prefix = _LOCALIZED_PREFIXES[language]
    spoken_text = f"{prefix}{friendly_text}"
    if len(spoken_text) > 360:
        spoken_text = spoken_text[:355].rsplit(" ", 1)[0] + "."
    words = len(spoken_text.split())
    return SpokenVerdict(
        language=language,
        language_name=LANGUAGE_NAMES[language],
        text=spoken_text,
        estimated_duration_seconds=max(8, min(28, int(round(words / 2.3)))),
        audio_b64_wav=build_spoken_verdict(VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS, language).audio_b64_wav,
    )


def build_chat_response(
    user_text: str,
    language: SupportedLanguage = SupportedLanguage.ENGLISH,
    media_verification: VerificationResponse | None = None,
    enable_live_lookup: bool = True,
) -> ChatAssistantResponse:
    """Answer questions, check rumors via INEC notices + live Dubawa/FactCheckHub, or guide safety."""
    clean_text = re.sub(r"\s+", " ", (user_text or "").strip())
    has_audio = media_verification is not None and media_verification.media_type == "audio"
    has_image = media_verification is not None and media_verification.media_type == "flyer"
    intent = classify_user_intent(clean_text, has_audio=has_audio, has_image=has_image)

    # 1. Partisan / Result Declaration Hard Guardrail
    if intent == ChatIntent.PARTISAN_OR_RESULTS_GUARDRAIL:
        answer = (
            "I am a strictly nonpartisan civic assistant. I cannot tell anyone who to vote for, "
            "and I never predict or declare election winners. Only INEC's duly appointed Returning Officers "
            "declare official results at designated collation centres."
        )
        return ChatAssistantResponse(
            request_id=str(uuid.uuid4()),
            detected_intent=intent,
            friendly_answer=answer,
            guidance_steps=[
                "Verify official announcements only on https://www.inecnigeria.org.",
                "Ask me factual questions about voting dates, PVC/BVAS rules, or to check a suspicious WhatsApp claim.",
            ],
            spoken_verdict=_build_chat_spoken_verdict(answer, language, VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS),
            citations=[
                PublicRecordCitation(
                    doc_id=OFFICIAL_NOTICES[3].notice_id,
                    title=OFFICIAL_NOTICES[3].title,
                    published_date=OFFICIAL_NOTICES[3].published_date,
                    source_url=OFFICIAL_NOTICES[3].source_url,
                    summary=OFFICIAL_NOTICES[3].official_summary,
                )
            ],
        )

    # 2. Safety / Danger / Check-in routing
    if intent == ChatIntent.SAFETY_OR_INCIDENT:
        answer = (
            "Your safety comes first. If you are in immediate physical danger right now, move to a safe location "
            "and call Nigeria's official emergency line (112). Tap 'Location & Shake Shield' to alert nearby users "
            "or open 'I Am Safe Check-In' so multiple witnesses can record what happened."
        )
        return ChatAssistantResponse(
            request_id=str(uuid.uuid4()),
            detected_intent=intent,
            friendly_answer=answer,
            guidance_steps=[
                "Open '2. Location & Shake Shield' to send a Shake Alert if you feel unsafe.",
                "Once safe, complete the short witness check-in so rumors don't spread a half-story.",
            ],
            spoken_verdict=_build_chat_spoken_verdict(answer, language, VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS),
            suggested_tab="safety",
        )

    # 3. Polling Unit Lookup
    if intent == ChatIntent.POLLING_UNIT_LOOKUP:
        matched_pu = next(
            (pu for pu in POLLING_UNITS if pu.state.lower() in clean_text.lower() or pu.lga.lower() in clean_text.lower()),
            None,
        )
        if matched_pu:
            answer = (
                f"In our public demo directory for {matched_pu.state} ({matched_pu.lga}), a sample polling unit is "
                f"{matched_pu.pu_name} [{matched_pu.pu_code}] in {matched_pu.ward} Ward. "
                f"{matched_pu.accessibility_note} Always confirm your personal PVC unit on voters.inecnigeria.org."
            )
        else:
            answer = (
                "Open '2. Location & Shake Shield' to either match your nearest demo Polling Unit automatically with GPS "
                "(your coordinates are never saved) or pick your State, LGA, and Ward. For official personal PVC checks, "
                "visit https://voters.inecnigeria.org."
            )
        return ChatAssistantResponse(
            request_id=str(uuid.uuid4()),
            detected_intent=intent,
            friendly_answer=answer,
            guidance_steps=[
                "Go to '2. Location & Shake Shield' in the top bar.",
                "Give explicit consent to match your GPS location or choose your State/LGA/Ward manually.",
            ],
            spoken_verdict=_build_chat_spoken_verdict(answer, language, VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS),
            suggested_tab="safety",
        )

    # 4. Media or Text Rumor Verification (INEC Notices + Live Dubawa / FactCheckHub)
    if intent == ChatIntent.VERIFY_MEDIA_OR_RUMOR:
        if media_verification is not None:
            v = media_verification
            if v.verdict_code == VerdictCode.CONTRADICTS_OFFICIAL_NOTICE:
                friendly = (
                    "Careful: what is claimed here does NOT match official INEC public records. "
                    + (v.notice_matches[0].contradiction_reason or v.uncertainty_note)
                )
            elif v.verdict_code == VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS:
                friendly = (
                    "Warning: our safety check found signs that this voice note or flyer may have been edited or AI-generated. "
                    "Please do not panic or forward it until you check inecnigeria.org."
                )
            elif v.verdict_code == VerdictCode.INCONCLUSIVE:
                friendly = (
                    "I cannot be 100% sure because WhatsApp compression, blur, or short audio hid the fine details. "
                    "Please verify directly on INEC's official website (inecnigeria.org) before trusting it."
                )
            else:
                friendly = (
                    "Good news so far: I did not find signs of AI voice cloning or image tampering in this file. "
                    "Still, always double-check breaking election news on inecnigeria.org."
                )
            citations = [
                PublicRecordCitation(
                    doc_id=m.notice_id,
                    title=m.title,
                    published_date=m.published_date,
                    source_url=m.source_url,
                    summary=m.official_summary,
                )
                for m in v.notice_matches
            ]
            return ChatAssistantResponse(
                request_id=v.request_id,
                detected_intent=intent,
                friendly_answer=friendly,
                guidance_steps=[
                    "Listen to the spoken reply in your preferred language using the Listen button.",
                    "Confirm any schedule or rule directly at https://www.inecnigeria.org.",
                ],
                spoken_verdict=v.spoken_verdict,
                media_verification=v,
                citations=citations,
            )

        # Text-only rumor verification: check INEC notices AND live Dubawa / FactCheckHub!
        matches = match_claim_against_notices(clean_text)
        contradictions = [m for m in matches if m.contradiction_found]
        live_hits = search_live_factchecks(clean_text, max_per_source=2) if enable_live_lookup else []

        citations = [
            PublicRecordCitation(
                doc_id=m.notice_id,
                title=m.title,
                published_date=m.published_date,
                source_url=m.source_url,
                summary=m.official_summary,
            )
            for m in matches
        ] + live_hits

        is_withdrawal_rumor = any(cue in clean_text.lower() for cue in _CANDIDATE_WITHDRAWAL_CUES)

        if contradictions:
            reasons = " ".join(c.contradiction_reason or c.official_summary for c in contradictions)
            answer = (
                f"Be careful—this claim looks FALSE or misleading. {reasons} "
                "Presidential/NASS elections remain scheduled for Jan 16, 2027 and Governorship/State for Feb 6, 2027, "
                "and voting is strictly in person with your PVC."
            )
            spoken = build_spoken_verdict(VerdictCode.CONTRADICTS_OFFICIAL_NOTICE, language)
        elif is_withdrawal_rumor:
            live_note = (
                f" We also checked Nigerian fact-checkers (Dubawa / FactCheckHub) and found {len(live_hits)} related "
                f"verification article(s)—for example: '{live_hits[0].title}'."
                if live_hits
                else " Neither INEC's official public notices nor our live check of Dubawa and FactCheckHub confirmed any candidate withdrawal or disqualification."
            )
            answer = (
                "Be very careful with 'them say' rumors claiming a candidate dropped out, stepped down, or was disqualified—"
                "this is a classic pre-election WhatsApp misinformation tactic."
                + live_note
                + " Never assume a candidate withdrew unless INEC publishes an official gazetted notice on inecnigeria.org."
            )
            spoken = build_spoken_verdict(VerdictCode.INCONCLUSIVE, language)
        elif live_hits:
            fact_summaries = [f"{h.title}: {h.summary}" for h in live_hits[:2]]
            llm_polished = synthesize_with_optional_llm(clean_text, fact_summaries, LANGUAGE_NAMES[language])
            answer = llm_polished or (
                f"Here is what verified Nigerian fact-checkers (Dubawa / FactCheckHub) found related to your question: "
                f"{live_hits[0].title} ({live_hits[0].published_date}). Check the cited links below and confirm official rules on inecnigeria.org."
            )
            spoken = _build_chat_spoken_verdict(answer, language, VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS)
        elif matches:
            answer = f"This matches verified public INEC information: {matches[0].official_summary}"
            spoken = _build_chat_spoken_verdict(answer, language, VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS)
        else:
            answer = (
                "I checked INEC's official notice archive and could not find a confirmed official notice matching that rumor. "
                "Treat unverified 'them say' messages with caution—attach the voice note or flyer photo here so I can scan it, "
                "or verify directly on inecnigeria.org."
            )
            spoken = build_spoken_verdict(VerdictCode.INCONCLUSIVE, language)

        return ChatAssistantResponse(
            request_id=str(uuid.uuid4()),
            detected_intent=intent,
            friendly_answer=answer,
            guidance_steps=[
                "Review the verified Dubawa, FactCheckHub, or INEC source links below.",
                "If someone sent you a screenshot or WhatsApp voice note, attach it here for media forensics.",
            ],
            spoken_verdict=spoken,
            citations=citations,
        )

    # 5. Factual Election Info & Published Record Q&A
    q_lower = clean_text.lower()
    scored: list[tuple[int, PublicDocumentEntry]] = []
    for doc in PUBLIC_DOCUMENT_RECORDS:
        hits = sum(1 for kw in doc.keywords if kw in q_lower)
        if hits > 0:
            scored.append((hits, doc))
    scored.sort(key=lambda pair: -pair[0])

    if scored:
        top_docs = [pair[1] for pair in scored[:2]]
        base_facts = [d.plain_answer for d in top_docs]
        llm_polished = synthesize_with_optional_llm(clean_text, base_facts, LANGUAGE_NAMES[language])
        answer = llm_polished or " ".join(base_facts)
        citations = [
            PublicRecordCitation(
                doc_id=d.doc_id,
                title=d.title,
                published_date=d.published_date,
                source_url=d.source_url,
                summary=d.summary,
            )
            for d in top_docs
        ]
    else:
        live_hits = search_live_factchecks(clean_text, max_per_source=2) if enable_live_lookup and len(clean_text.split()) >= 2 else []
        if live_hits:
            answer = (
                f"Here is what verified Nigerian fact-checkers published on this topic: "
                f"{live_hits[0].title} ({live_hits[0].published_date}). See the source links below."
            )
            citations = live_hits
        else:
            answer = (
                "Hello! Ask me in plain words or Nigerian Pidgin to check any rumor (e.g. 'them say election don shift'), "
                "ask for official 2027 dates, PVC/BVAS rules, or attach a WhatsApp voice note or flyer."
            )
            citations = [
                PublicRecordCitation(
                    doc_id=d.doc_id,
                    title=d.title,
                    published_date=d.published_date,
                    source_url=d.source_url,
                    summary=d.summary,
                )
                for d in PUBLIC_DOCUMENT_RECORDS[:2]
            ]

    return ChatAssistantResponse(
        request_id=str(uuid.uuid4()),
        detected_intent=intent,
        friendly_answer=answer,
        guidance_steps=[
            "Tap 'Listen' below to hear this answer read aloud.",
            "Attach any suspicious WhatsApp voice note or flyer anytime.",
        ],
        spoken_verdict=_build_chat_spoken_verdict(answer, language, VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS),
        citations=citations,
    )
