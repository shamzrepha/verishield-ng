"""Public INEC notice verification and optional OCR text extraction."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from PIL import Image

from ..schemas import NoticeMatch


@dataclass(frozen=True)
class OfficialNoticeRecord:
    """Verified public INEC notice entry used for claim cross-checking."""

    notice_id: str
    title: str
    published_date: str
    source_url: str
    dataset_type: str
    official_summary: str
    contradiction_patterns: tuple[str, ...]
    contradiction_reason: str
    supporting_keywords: tuple[str, ...]


OFFICIAL_NOTICES: tuple[OfficialNoticeRecord, ...] = (
    OfficialNoticeRecord(
        notice_id="INEC-2027-TIMETABLE",
        title="INEC 2027 General Election Official Timetable",
        published_date="2026-02-26",
        source_url="https://www.inecnigeria.org",
        dataset_type="PUBLIC_RECORD",
        official_summary=(
            "Presidential and National Assembly elections are scheduled for Saturday, January 16, 2027, "
            "and Governorship and State Houses of Assembly elections for Saturday, February 6, 2027. "
            "Any postponement or schedule change is announced strictly through official INEC press releases."
        ),
        contradiction_patterns=(
            r"\b(postponed|postpone|shifted|shift(?:ed)?\s+to|cancel(?:led|ed)|called\s+off|suspended)\b",
            r"\bno\s+election\s+(?:tomorrow|saturday|this\s+week)\b",
            r"\b(election\s+don\s+shift|dem\s+don\s+cancel\s+election|an\s+dage\s+zabe|a\s+ti\s+sun\s+ibo|e\s+yigharịrị\s+ntuli\s+aka)\b",
        ),
        contradiction_reason=(
            "Claims an unverified election postponement, suspension, or cancellation contradicting INEC's published timetable."
        ),
        supporting_keywords=("january 16, 2027", "february 6, 2027", "timetable", "general election"),
    ),
    OfficialNoticeRecord(
        notice_id="INEC-VOTING-PVC-BVAS",
        title="Official In-Person Voting, PVC & BVAS Accreditation Guidelines",
        published_date="2026-06-15",
        source_url="https://www.inecnigeria.org",
        dataset_type="PUBLIC_RECORD",
        official_summary=(
            "Voting takes place strictly in person at assigned polling units using a valid Permanent Voter's Card (PVC) "
            "and BVAS accreditation. Nigeria does not conduct voting by SMS, WhatsApp, or public websites."
        ),
        contradiction_patterns=(
            r"\bvote\s+(?:by|via|on)\s+(?:sms|whatsapp|online|internet|phone|website)\b",
            r"\b(?:no|without)\s+pvc\s+(?:needed|required)\b",
            r"\bpvc\s+(?:cancelled|canceled|abolished|no\s+longer\s+valid)\b",
            r"\bbvas\s+(?:scrapped|disabled|abandoned)\b",
        ),
        contradiction_reason=(
            "Falsely claims online/SMS voting or states that PVCs or BVAS accreditation are cancelled."
        ),
        supporting_keywords=("pvc", "bvas", "polling unit", "accreditation"),
    ),
    OfficialNoticeRecord(
        notice_id="INEC-POLLING-UNIT-RELOCATION",
        title="Polling Unit Assignment & Official Relocation Verification Rule",
        published_date="2026-08-10",
        source_url="https://www.inecnigeria.org",
        dataset_type="PUBLIC_RECORD",
        official_summary=(
            "Official polling unit changes are published directly on INEC's verified Voter Verification Portal "
            "and State REC announcements, never via anonymous forwarded screenshots."
        ),
        contradiction_patterns=(
            r"\bpolling\s+unit(?:s)?\s+(?:all\s+)?(?:relocated|moved|closed|merged)\s+(?:to|until)\b",
            r"\ball\s+voters\s+in\s+\w+\s+must\s+move\s+to\b",
        ),
        contradiction_reason=(
            "Alleges sweeping polling-unit relocation or closure without a verifiable INEC REC portal reference."
        ),
        supporting_keywords=("polling unit", "voter verification", "resident electoral commissioner"),
    ),
    OfficialNoticeRecord(
        notice_id="INEC-NONPARTISAN-OFFICIAL-RESULTS",
        title="Authorized Election Result Collation & Declaration Channel",
        published_date="2026-09-01",
        source_url="https://www.inecnigeria.org",
        dataset_type="PUBLIC_RECORD",
        official_summary=(
            "Only Returning Officers duly appointed by INEC declare official election results at designated collation centres."
        ),
        contradiction_patterns=(
            r"\b(?:official\s+winner\s+declared\s+early|unofficial\s+final\s+inec\s+result)\b",
        ),
        contradiction_reason="Circulates premature or unauthorized official result declarations.",
        supporting_keywords=("returning officer", "collation"),
    ),
)


def extract_text_from_image(pil_img: Image.Image) -> str | None:
    """Extract flyer text via tesseract CLI if available on PATH, else check image Info text."""
    embedded_caption = ""
    for key in ("Description", "Comment", "NoticeText", "Title"):
        val = (pil_img.info or {}).get(key)
        if isinstance(val, str) and val.strip():
            embedded_caption = f"{embedded_caption} {val.strip()}".strip()

    tesseract_bin = shutil.which("tesseract")
    if not tesseract_bin:
        return embedded_caption or None

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        pil_img.convert("RGB").save(tmp_path, format="PNG")
        proc = subprocess.run(
            [tesseract_bin, tmp_path, "stdout", "--psm", "6"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        ocr_text = proc.stdout.strip() if proc.returncode == 0 else ""
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    combined = " ".join(part for part in (ocr_text, embedded_caption) if part).strip()
    return combined or None


def match_claim_against_notices(claim_text: str | None) -> list[NoticeMatch]:
    """Compare extracted flyer OCR text or user-entered claim against verified INEC notices."""
    if not claim_text or not claim_text.strip():
        return []

    normalized = re.sub(r"\s+", " ", claim_text.strip().lower())
    matches: list[NoticeMatch] = []

    for notice in OFFICIAL_NOTICES:
        contradiction_hit = any(re.search(pattern, normalized) for pattern in notice.contradiction_patterns)
        keyword_hit = any(kw in normalized for kw in notice.supporting_keywords)

        if contradiction_hit or keyword_hit:
            matches.append(
                NoticeMatch(
                    notice_id=notice.notice_id,
                    title=notice.title,
                    published_date=notice.published_date,
                    source_url=notice.source_url,
                    dataset_type=notice.dataset_type,  # type: ignore[arg-type]
                    official_summary=notice.official_summary,
                    contradiction_found=contradiction_hit,
                    contradiction_reason=notice.contradiction_reason if contradiction_hit else None,
                )
            )

    return matches
