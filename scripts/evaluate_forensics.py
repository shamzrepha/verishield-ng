"""Evaluate VeriShield NG Shared Forensics Core against the synthetic benchmark dataset."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.civic import match_claim_against_notices  # noqa: E402
from backend.app.config import SYNTHETIC_DIR, VerdictCode  # noqa: E402
from backend.app.forensics import analyze_audio, analyze_image  # noqa: E402
from backend.app.registry import SupervisorQueueStore  # noqa: E402


def main() -> int:
    manifest_path = SYNTHETIC_DIR / "manifest.json"
    if not manifest_path.exists():
        print("Synthetic dataset not found. Run scripts/generate_synthetic_dataset.py first.")
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    samples = manifest.get("samples", [])
    passed = 0

    print("=== Module A Synthetic Benchmark ===")
    for item in samples:
        target = SYNTHETIC_DIR / item["category"] / item["filename"]
        raw = target.read_bytes()
        if item["category"] == "flyers":
            res = analyze_image(raw, mode="flyer")
            verdict = res.verdict_code
            matches = match_claim_against_notices(item.get("claim_text"))
            if any(m.contradiction_found for m in matches) and verdict in {
                VerdictCode.OFFICIAL_MATCH_OR_NO_INDICATORS,
                VerdictCode.INCONCLUSIVE,
            }:
                verdict = VerdictCode.CONTRADICTS_OFFICIAL_NOTICE
        else:
            res = analyze_audio(raw, filename=item["filename"])
            verdict = res.verdict_code

        expected = item["expected_verdict"]
        ok = verdict.value == expected
        passed += int(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {item['id']}: got={verdict.value} expected={expected}")

    store = SupervisorQueueStore(SYNTHETIC_DIR)
    queue = store.get_queue(flagged_only=False)
    print("\n=== Module B Synthetic Intake Queue Summary ===")
    print(
        f"  total={queue.total_records}, flagged={queue.flagged_for_review}, "
        f"burst_anomalies={queue.burst_anomalies_detected}"
    )
    print(f"\nBenchmark score: {passed}/{len(samples)} Module A cases matched calibrated expectations.")
    return 0 if passed == len(samples) else 2


if __name__ == "__main__":
    raise SystemExit(main())
