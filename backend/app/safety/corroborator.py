"""Shake-to-Alert geospatial clustering and Multi-Witness 'Anti-Half-Story' corroboration engine."""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from ..civic.polling_units import get_polling_unit_by_code
from ..schemas import (
    CorroboratedStorySummary,
    InterviewChatIn,
    InterviewChatResponse,
    SafeInterviewIn,
    SafeInterviewRecord,
    SafetyDashboardResponse,
    SosAlertRecord,
    SosPingIn,
)

CLUSTER_WINDOW_MINUTES = 10
CLUSTER_ESCALATION_THRESHOLD = 2


class SafetyAlertStore:
    """In-memory sandbox store for ward shake-alerts and multi-witness incident interviews."""

    def __init__(self) -> None:
        self._alerts: dict[str, list[SosAlertRecord]] = defaultdict(list)
        self._interviews: dict[str, list[SafeInterviewRecord]] = defaultdict(list)
        self._seed_demo_scenarios()

    def _seed_demo_scenarios(self) -> None:
        now = datetime.now(timezone.utc)
        # Pre-seed 1 active single-user alert + 2 conflicting witness reports at Ikeja demo unit
        # so users can immediately see how a 2nd shake escalates and how multi-witness corroboration prevents half-stories
        self._alerts["PU-LA-IKJ-004"] = [
            SosAlertRecord(
                alert_id="SOS-DEMO-01",
                citizen_alias="Citizen-Amina-Demo",
                pu_code="PU-LA-IKJ-004",
                trigger_method="SHAKE_GESTURE",
                created_at=now - timedelta(minutes=3),
                note="Rapid phone shake detected near entrance gate (synthetic demo).",
            )
        ]
        self._interviews["PU-LA-IKJ-004"] = [
            SafeInterviewRecord(
                interview_id="INT-DEMO-01",
                citizen_alias="Citizen-Amina-Demo",
                pu_code="PU-LA-IKJ-004",
                is_safe_now=True,
                incident_category="FALSE_RUMOR_PANIC",
                eyewitness_type="DIRECT_EYEWITNESS",
                narrative="People panicked after someone shouted a fake WhatsApp rumor that voting was cancelled; no weapons or fighting occurred.",
                submitted_at=now - timedelta(minutes=2),
            ),
            SafeInterviewRecord(
                interview_id="INT-DEMO-02",
                citizen_alias="Citizen-Tunde-Demo",
                pu_code="PU-LA-IKJ-004",
                is_safe_now=True,
                incident_category="INTIMIDATION_OR_THREAT",
                eyewitness_type="HEARD_FROM_OTHERS",
                narrative="Someone told me touts were shouting outside the gate, though I did not see them directly inside the courtyard.",
                submitted_at=now - timedelta(minutes=1),
            ),
        ]

    def trigger_sos(self, payload: SosPingIn) -> SafetyDashboardResponse:
        rec = SosAlertRecord(
            alert_id=f"SOS-{uuid.uuid4().hex[:6].upper()}",
            citizen_alias=payload.citizen_alias,
            pu_code=payload.pu_code,
            trigger_method=payload.trigger_method,
            created_at=datetime.now(timezone.utc),
            note=payload.note or "Phone shake danger signal triggered.",
        )
        self._alerts[payload.pu_code].append(rec)
        return self.get_status(payload.pu_code)

    def submit_interview(self, payload: SafeInterviewIn) -> SafetyDashboardResponse:
        rec = SafeInterviewRecord(
            interview_id=f"INT-{uuid.uuid4().hex[:6].upper()}",
            citizen_alias=payload.citizen_alias,
            pu_code=payload.pu_code,
            is_safe_now=payload.is_safe_now,
            incident_category=payload.incident_category,
            eyewitness_type=payload.eyewitness_type,
            narrative=payload.narrative.strip(),
            submitted_at=datetime.now(timezone.utc),
        )
        self._interviews[payload.pu_code].append(rec)
        return self.get_status(payload.pu_code)

    def _build_story(self, pu_code: str) -> CorroboratedStorySummary:
        pu = get_polling_unit_by_code(pu_code)
        pu_name = pu.pu_name if pu else f"Polling Unit {pu_code}"

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=CLUSTER_WINDOW_MINUTES)
        recent_alerts = [a for a in self._alerts.get(pu_code, []) if a.created_at >= cutoff]
        distinct_alert_users = {a.citizen_alias for a in recent_alerts}
        active_count = len(distinct_alert_users)

        broadcasts: list[str] = []
        if active_count >= CLUSTER_ESCALATION_THRESHOLD:
            cluster_level = "CLUSTER_HIGH_ALERT"
            broadcasts.append(
                f"CLUSTER ALERT ({active_count} distinct citizens in {CLUSTER_WINDOW_MINUTES} min): "
                f"Simulated warning sent to nearby registered voters around {pu_name} to exercise caution."
            )
            broadcasts.append(
                "Simulated escalation dispatched to Ward Accredited Observer & Security Coordination Desk (Demo Sandbox)."
            )
        elif active_count == 1:
            cluster_level = "SINGLE_ALERT_MONITORING"
            broadcasts.append(
                "Single shake alert logged. Personal emergency contact notified (Demo); monitoring area for corroborating signals."
            )
        else:
            cluster_level = "CALM"

        interviews = list(self._interviews.get(pu_code, []))
        direct_list = [it for it in interviews if it.eyewitness_type == "DIRECT_EYEWITNESS"]
        secondhand_list = [it for it in interviews if it.eyewitness_type == "HEARD_FROM_OTHERS"]

        # Weight direct eyewitness accounts (2x) vs secondhand reports (1x) to avoid rumor amplification
        weighted_counts: Counter[str] = Counter()
        raw_counts: Counter[str] = Counter()
        for it in interviews:
            raw_counts[it.incident_category] += 1
            weight = 2 if it.eyewitness_type == "DIRECT_EYEWITNESS" else 1
            weighted_counts[it.incident_category] += weight

        total_interviews = len(interviews)
        if total_interviews == 0:
            corroboration_status = "NO_INCIDENTS"
            balanced_summary = "No safety incidents reported at this polling unit."
        elif total_interviews == 1:
            corroboration_status = "UNCORROBORATED_SINGLE_REPORT"
            only = interviews[0]
            balanced_summary = (
                f"Half-story warning: Only 1 citizen ({only.citizen_alias}, {only.eyewitness_type.lower().replace('_', ' ')}) "
                f"reported '{only.incident_category}'. Awaiting additional eyewitnesses before drawing conclusions."
            )
        else:
            top_cat, top_weight = weighted_counts.most_common(1)[0]
            total_weight = sum(weighted_counts.values())
            consensus_ratio = top_weight / max(total_weight, 1)

            if len(direct_list) >= 2 and consensus_ratio >= 0.60:
                corroboration_status = "MULTI_WITNESS_CORROBORATED"
                balanced_summary = (
                    f"Multi-witness corroborated ({len(direct_list)} direct eyewitnesses, {len(secondhand_list)} secondhand): "
                    f"Independent accounts align primarily on '{top_cat}' ({consensus_ratio:.0%} weighted agreement). "
                    "Both consensus facts and individual narratives are preserved below."
                )
            else:
                corroboration_status = "CONFLICTING_ACCOUNTS"
                cats_str = ", ".join(f"{k} ({v})" for k, v in raw_counts.items())
                balanced_summary = (
                    f"Conflicting or mixed-reliability stories ({total_interviews} reports: {cats_str}). "
                    f"Direct eyewitnesses ({len(direct_list)}) and secondhand accounts ({len(secondhand_list)}) differ—"
                    "flagged for human observer verification so neither side is distorted."
                )

        return CorroboratedStorySummary(
            pu_code=pu_code,
            pu_name=pu_name,
            active_sos_count_last_10m=active_count,
            cluster_alert_level=cluster_level,  # type: ignore[arg-type]
            broadcast_warnings=broadcasts,
            corroboration_status=corroboration_status,  # type: ignore[arg-type]
            total_interviews=total_interviews,
            direct_eyewitness_count=len(direct_list),
            secondhand_count=len(secondhand_list),
            balanced_summary=balanced_summary,
            category_breakdown=dict(raw_counts),
            witness_perspectives=sorted(interviews, key=lambda r: r.submitted_at, reverse=True),
        )

    def get_status(self, pu_code: str = "PU-LA-IKJ-004") -> SafetyDashboardResponse:
        alerts = sorted(self._alerts.get(pu_code, []), key=lambda a: a.created_at, reverse=True)
        return SafetyDashboardResponse(
            selected_pu_code=pu_code,
            story=self._build_story(pu_code),
            recent_alerts=alerts[:15],
        )

    def process_interview_chat(self, payload: InterviewChatIn) -> InterviewChatResponse:
        """AI witness check-in interviewer: infers category, asks eyewitness follow-up if needed, and updates story."""
        msg = payload.message.strip()
        q = msg.lower()

        if any(w in q for w in ("fight", "beat", "gun", "shoot", "attack", "wound", "violence")):
            category = "PHYSICAL_ALTERCATION"
        elif any(w in q for w in ("bvas", "ballot", "snatch", "box", "spoilt", "machine")):
            category = "BALLOT_OR_EQUIPMENT_DISRUPTION"
        elif any(w in q for w in ("threat", "thug", "intimidat", "shout", "chase", "scare")):
            category = "INTIMIDATION_OR_THREAT"
        elif any(w in q for w in ("late", "queue", "delay", "wait", "calm", "peaceful")):
            category = "LOGISTICS_DELAY_CALM"
        elif any(w in q for w in ("rumor", "rumour", "fake", "whatsapp", "panic", "false")):
            category = "FALSE_RUMOR_PANIC"
        else:
            category = "OTHER"

        inferred_eye = payload.eyewitness_type
        if inferred_eye == "UNKNOWN":
            if any(w in q for w in ("i saw", "my own eyes", "front of me", "i witness", "happened beside me", "i was there")):
                inferred_eye = "DIRECT_EYEWITNESS"
            elif any(w in q for w in ("someone told me", "they told me", "i heard", "friend said", "rumor", "dem say", "them say")):
                inferred_eye = "HEARD_FROM_OTHERS"

        if inferred_eye == "UNKNOWN":
            return InterviewChatResponse(
                reply_text=(
                    f"Glad you are safe. I noted this as '{category.replace('_', ' ').title()}'. "
                    "One quick check so we don't mix up rumors with facts: did you see this directly with your own eyes, "
                    "or did someone else tell you?"
                ),
                inferred_category=category,
                eyewitness_confirmed=False,
                interview_saved=False,
            )

        status = self.submit_interview(
            SafeInterviewIn(
                citizen_alias=payload.citizen_alias,
                pu_code=payload.pu_code,
                is_safe_now=True,
                incident_category=category,  # type: ignore[arg-type]
                eyewitness_type=inferred_eye,  # type: ignore[arg-type]
                narrative=msg,
            )
        )
        return InterviewChatResponse(
            reply_text=(
                f"Thank you—recorded as {inferred_eye.lower().replace('_', ' ')} under '{category.replace('_', ' ')}'. "
                f"Unit status is now: {status.story.corroboration_status.replace('_', ' ')}."
            ),
            inferred_category=category,
            eyewitness_confirmed=True,
            interview_saved=True,
            safety_status=status,
        )
