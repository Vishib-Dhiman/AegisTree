"""Measure System 1 task routing against the keyword rule.

Runs every prompt in scripts/data/system1_eval.json through the Verdict engine
and reports, per split:
  - keyword rule accuracy
  - Verdict accuracy on the prompts where it clears each threshold (coverage)
  - hybrid accuracy (Verdict above threshold, keyword otherwise), as the router does

Usage: .venv/bin/python scripts/calibrate_system1.py [--workspace demo_vault]
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aegis.core.config import config_manager
from aegis.core.models import ChoiceQuery
from aegis.system1.router import (
    TASK_OPTIONS,
    apply_keyword_rule,
    best_option,
    build_context,
    relative_confidence,
)
from aegis.system1.verdict_engine import VerdictDecisionEngine

THRESHOLDS = [0.4, 0.45, 0.5, 0.55, 0.6, 0.7]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default="demo_vault")
    args = parser.parse_args()

    data = json.loads((ROOT / "scripts" / "data" / "system1_eval.json").read_text())
    engine = VerdictDecisionEngine()
    option_ids = {o.id for o in TASK_OPTIONS}
    query = ChoiceQuery(
        id="task_classification",
        question="What type of action is the user requesting?",
        options=TASK_OPTIONS,
        allow_abstention=True,
    )
    current = config_manager.config.system1_confidence_threshold

    for split in ("dev", "test"):
        rows = []
        for item in data[split]:
            res = engine.evaluate_choice(build_context(item["prompt"], args.workspace), query)
            pick = best_option(res.probabilities, option_ids)
            rows.append({
                "label": item["label"],
                "keyword": apply_keyword_rule(item["prompt"]),
                "pick": pick,
                "conf": relative_confidence(res.probabilities, pick, option_ids),
                "latency_ms": res.latency_ms,
            })

        n = len(rows)
        kw = sum(r["keyword"] == r["label"] for r in rows)
        lat = sorted(r["latency_ms"] for r in rows)[n // 2]
        print(f"\n== {split} ({n} prompts, median Verdict latency {lat:.1f} ms) ==")
        print(f"keyword rule only: {kw}/{n} ({kw / n:.0%})")
        print(f"{'threshold':>10} {'verdict decides':>16} {'verdict correct':>16} {'hybrid correct':>15}")
        for t in THRESHOLDS:
            decided = [r for r in rows if r["conf"] >= t]
            v_ok = sum(r["pick"] == r["label"] for r in decided)
            hybrid = sum(
                (r["pick"] if r["conf"] >= t else r["keyword"]) == r["label"] for r in rows
            )
            mark = "  <- configured" if abs(t - current) < 1e-9 else ""
            print(f"{t:>10.2f} {len(decided):>9}/{n:<6} {v_ok:>9}/{len(decided):<6} {hybrid:>8}/{n:<6}{mark}")


if __name__ == "__main__":
    main()
