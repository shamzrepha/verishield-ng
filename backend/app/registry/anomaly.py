"""Batch upload-burst anomaly detection, perceptual face deduplication, and Supervisor Review Queue."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import ReviewStatus, SYNTHETIC_DIR, THRESHOLDS, VERDICT_LABELS, VerdictCode
from ..forensics.visual import analyze_image, hamming_distance_hex
from ..schemas import AuditLogEntry, IntakeRecordIn, IntakeReviewItem, ReviewDecisionIn, SupervisorQueueResponse


def detect_burst_anomalies(records: list[IntakeRecordIn]) -> dict[str, list[str]]:
    """Flag sliding-window upload spikes and off-hours (00:00-05:00) high-rate operator bursts."""
    reasons_by_id: dict[str, list[str]] = defaultdict(list)
    by_operator: dict[str, list[IntakeRecordIn]] = defaultdict(list)

    for rec in records:
        by_operator[rec.operator_id].append(rec)

    window = timedelta(minutes=THRESHOLDS.burst_window_minutes)
    for op_id, op_records in by_operator.items():
        op_records.sort(key=lambda r: r.captured_at)
        left = 0
        for right, rec in enumerate(op_records):
            while rec.captured_at - op_records[left].captured_at > window:
                left += 1
            count_in_window = right - left + 1
            if count_in_window >= THRESHOLDS.burst_count_threshold:
                for member in op_records[left : right + 1]:
                    msg = (
                        f"Upload burst: operator {op_id} uploaded {count_in_window} records within "
                        f"{THRESHOLDS.burst_window_minutes} min."
                    )
                    if msg not in reasons_by_id[member.record_id]:
                        reasons_by_id[member.record_id].append(msg)

            # Off-hours anomaly if >=4 records captured between 00:00 and 04:59
            if 0 <= rec.captured_at.hour < 5 and count_in_window >= 4:
                msg = f"Off-hours intake spike ({rec.captured_at.strftime('%H:%M')} WAT) by operator {op_id}."
                if msg not in reasons_by_id[rec.record_id]:
                    reasons_by_id[rec.record_id].append(msg)

    return reasons_by_id


def evaluate_synthetic_batch(
    records: list[IntakeRecordIn],
    image_lookup: dict[str, bytes],
) -> list[IntakeReviewItem]:
    """Run the Shared Visual Forensics Core + burst & duplicate checks on a synthetic batch."""
    burst_reasons = detect_burst_anomalies(records)
    visual_results = {}
    dhash_clusters: list[tuple[str, str]] = []  # (cluster_id, dhash_hex)
    cluster_for_record: dict[str, str | None] = {}

    for rec in records:
        raw_bytes = image_lookup.get(rec.image_filename)
        if not raw_bytes:
            continue
        vis = analyze_image(raw_bytes, mode="portrait")
        visual_results[rec.record_id] = vis

        matched_cluster: str | None = None
        for cid, chash in dhash_clusters:
            if hamming_distance_hex(vis.dhash_hex, chash) <= 1:
                matched_cluster = cid
                break
        if matched_cluster is None:
            matched_cluster = f"FACE-CLUSTER-{len(dhash_clusters) + 1:03d}"
            dhash_clusters.append((matched_cluster, vis.dhash_hex))
        cluster_for_record[rec.record_id] = matched_cluster

    cluster_counts: dict[str, int] = defaultdict(int)
    for cid in cluster_for_record.values():
        if cid is not None:
            cluster_counts[cid] += 1

    items: list[IntakeReviewItem] = []
    for rec in records:
        vis = visual_results.get(rec.record_id)
        if vis is None:
            continue
        reasons = list(burst_reasons.get(rec.record_id, []))
        cid = cluster_for_record.get(rec.record_id)
        dup_cluster = cid if (cid and cluster_counts[cid] > 1) else None
        if dup_cluster:
            reasons.append(f"Near-duplicate portrait hash matched across multiple synthetic records ({dup_cluster}).")

        if vis.verdict_code == VerdictCode.SYNTHETIC_OR_TAMPER_INDICATORS:
            reasons.append("Shared Visual Forensics Core flagged synthetic portrait or screen-recapture traces.")
        elif vis.verdict_code == VerdictCode.INCONCLUSIVE:
            reasons.append("Low-quality/degraded portrait requires human review or recapture.")

        items.append(
            IntakeReviewItem(
                record_id=rec.record_id,
                synthetic_applicant_alias=rec.synthetic_applicant_alias,
                operator_id=rec.operator_id,
                station_code=rec.station_code,
                captured_at=rec.captured_at,
                image_filename=rec.image_filename,
                visual_verdict_code=vis.verdict_code,
                visual_verdict_label=VERDICT_LABELS[vis.verdict_code],
                ai_face_likelihood=vis.ai_face_likelihood,
                screen_spoof_likelihood=vis.screen_spoof_likelihood,
                duplicate_face_cluster=dup_cluster,
                burst_anomaly_flag=bool(burst_reasons.get(rec.record_id)),
                anomaly_reasons=reasons,
                signals=vis.signals,
                review_status=ReviewStatus.PENDING_REVIEW,
                audit_log=[
                    AuditLogEntry(
                        timestamp=datetime.now(timezone.utc),
                        actor="verishield_forensics_core",
                        action="SCREENED",
                        rationale=(
                            "Queued for human supervisor review."
                            if reasons
                            else "No visual or burst anomalies detected; available in audit log."
                        ),
                    )
                ],
            )
        )

    # Sort flagged items first so supervisors triage highest-risk records immediately
    items.sort(key=lambda it: (len(it.anomaly_reasons) == 0, -max(it.ai_face_likelihood, it.screen_spoof_likelihood)))
    return items


class SupervisorQueueStore:
    """In-memory Supervisor Review Queue backed by the synthetic demo batch."""

    def __init__(self, synthetic_dir: Path = SYNTHETIC_DIR) -> None:
        self._synthetic_dir = synthetic_dir
        self._items: dict[str, IntakeReviewItem] = {}
        self.reload_from_disk()

    def reload_from_disk(self) -> None:
        manifest_path = self._synthetic_dir / "registry_batch.json"
        if not manifest_path.exists():
            self._items = {}
            return

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = [IntakeRecordIn.model_validate(item) for item in payload.get("records", [])]
        portraits_dir = self._synthetic_dir / "portraits"
        image_lookup: dict[str, bytes] = {}
        for rec in records:
            img_path = portraits_dir / rec.image_filename
            if img_path.exists():
                image_lookup[rec.image_filename] = img_path.read_bytes()

        evaluated = evaluate_synthetic_batch(records, image_lookup)
        self._items = {item.record_id: item for item in evaluated}

    def upsert_item(self, item: IntakeReviewItem) -> IntakeReviewItem:
        self._items[item.record_id] = item
        return item

    def get_queue(self, flagged_only: bool = False) -> SupervisorQueueResponse:
        all_items = list(self._items.values())
        filtered = [it for it in all_items if it.anomaly_reasons] if flagged_only else all_items
        return SupervisorQueueResponse(
            total_records=len(all_items),
            flagged_for_review=sum(1 for it in all_items if it.anomaly_reasons),
            pending_review=sum(
                1 for it in all_items if it.anomaly_reasons and it.review_status == ReviewStatus.PENDING_REVIEW
            ),
            burst_anomalies_detected=sum(1 for it in all_items if it.burst_anomaly_flag),
            items=filtered,
        )

    def record_decision(self, record_id: str, decision: ReviewDecisionIn) -> IntakeReviewItem:
        item = self._items.get(record_id)
        if item is None:
            raise KeyError(f"Synthetic intake record '{record_id}' not found.")

        new_status = ReviewStatus(decision.decision)
        updated_log = [
            *item.audit_log,
            AuditLogEntry(
                timestamp=datetime.now(timezone.utc),
                actor=decision.supervisor_alias,
                action=new_status.value,
                rationale=decision.rationale,
            ),
        ]
        updated = item.model_copy(update={"review_status": new_status, "audit_log": updated_log})
        self._items[record_id] = updated
        return updated
