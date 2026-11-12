"""Pydantic schemas defining the Shared Forensics Core and Responsible-AI Contract."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .config import ReviewStatus, SupportedLanguage, VerdictCode


class ForensicSignal(BaseModel):
    """Single interpretable forensic signal contributing to a calibrated verdict."""

    name: str
    score: float = Field(ge=0.0, le=1.0, description="Normalized indicator strength in [0, 1].")
    threshold: float = Field(ge=0.0, le=1.0)
    triggered: bool
    detail: str


class NoticeMatch(BaseModel):
    """Reference to an official public INEC notice or civic calendar entry."""

    notice_id: str
    title: str
    published_date: str
    source_url: str
    dataset_type: Literal["PUBLIC_RECORD", "SYNTHETIC_BENCHMARK"]
    official_summary: str
    contradiction_found: bool = False
    contradiction_reason: str | None = None


class SpokenVerdict(BaseModel):
    """Multilingual accessible summary ready for screen readers and audio playback."""

    language: SupportedLanguage
    language_name: str
    text: str
    estimated_duration_seconds: int = Field(ge=5, le=30)
    audio_b64_wav: str | None = Field(
        default=None,
        description="Optional short accessible alert tone/chime WAV; browser TTS speaks full localized script.",
    )


class VerificationResponse(BaseModel):
    """Unified Module A verification response adhering to Responsible-AI safeguards."""

    request_id: str
    media_type: Literal["audio", "flyer", "portrait"]
    verdict_code: VerdictCode
    verdict_label: str
    confidence_calibration: Literal["CALIBRATED_EVIDENCE", "DEGRADED_INCONCLUSIVE"]
    compression_degradation_detected: bool
    uncertainty_note: str
    signals: list[ForensicSignal]
    extracted_text: str | None = None
    notice_matches: list[NoticeMatch] = Field(default_factory=list)
    spoken_verdict: SpokenVerdict
    official_channels: list[str]
    nonpartisan_disclaimer: str = (
        "VeriShield NG performs signal-level authenticity screening and public-notice lookup only. "
        "It never declares election winners or official results."
    )


class IntakeRecordIn(BaseModel):
    """Synthetic intake record metadata (100% synthetic demo data—zero real PII)."""

    record_id: str
    synthetic_applicant_alias: str
    operator_id: str
    station_code: str
    captured_at: datetime
    image_filename: str
    claimed_capture_source: str = "registration_tablet"


class ReviewDecisionIn(BaseModel):
    """Human supervisor action for Module B Supervisor Review Queue."""

    decision: Literal["CLEARED_BY_HUMAN", "ESCALATED_FOR_AUDIT", "RECAPTURE_REQUESTED"]
    supervisor_alias: str = Field(min_length=2, max_length=64)
    rationale: str = Field(min_length=5, max_length=500)


class AuditLogEntry(BaseModel):
    """Immutable human-in-the-loop review trail entry."""

    timestamp: datetime
    actor: str
    action: str
    rationale: str


class IntakeReviewItem(BaseModel):
    """Module B Supervisor Review Queue row combining Visual Forensics Core + burst anomalies."""

    record_id: str
    synthetic_applicant_alias: str
    operator_id: str
    station_code: str
    captured_at: datetime
    image_filename: str
    visual_verdict_code: VerdictCode
    visual_verdict_label: str
    ai_face_likelihood: float = Field(ge=0.0, le=1.0)
    screen_spoof_likelihood: float = Field(ge=0.0, le=1.0)
    duplicate_face_cluster: str | None = None
    burst_anomaly_flag: bool = False
    anomaly_reasons: list[str]
    signals: list[ForensicSignal]
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    audit_log: list[AuditLogEntry] = Field(default_factory=list)


class SupervisorQueueResponse(BaseModel):
    """Module B dashboard payload."""

    synthetic_dataset_notice: str = (
        "100% synthetic demonstration dataset — contains zero real voter PII or live institutional records."
    )
    total_records: int
    flagged_for_review: int
    pending_review: int
    burst_anomalies_detected: int
    items: list[IntakeReviewItem]


class ChatIntent(str):
    """Detected conversational intent for plain-language citizen chat."""

    VERIFY_MEDIA_OR_RUMOR = "VERIFY_MEDIA_OR_RUMOR"
    PUBLIC_RECORD_OR_FACT_QA = "PUBLIC_RECORD_OR_FACT_QA"
    POLLING_UNIT_LOOKUP = "POLLING_UNIT_LOOKUP"
    SAFETY_OR_INCIDENT = "SAFETY_OR_INCIDENT"
    PARTISAN_OR_RESULTS_GUARDRAIL = "PARTISAN_OR_RESULTS_GUARDRAIL"


class PublicRecordCitation(BaseModel):
    """Verified public electoral/civic document citation returned by Civic AI chat."""

    doc_id: str
    title: str
    published_date: str
    source_url: str
    summary: str


class ChatAssistantResponse(BaseModel):
    """Conversational plain-language Civic AI response suitable for all ages."""

    request_id: str
    detected_intent: str
    friendly_answer: str
    guidance_steps: list[str] = Field(default_factory=list)
    spoken_verdict: SpokenVerdict
    media_verification: VerificationResponse | None = None
    citations: list[PublicRecordCitation] = Field(default_factory=list)
    suggested_tab: Literal["chat", "safety", "screening"] = "chat"


class PollingUnitInfo(BaseModel):
    """Synthetic/reference Nigerian polling unit details for location registration."""

    pu_code: str
    pu_name: str
    ward: str
    lga: str
    state: str
    lat: float = 0.0
    lon: float = 0.0
    accessibility_note: str
    official_lookup_url: str = "https://voters.inecnigeria.org"


class NearestLocationIn(BaseModel):
    """Ephemeral GPS coordinates matched on-server without storing raw lat/lon."""

    citizen_alias: str = Field(min_length=2, max_length=60)
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)


class NearestLocationResponse(BaseModel):
    """Nearest reference polling unit computed via Haversine distance (raw coords discarded)."""

    session_id: str
    citizen_alias: str
    polling_unit: PollingUnitInfo
    distance_km: float
    nearby_registered_demo_users: int
    privacy_notice: str = (
        "NDPA 2023 Data Minimization: Raw GPS coordinates were used ephemerally to match your ward unit "
        "and were NOT stored."
    )


class LocationRegistrationIn(BaseModel):
    """Consent-based synthetic/anonymous location registration."""

    citizen_alias: str = Field(min_length=2, max_length=60)
    state: str
    lga: str
    ward: str
    emergency_contact_label: str = Field(default="Family / Ward Observer (Demo)", max_length=80)


class LocationRegistrationResponse(BaseModel):
    """Registered polling unit assignment & safety shield status."""

    session_id: str
    citizen_alias: str
    polling_unit: PollingUnitInfo
    nearby_registered_demo_users: int
    privacy_notice: str = (
        "Zero real PII stored. Only ward/polling-unit code and anonymous session alias are used for demo alerts."
    )


class SosPingIn(BaseModel):
    """Shake-gesture or panic-button danger alert."""

    citizen_alias: str = Field(min_length=2, max_length=60)
    pu_code: str
    trigger_method: Literal["SHAKE_GESTURE", "PANIC_BUTTON"] = "SHAKE_GESTURE"
    note: str = Field(default="", max_length=240)


class SosAlertRecord(BaseModel):
    """Single logged safety ping."""

    alert_id: str
    citizen_alias: str
    pu_code: str
    trigger_method: Literal["SHAKE_GESTURE", "PANIC_BUTTON"]
    created_at: datetime
    note: str = ""


class SafeInterviewIn(BaseModel):
    """Structured 'I am safe' check-in chat interview to prevent half/biased stories."""

    citizen_alias: str = Field(min_length=2, max_length=60)
    pu_code: str
    is_safe_now: bool = True
    incident_category: Literal[
        "FALSE_RUMOR_PANIC",
        "INTIMIDATION_OR_THREAT",
        "BALLOT_OR_EQUIPMENT_DISRUPTION",
        "PHYSICAL_ALTERCATION",
        "LOGISTICS_DELAY_CALM",
        "OTHER",
    ]
    eyewitness_type: Literal["DIRECT_EYEWITNESS", "HEARD_FROM_OTHERS"]
    narrative: str = Field(min_length=5, max_length=600)


class SafeInterviewRecord(BaseModel):
    """Stored witness account after safety confirmation."""

    interview_id: str
    citizen_alias: str
    pu_code: str
    is_safe_now: bool
    incident_category: str
    eyewitness_type: str
    narrative: str
    submitted_at: datetime


class CorroboratedStorySummary(BaseModel):
    """Multi-witness corroborated incident synthesis preventing half/biased stories."""

    pu_code: str
    pu_name: str
    active_sos_count_last_10m: int
    cluster_alert_level: Literal["CALM", "SINGLE_ALERT_MONITORING", "CLUSTER_HIGH_ALERT"]
    broadcast_warnings: list[str]
    corroboration_status: Literal[
        "NO_INCIDENTS",
        "UNCORROBORATED_SINGLE_REPORT",
        "CONFLICTING_ACCOUNTS",
        "MULTI_WITNESS_CORROBORATED",
    ]
    total_interviews: int
    direct_eyewitness_count: int
    secondhand_count: int
    balanced_summary: str
    category_breakdown: dict[str, int] = Field(default_factory=dict)
    witness_perspectives: list[SafeInterviewRecord] = Field(default_factory=list)


class SafetyDashboardResponse(BaseModel):
    """Full Polling Unit Safety & Multi-Witness Corroboration status."""

    sandbox_notice: str = (
        "Safety & Observer Broadcast Sandbox (Demo Mode) — simulates ward alerts and witness corroboration. "
        "For real physical danger in Nigeria, call official emergency services (112)."
    )
    selected_pu_code: str
    story: CorroboratedStorySummary
    recent_alerts: list[SosAlertRecord]


class InterviewChatIn(BaseModel):
    """Conversational 'I Am Safe' AI follow-up interview step."""

    citizen_alias: str = Field(min_length=2, max_length=60)
    pu_code: str
    message: str = Field(min_length=2, max_length=600)
    eyewitness_type: Literal["DIRECT_EYEWITNESS", "HEARD_FROM_OTHERS", "UNKNOWN"] = "UNKNOWN"


class InterviewChatResponse(BaseModel):
    """AI interviewer reply + updated corroboration when witness details are complete."""

    reply_text: str
    inferred_category: str
    eyewitness_confirmed: bool
    interview_saved: bool
    safety_status: SafetyDashboardResponse | None = None

