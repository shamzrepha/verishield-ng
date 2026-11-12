"""FastAPI entrypoint exposing VeriShield NG Civic AI Chat, Safety Shield, and Module B Screening."""

from __future__ import annotations

import io
import json
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from .civic import (
    OFFICIAL_NOTICES,
    LocationRegistryStore,
    build_chat_response,
    build_spoken_verdict,
    extract_text_from_image,
    list_polling_units,
    match_claim_against_notices,
)
from .config import (
    FRONTEND_DIR,
    LANGUAGE_NAMES,
    MAX_AUDIO_BYTES,
    MAX_IMAGE_BYTES,
    OFFICIAL_INEC_CHANNELS,
    SYNTHETIC_DIR,
    VERDICT_LABELS,
    SupportedLanguage,
    VerdictCode,
)
from .forensics import analyze_audio, analyze_image
from .registry import SupervisorQueueStore
from .safety import SafetyAlertStore
from .schemas import (
    AuditLogEntry,
    ChatAssistantResponse,
    IntakeReviewItem,
    InterviewChatIn,
    InterviewChatResponse,
    LocationRegistrationIn,
    LocationRegistrationResponse,
    NearestLocationIn,
    NearestLocationResponse,
    ReviewDecisionIn,
    SafeInterviewIn,
    SafetyDashboardResponse,
    SosPingIn,
    SupervisorQueueResponse,
    VerificationResponse,
)

def _ensure_synthetic_dataset() -> None:
    """Auto-generate deterministic zero-PII synthetic fixtures on fresh clone or cloud deploy."""
    if (SYNTHETIC_DIR / "manifest.json").exists() and (SYNTHETIC_DIR / "registry_batch.json").exists():
        return
    root_dir = str(Path(__file__).resolve().parents[2])
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
    from scripts.generate_synthetic_dataset import main as generate_dataset

    generate_dataset()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _ensure_synthetic_dataset()
    yield


app = FastAPI(
    title="VeriShield NG — #AI4Elections Unified Defense API",
    version="0.3.0",
    lifespan=_lifespan,
    description=(
        "Accessible Conversational Civic AI PWA, Live Fact-Check Lookup, Shared Synthetic-Media & Tamper Forensics Core, "
        "Shake-to-Alert Safety Shield with Multi-Witness AI Interview Corroboration, and Module B Intake Guard."
    ),
)

_queue_store: SupervisorQueueStore | None = None
_location_store = LocationRegistryStore()
_safety_store = SafetyAlertStore()


def get_queue_store() -> SupervisorQueueStore:
    """Lazily initialize or return the Module B Supervisor Queue Store."""
    global _queue_store
    if _queue_store is None:
        _ensure_synthetic_dataset()
        _queue_store = SupervisorQueueStore()
    return _queue_store


def _read_bounded_upload(upload: UploadFile, max_bytes: int, label: str) -> bytes:
    raw = upload.file.read(max_bytes + 1)
    if not raw:
        raise HTTPException(status_code=400, detail=f"Uploaded {label} file is empty.")
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded {label} exceeds maximum allowed size ({max_bytes // (1024 * 1024)} MB).",
        )
    return raw


def _run_audio_verification(
    audio_bytes: bytes,
    filename: str,
    language: SupportedLanguage,
    claim_text: str | None,
) -> VerificationResponse:
    try:
        audio_res = analyze_audio(audio_bytes, filename=filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    notice_matches = match_claim_against_notices(claim_text)
    contradiction = any(m.contradiction_found for m in notice_matches)

    verdict_code = audio_res.verdict_code
    uncertainty = audio_res.uncertainty_note
    if contradiction and verdict_code != VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS:
        verdict_code = VerdictCode.CONTRADICTS_OFFICIAL_NOTICE
        uncertainty = (
            "Submitted transcript/claim contradicts verified public INEC notices. "
            f"Acoustic note: {audio_res.uncertainty_note}"
        )

    spoken = build_spoken_verdict(verdict_code, language)
    return VerificationResponse(
        request_id=str(uuid.uuid4()),
        media_type="audio",
        verdict_code=verdict_code,
        verdict_label=VERDICT_LABELS[verdict_code],
        confidence_calibration=(
            "DEGRADED_INCONCLUSIVE" if verdict_code == VerdictCode.INCONCLUSIVE else "CALIBRATED_EVIDENCE"
        ),
        compression_degradation_detected=audio_res.compression_degradation_detected,
        uncertainty_note=uncertainty,
        signals=audio_res.signals,
        extracted_text=claim_text.strip() if claim_text else None,
        notice_matches=notice_matches,
        spoken_verdict=spoken,
        official_channels=list(OFFICIAL_INEC_CHANNELS),
    )


def _run_flyer_verification(
    img_bytes: bytes,
    language: SupportedLanguage,
    claim_text: str | None,
) -> VerificationResponse:
    try:
        vis_res = analyze_image(img_bytes, mode="flyer")
        pil_img = Image.open(io.BytesIO(img_bytes))
        ocr_text = extract_text_from_image(pil_img)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    combined_text = " ".join(part for part in (ocr_text or "", claim_text or "") if part).strip() or None
    notice_matches = match_claim_against_notices(combined_text)
    contradiction = any(m.contradiction_found for m in notice_matches)

    verdict_code = vis_res.verdict_code
    uncertainty = vis_res.uncertainty_note
    if contradiction and verdict_code in {VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS, VerdictCode.INCONCLUSIVE}:
        verdict_code = VerdictCode.CONTRADICTS_OFFICIAL_NOTICE
        uncertainty = (
            "Notice text contradicts verified INEC public guidelines/timetables. "
            f"Visual forensics detail: {vis_res.uncertainty_note}"
        )

    spoken = build_spoken_verdict(verdict_code, language)
    return VerificationResponse(
        request_id=str(uuid.uuid4()),
        media_type="flyer",
        verdict_code=verdict_code,
        verdict_label=VERDICT_LABELS[verdict_code],
        confidence_calibration=(
            "DEGRADED_INCONCLUSIVE" if verdict_code == VerdictCode.INCONCLUSIVE else "CALIBRATED_EVIDENCE"
        ),
        compression_degradation_detected=vis_res.compression_degradation_detected,
        uncertainty_note=uncertainty,
        signals=vis_res.signals,
        extracted_text=combined_text,
        notice_matches=notice_matches,
        spoken_verdict=spoken,
        official_channels=list(OFFICIAL_INEC_CHANNELS),
    )


@app.get("/health")
def health_check() -> dict[str, str]:
    """Liveness and dependency status check."""
    return {"status": "ok", "service": "verishield-ng", "mode": "nonpartisan_synthetic_ready"}


@app.get("/api/v1/languages")
def list_languages() -> dict[str, list[dict[str, str]]]:
    """Return supported spoken verdict languages."""
    return {
        "languages": [
            {"code": lang.value, "name": LANGUAGE_NAMES[lang]}
            for lang in SupportedLanguage
        ]
    }


@app.get("/api/v1/notices")
def list_official_notices() -> dict[str, list[dict[str, str]]]:
    """Return the verified public INEC notice corpus used for grounded cross-checks."""
    return {
        "notices": [
            {
                "notice_id": n.notice_id,
                "title": n.title,
                "published_date": n.published_date,
                "source_url": n.source_url,
                "dataset_type": n.dataset_type,
                "official_summary": n.official_summary,
            }
            for n in OFFICIAL_NOTICES
        ]
    }


@app.get("/api/v1/demo-samples")
def list_demo_samples() -> dict[str, list[dict[str, str]]]:
    """List synthetic evaluation fixtures generated under data/synthetic/ for one-click UI testing."""
    _ensure_synthetic_dataset()
    manifest = SYNTHETIC_DIR / "manifest.json"
    if not manifest.exists():
        return {"samples": []}
    return json.loads(manifest.read_text(encoding="utf-8"))


@app.get("/api/v1/demo-samples/{category}/{filename}")
def fetch_demo_sample(category: str, filename: str) -> FileResponse:
    """Safely serve a generated synthetic sample file for browser verification."""
    if category not in {"audio", "flyers", "portraits"}:
        raise HTTPException(status_code=400, detail="Invalid synthetic sample category.")
    safe_name = Path(filename).name
    target = (SYNTHETIC_DIR / category / safe_name).resolve()
    base = (SYNTHETIC_DIR / category).resolve()
    if not target.is_relative_to(base) or not target.exists():
        raise HTTPException(status_code=404, detail="Synthetic sample not found.")
    return FileResponse(target)


@app.post("/api/v1/module-a/chat", response_model=ChatAssistantResponse)
def civic_chat_endpoint(
    message: str = Form(default=""),
    language: SupportedLanguage = Form(SupportedLanguage.ENGLISH),
    file: UploadFile | None = File(default=None),
) -> ChatAssistantResponse:
    """Plain-language Civic AI Chat: understands citizen questions, verifies rumors/media, and cites public docs."""
    media_verification: VerificationResponse | None = None
    if file is not None and file.filename:
        content_type = (file.content_type or "").lower()
        suffix = Path(file.filename).suffix.lower()
        is_audio = content_type.startswith("audio/") or suffix in {".ogg", ".opus", ".wav", ".mp3", ".m4a", ".webm"}
        if is_audio:
            raw = _read_bounded_upload(file, MAX_AUDIO_BYTES, "audio")
            media_verification = _run_audio_verification(raw, file.filename, language, message or None)
        else:
            raw = _read_bounded_upload(file, MAX_IMAGE_BYTES, "image")
            media_verification = _run_flyer_verification(raw, language, message or None)

    return build_chat_response(message, language=language, media_verification=media_verification)


@app.post("/api/v1/module-a/verify-audio", response_model=VerificationResponse)
def verify_audio_endpoint(
    file: UploadFile = File(...),
    language: SupportedLanguage = Form(SupportedLanguage.ENGLISH),
    claim_text: str | None = Form(default=None),
) -> VerificationResponse:
    """Module A: Verify a forwarded voice note (.ogg/.opus/.mp3/.wav) with calibrated uncertainty."""
    audio_bytes = _read_bounded_upload(file, MAX_AUDIO_BYTES, "audio")
    return _run_audio_verification(audio_bytes, file.filename or "voice_note.ogg", language, claim_text)


@app.post("/api/v1/module-a/verify-flyer", response_model=VerificationResponse)
def verify_flyer_endpoint(
    file: UploadFile = File(...),
    language: SupportedLanguage = Form(SupportedLanguage.ENGLISH),
    claim_text: str | None = Form(default=None),
) -> VerificationResponse:
    """Module A: Verify an election notice/flyer via Shared Visual Forensics Core + INEC notice lookup."""
    img_bytes = _read_bounded_upload(file, MAX_IMAGE_BYTES, "image")
    return _run_flyer_verification(img_bytes, language, claim_text)


@app.get("/api/v1/location/directory")
def get_location_directory() -> dict[str, list[dict[str, Any]]]:
    """Return reference Nigerian polling unit directory (zero real PII)."""
    return {"polling_units": [pu.model_dump() for pu in list_polling_units()]}


@app.post("/api/v1/location/register", response_model=LocationRegistrationResponse)
def register_citizen_location(body: LocationRegistrationIn) -> LocationRegistrationResponse:
    """Register synthetic/anonymous location to assign a polling unit and enable ward safety alerts."""
    return _location_store.register(body)


@app.post("/api/v1/location/nearest", response_model=NearestLocationResponse)
def register_nearest_polling_unit(body: NearestLocationIn) -> NearestLocationResponse:
    """Match device GPS coordinates ephemerally to nearest reference Polling Unit without saving GPS."""
    return _location_store.register_nearest(body)


@app.get("/api/v1/safety/status", response_model=SafetyDashboardResponse)
def get_safety_status(pu_code: str = Query(default="PU-LA-IKJ-004")) -> SafetyDashboardResponse:
    """Inspect active ward Shake-Alert cluster status and multi-witness corroborated story."""
    return _safety_store.get_status(pu_code=pu_code)


@app.post("/api/v1/safety/sos", response_model=SafetyDashboardResponse)
def trigger_safety_sos(body: SosPingIn) -> SafetyDashboardResponse:
    """Trigger a Shake-to-Alert or panic SOS ping; escalates when multiple nearby citizens trigger."""
    return _safety_store.trigger_sos(body)


@app.post("/api/v1/safety/interview", response_model=SafetyDashboardResponse)
def submit_safe_interview(body: SafeInterviewIn) -> SafetyDashboardResponse:
    """Submit an 'I am safe' structured witness interview to corroborate multi-user accounts."""
    return _safety_store.submit_interview(body)


@app.post("/api/v1/safety/interview/chat", response_model=InterviewChatResponse)
def submit_safe_interview_chat(body: InterviewChatIn) -> InterviewChatResponse:
    """Conversational AI 'I Am Safe' follow-up witness interview that updates multi-witness corroboration."""
    return _safety_store.process_interview_chat(body)


@app.get("/api/v1/module-b/queue", response_model=SupervisorQueueResponse)
def get_module_b_queue(flagged_only: bool = Query(default=False)) -> SupervisorQueueResponse:
    """Module B: Fetch the synthetic intake & registry Supervisor Review Queue."""
    return get_queue_store().get_queue(flagged_only=flagged_only)


@app.post("/api/v1/module-b/reload")
def reload_module_b_queue() -> SupervisorQueueResponse:
    """Reload synthetic batch from data/synthetic/registry_batch.json."""
    store = get_queue_store()
    store.reload_from_disk()
    return store.get_queue(flagged_only=False)


@app.post("/api/v1/module-b/analyze-intake", response_model=IntakeReviewItem)
def analyze_single_intake_portrait(
    file: UploadFile = File(...),
    synthetic_applicant_alias: str = Form("SYNTH-APPLICANT-CUSTOM"),
    operator_id: str = Form("OP-SYNTH-DEMO"),
    station_code: str = Form("STN-LAGOS-SYNTH-01"),
) -> IntakeReviewItem:
    """Module B: Screen a single synthetic portrait via the exact same Shared Visual Forensics Core."""
    img_bytes = _read_bounded_upload(file, MAX_IMAGE_BYTES, "portrait")
    try:
        vis = analyze_image(img_bytes, mode="portrait")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    reasons: list[str] = []
    if vis.verdict_code == VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS:
        reasons.append("Shared Visual Forensics Core flagged synthetic portrait or screen-recapture indicators.")
    elif vis.verdict_code == VerdictCode.INCONCLUSIVE:
        reasons.append("Degraded portrait quality requires human supervisor review or recapture.")

    record_id = f"REC-{uuid.uuid4().hex[:8].upper()}"
    item = IntakeReviewItem(
        record_id=record_id,
        synthetic_applicant_alias=synthetic_applicant_alias,
        operator_id=operator_id,
        station_code=station_code,
        captured_at=datetime.now(timezone.utc),
        image_filename=file.filename or "synthetic_upload.png",
        visual_verdict_code=vis.verdict_code,
        visual_verdict_label=VERDICT_LABELS[vis.verdict_code],
        ai_face_likelihood=vis.ai_face_likelihood,
        screen_spoof_likelihood=vis.screen_spoof_likelihood,
        duplicate_face_cluster=None,
        burst_anomaly_flag=False,
        anomaly_reasons=reasons,
        signals=vis.signals,
        audit_log=[
            AuditLogEntry(
                timestamp=datetime.now(timezone.utc),
                actor="verishield_forensics_core",
                action="SCREENED",
                rationale=vis.uncertainty_note,
            )
        ],
    )
    return get_queue_store().upsert_item(item)


@app.post("/api/v1/module-b/review/{record_id}", response_model=IntakeReviewItem)
def review_intake_record(record_id: str, body: ReviewDecisionIn) -> IntakeReviewItem:
    """Module B: Record an auditable human-in-the-loop supervisor decision (never auto-deletes)."""
    try:
        return get_queue_store().record_decision(record_id, body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _serve_frontend_file(filename: str, media_type: str | None = None, headers: dict[str, str] | None = None) -> FileResponse:
    """Serve a frontend HTML or PWA asset cleanly or return 404 JSON if absent."""
    target = FRONTEND_DIR / filename
    if not target.exists():
        return JSONResponse({"message": f"{filename} not found. API docs available at /docs."}, status_code=404)  # type: ignore[return-value]
    return FileResponse(target, media_type=media_type, headers=headers)


@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    """Serve the VeriShield NG Gateway landing page (NDPA 2023 + role selector)."""
    return _serve_frontend_file("index.html", media_type="text/html; charset=utf-8")


@app.get("/citizen", include_in_schema=False)
def serve_citizen_pwa() -> FileResponse:
    """Serve the accessible Mobile PWA Citizen Civic AI & Shake Shield application."""
    return _serve_frontend_file("citizen.html", media_type="text/html; charset=utf-8")


@app.get("/screening", include_in_schema=False)
def serve_screening_desk() -> FileResponse:
    """Serve the INEC Supervisor Intake Screening Desk (Module B)."""
    return _serve_frontend_file("screening.html", media_type="text/html; charset=utf-8")


@app.get("/manifest.webmanifest", include_in_schema=False)
def serve_manifest() -> FileResponse:
    """Serve Web App Manifest for installable Mobile PWA mode."""
    return _serve_frontend_file("manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def serve_service_worker() -> FileResponse:
    """Serve root-scoped PWA service worker."""
    return _serve_frontend_file(
        "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/icon.svg", include_in_schema=False)
def serve_icon() -> FileResponse:
    """Serve crisp SVG app icon for PWA install & browser favicon."""
    return _serve_frontend_file("icon.svg", media_type="image/svg+xml")


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
