"""Automated unit & integration tests for VeriShield NG Shared Forensics Core and Responsible-AI Contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.civic import build_spoken_verdict, match_claim_against_notices  # noqa: E402
from backend.app.civic import assistant as civic_assistant  # noqa: E402
from backend.app.civic.factcheck import extract_search_query  # noqa: E402
from backend.app.config import SYNTHETIC_DIR, SupportedLanguage, VerdictCode  # noqa: E402
from backend.app.forensics import analyze_audio, analyze_image  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.schemas import PublicRecordCitation  # noqa: E402
from scripts.generate_synthetic_dataset import main as generate_dataset  # noqa: E402


def setup_module(module: object) -> None:
    """Ensure deterministic synthetic benchmark fixtures exist before running tests."""
    if not (SYNTHETIC_DIR / "manifest.json").exists():
        generate_dataset()


def test_multilingual_spoken_verdict_covers_all_five_languages_and_four_verdicts() -> None:
    for verdict in VerdictCode:
        for lang in SupportedLanguage:
            spoken = build_spoken_verdict(verdict, lang)
            assert spoken.language == lang
            assert len(spoken.text) > 40
            assert 8 <= spoken.estimated_duration_seconds <= 30
            assert spoken.audio_b64_wav is not None and len(spoken.audio_b64_wav) > 100


def test_notice_matcher_flags_postponement_and_online_voting_contradictions() -> None:
    matches = match_claim_against_notices("Breaking news: Presidential election postponed indefinitely, vote by SMS.")
    assert any(m.contradiction_found for m in matches)

    benign = match_claim_against_notices("Official INEC 2027 General Election Timetable January 16, 2027.")
    assert benign and not any(m.contradiction_found for m in benign)


def test_shared_visual_forensics_core_on_flyer_and_portrait_modes() -> None:
    clean_flyer = (SYNTHETIC_DIR / "flyers" / "flyer_authentic_timetable.jpg").read_bytes()
    spliced_flyer = (SYNTHETIC_DIR / "flyers" / "flyer_spliced_forged.jpg").read_bytes()
    moire_flyer = (SYNTHETIC_DIR / "flyers" / "flyer_screen_spoof.jpg").read_bytes()
    blur_flyer = (SYNTHETIC_DIR / "flyers" / "flyer_whatsapp_blur_inconclusive.jpg").read_bytes()

    assert analyze_image(clean_flyer, mode="flyer").verdict_code == VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS
    assert analyze_image(spliced_flyer, mode="flyer").verdict_code == VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS
    assert analyze_image(moire_flyer, mode="flyer").verdict_code == VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS
    blur_res = analyze_image(blur_flyer, mode="flyer")
    assert blur_res.verdict_code == VerdictCode.INCONCLUSIVE
    assert blur_res.compression_degradation_detected is True

    # Same visual core reused in portrait mode for Module B
    ai_portrait = (SYNTHETIC_DIR / "portraits" / "synth_ai_face_01.png").read_bytes()
    spoof_portrait = (SYNTHETIC_DIR / "portraits" / "synth_screen_spoof_01.jpg").read_bytes()
    clean_portrait = (SYNTHETIC_DIR / "portraits" / "synth_clean_01.jpg").read_bytes()

    assert analyze_image(clean_portrait, mode="portrait").verdict_code == VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS
    assert analyze_image(ai_portrait, mode="portrait").verdict_code == VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS
    assert analyze_image(spoof_portrait, mode="portrait").verdict_code == VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS


def test_acoustic_forensics_detects_spoof_and_calibrates_whatsapp_ogg_to_inconclusive() -> None:
    clean_wav = (SYNTHETIC_DIR / "audio" / "voice_authentic_demo.wav").read_bytes()
    spoof_wav = (SYNTHETIC_DIR / "audio" / "voice_synthetic_clone_demo.wav").read_bytes()

    clean_res = analyze_audio(clean_wav, filename="voice_authentic_demo.wav")
    spoof_res = analyze_audio(spoof_wav, filename="voice_synthetic_clone_demo.wav")
    assert clean_res.verdict_code == VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS
    assert spoof_res.verdict_code == VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS

    ogg_path = SYNTHETIC_DIR / "audio" / "voice_whatsapp_narrowband.ogg"
    if ogg_path.exists():
        ogg_res = analyze_audio(ogg_path.read_bytes(), filename="voice_whatsapp_narrowband.ogg")
        assert ogg_res.compression_degradation_detected is True
        assert ogg_res.verdict_code == VerdictCode.INCONCLUSIVE


def test_fastapi_module_a_and_module_b_end_to_end() -> None:
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert len(client.get("/api/v1/languages").json()["languages"]) == 5

    # Module A flyer contradiction + Pidgin spoken verdict
    flyer_bytes = (SYNTHETIC_DIR / "flyers" / "flyer_authentic_timetable.jpg").read_bytes()
    resp = client.post(
        "/api/v1/module-a/verify-flyer",
        data={"language": "pcm", "claim_text": "Dem don cancel election tomorrow, vote by WhatsApp"},
        files={"file": ("notice.jpg", flyer_bytes, "image/jpeg")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict_code"] == VerdictCode.CONTRADICTS_OFFICIAL_NOTICE.value
    assert body["spoken_verdict"]["language"] == "pcm"
    assert "never declares election winners" in body["nonpartisan_disclaimer"].lower()

    # Module A audio endpoint
    spoof_bytes = (SYNTHETIC_DIR / "audio" / "voice_synthetic_clone_demo.wav").read_bytes()
    audio_resp = client.post(
        "/api/v1/module-a/verify-audio",
        data={"language": "ig"},
        files={"file": ("spoof.wav", spoof_bytes, "audio/wav")},
    )
    assert audio_resp.status_code == 200
    assert audio_resp.json()["verdict_code"] == VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS.value
    assert audio_resp.json()["spoken_verdict"]["language"] == "ig"

    # Module B queue reload + human-in-the-loop supervisor decision
    reload_resp = client.post("/api/v1/module-b/reload")
    assert reload_resp.status_code == 200
    q = reload_resp.json()
    assert q["total_records"] == 25
    assert q["burst_anomalies_detected"] == 14
    assert q["flagged_for_review"] == 19

    by_id = {item["record_id"]: item for item in q["items"]}
    assert by_id["SYNTH-REG-0001"]["anomaly_reasons"] == []
    assert by_id["SYNTH-REG-0007"]["visual_verdict_code"] == VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS.value
    assert by_id["SYNTH-REG-0010"]["duplicate_face_cluster"] == by_id["SYNTH-REG-0011"]["duplicate_face_cluster"]
    assert by_id["SYNTH-REG-0010"]["duplicate_face_cluster"] is not None

    flagged_id = next(item["record_id"] for item in q["items"] if item["anomaly_reasons"])
    review_resp = client.post(
        f"/api/v1/module-b/review/{flagged_id}",
        json={
            "decision": "ESCALATED_FOR_AUDIT",
            "supervisor_alias": "SUP-TEST-01",
            "rationale": "Escalated synthetic intake burst record for human inspection.",
        },
    )
    assert review_resp.status_code == 200
    reviewed = review_resp.json()
    assert reviewed["review_status"] == "ESCALATED_FOR_AUDIT"
    assert len(reviewed["audit_log"]) == 2


def test_conversational_civic_ai_chat_intents_and_media_attachment() -> None:
    client = TestClient(app)

    # 1. Plain-language rumor detection (Pidgin)
    r_rumor = client.post(
        "/api/v1/module-a/chat",
        data={"message": "Dem say presidential election don shift?", "language": "pcm"},
    )
    assert r_rumor.status_code == 200
    d_rumor = r_rumor.json()
    assert d_rumor["detected_intent"] == "VERIFY_MEDIA_OR_RUMOR"
    assert d_rumor["spoken_verdict"]["language"] == "pcm"
    assert "false" in d_rumor["friendly_answer"].lower() or "misleading" in d_rumor["friendly_answer"].lower()

    # 2. Factual published record / Electoral Act Q&A
    r_pwd = client.post(
        "/api/v1/module-a/chat",
        data={"message": "How can blind or elderly voters get help and check published candidate achievement records?", "language": "en"},
    )
    assert r_pwd.status_code == 200
    d_pwd = r_pwd.json()
    assert d_pwd["detected_intent"] == "PUBLIC_RECORD_OR_FACT_QA"
    doc_ids = {c["doc_id"] for c in d_pwd["citations"]}
    assert "DOC-ELECTORAL-ACT-2022-PWD" in doc_ids
    assert "DOC-CIVIC-TRANSCRIPT-RECORDS" in doc_ids

    # 3. Nonpartisan guardrail on winner/endorsement query
    r_guard = client.post(
        "/api/v1/module-a/chat",
        data={"message": "Who won the election and who should I vote for?", "language": "en"},
    )
    assert r_guard.status_code == 200
    assert r_guard.json()["detected_intent"] == "PARTISAN_OR_RESULTS_GUARDRAIL"

    # 4. Chat with attached spliced flyer automatically invokes Shared Visual Forensics Core
    spliced_bytes = (SYNTHETIC_DIR / "flyers" / "flyer_spliced_forged.jpg").read_bytes()
    r_media = client.post(
        "/api/v1/module-a/chat",
        data={"message": "Please check this flyer for my grandmother", "language": "yo"},
        files={"file": ("forged.jpg", spliced_bytes, "image/jpeg")},
    )
    assert r_media.status_code == 200
    d_media = r_media.json()
    assert d_media["media_verification"]["verdict_code"] == VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS.value
    assert d_media["spoken_verdict"]["language"] == "yo"


def test_location_shake_sos_cluster_and_multi_witness_corroboration() -> None:
    client = TestClient(app)

    # 1. Location registration assigns demo Polling Unit
    loc_resp = client.post(
        "/api/v1/location/register",
        json={
            "citizen_alias": "Elder-Musa-Test",
            "state": "Federal Capital Territory",
            "lga": "Abuja Municipal (AMAC)",
            "ward": "Wuse",
        },
    )
    assert loc_resp.status_code == 200
    pu_code = loc_resp.json()["polling_unit"]["pu_code"]
    assert pu_code == "PU-FC-AMAC-001"

    # 2. Seeded Ikeja unit shows pre-existing conflicting accounts (prevents half-story bias)
    ikeja_status = client.get("/api/v1/safety/status", params={"pu_code": "PU-LA-IKJ-004"}).json()
    assert ikeja_status["story"]["corroboration_status"] == "CONFLICTING_ACCOUNTS"

    # 3. First shake alert on Wuse unit -> SINGLE_ALERT_MONITORING
    sos1 = client.post(
        "/api/v1/safety/sos",
        json={"citizen_alias": "User-Wuse-A", "pu_code": pu_code, "trigger_method": "SHAKE_GESTURE"},
    ).json()
    assert sos1["story"]["cluster_alert_level"] == "SINGLE_ALERT_MONITORING"

    # 4. Second distinct user shake in same sequence/location -> escalates to CLUSTER_HIGH_ALERT
    sos2 = client.post(
        "/api/v1/safety/sos",
        json={"citizen_alias": "User-Wuse-B", "pu_code": pu_code, "trigger_method": "SHAKE_GESTURE"},
    ).json()
    assert sos2["story"]["cluster_alert_level"] == "CLUSTER_HIGH_ALERT"
    assert sos2["story"]["active_sos_count_last_10m"] == 2
    assert len(sos2["story"]["broadcast_warnings"]) >= 2

    # 5. Single "I'm safe" interview -> UNCORROBORATED_SINGLE_REPORT (half-story risk flagged)
    int1 = client.post(
        "/api/v1/safety/interview",
        json={
            "citizen_alias": "User-Wuse-A",
            "pu_code": pu_code,
            "is_safe_now": True,
            "incident_category": "FALSE_RUMOR_PANIC",
            "eyewitness_type": "DIRECT_EYEWITNESS",
            "narrative": "Someone shouted a fake WhatsApp rumor; officials calmed voters immediately.",
        },
    ).json()
    assert int1["story"]["corroboration_status"] == "UNCORROBORATED_SINGLE_REPORT"

    # 6. Second independent eyewitness aligns -> MULTI_WITNESS_CORROBORATED
    int2 = client.post(
        "/api/v1/safety/interview",
        json={
            "citizen_alias": "User-Wuse-B",
            "pu_code": pu_code,
            "is_safe_now": True,
            "incident_category": "FALSE_RUMOR_PANIC",
            "eyewitness_type": "DIRECT_EYEWITNESS",
            "narrative": "Confirmed: no fight occurred, only brief panic over a fake cancellation message.",
        },
    ).json()
    assert int2["story"]["corroboration_status"] == "MULTI_WITNESS_CORROBORATED"
    assert int2["story"]["direct_eyewitness_count"] == 2


def test_pidgin_candidate_withdrawal_rumor_and_live_factcheck_adapter(monkeypatch: object) -> None:
    # Stopword stripper leaves core subject terms cleanly for live search
    assert extract_search_query("them say peter obi don drop from election") == "peter obi drop election"

    client = TestClient(app)

    # 1. With mocked Dubawa citation hit (offline-deterministic)
    mock_hit = PublicRecordCitation(
        doc_id="DUBAWA-999",
        title="[Dubawa Nigeria] Fact-Check on Viral Candidate Withdrawal Claims",
        published_date="2026-10-15",
        source_url="https://dubawa.org/example-check",
        summary="No verified INEC notice shows any withdrawal.",
    )
    monkeypatch.setattr(civic_assistant, "search_live_factchecks", lambda q, max_per_source=2: [mock_hit])  # type: ignore[attr-defined]

    resp = client.post(
        "/api/v1/module-a/chat",
        data={"message": "them say peter obi don drop from election", "language": "pcm"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["detected_intent"] == "VERIFY_MEDIA_OR_RUMOR"
    assert "dropped out" in body["friendly_answer"].lower() or "withdrawal" in body["friendly_answer"].lower()
    assert any(c["doc_id"] == "DUBAWA-999" for c in body["citations"])

    # 2. Offline / zero-hit fallback still catches "them say" withdrawal tactic safely
    monkeypatch.setattr(civic_assistant, "search_live_factchecks", lambda q, max_per_source=2: [])  # type: ignore[attr-defined]
    offline_resp = client.post(
        "/api/v1/module-a/chat",
        data={"message": "them say peter obi don drop from election", "language": "en"},
    )
    assert offline_resp.status_code == 200
    assert "dubawa" in offline_resp.json()["friendly_answer"].lower()


def test_ephemeral_gps_nearest_pu_and_ai_interview_chat() -> None:
    client = TestClient(app)

    # Ephemeral GPS near Alausa, Ikeja assigns PU-LA-IKJ-004 within < 0.5 km
    gps_resp = client.post(
        "/api/v1/location/nearest",
        json={"citizen_alias": "GPS-Elder-Demo", "lat": 6.6145, "lon": 3.3582},
    )
    assert gps_resp.status_code == 200
    gps_data = gps_resp.json()
    assert gps_data["polling_unit"]["pu_code"] == "PU-LA-IKJ-004"
    assert gps_data["distance_km"] < 0.5
    assert "not stored" in gps_data["privacy_notice"].lower()

    # Ephemeral GPS near Surulere assigns PU-LA-SUR-011
    sur_resp = client.post(
        "/api/v1/location/nearest",
        json={"citizen_alias": "GPS-Surulere-Demo", "lat": 6.4970, "lon": 3.3650},
    )
    assert sur_resp.status_code == 200
    assert sur_resp.json()["polling_unit"]["pu_code"] == "PU-LA-SUR-011"

    # Conversational "I Am Safe" AI interviewer asks follow-up when eyewitness certainty is UNKNOWN
    chat1 = client.post(
        "/api/v1/safety/interview/chat",
        json={
            "citizen_alias": "Interview-User-01",
            "pu_code": "PU-FC-AMAC-001",
            "message": "There was shouting about BVAS delay near gate 1, queue calm now.",
            "eyewitness_type": "UNKNOWN",
        },
    )
    assert chat1.status_code == 200
    c1 = chat1.json()
    assert c1["eyewitness_confirmed"] is False
    assert c1["interview_saved"] is False
    assert "own eyes" in c1["reply_text"].lower() or "social media" in c1["reply_text"].lower()

    # Supplying certainty via text ("I saw it myself") confirms & saves interview into corroboration
    chat2 = client.post(
        "/api/v1/safety/interview/chat",
        json={
            "citizen_alias": "Interview-User-01",
            "pu_code": "PU-FC-AMAC-001",
            "message": "I saw it myself: BVAS machine took 20 minutes to reboot, queue calm now.",
            "eyewitness_type": "DIRECT_EYEWITNESS",
        },
    )
    assert chat2.status_code == 200
    c2 = chat2.json()
    assert c2["eyewitness_confirmed"] is True
    assert c2["interview_saved"] is True
    assert c2["safety_status"] is not None


def test_multipage_frontend_and_pwa_routes() -> None:
    client = TestClient(app)

    for path in ["/", "/citizen", "/screening"]:
        r = client.get(path)
        assert r.status_code == 200
        assert "VeriShield" in r.text

    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json()["start_url"] == "/citizen"

    sw = client.get("/sw.js")
    assert sw.status_code == 200
    assert "verishield-ng" in sw.text

    icon = client.get("/icon.svg")
    assert icon.status_code == 200
    assert "<svg" in icon.text

    directory = client.get("/api/v1/location/directory")
    assert directory.status_code == 200
    assert len(directory.json()["polling_units"]) >= 8


