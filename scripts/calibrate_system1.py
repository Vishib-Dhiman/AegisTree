"""Measure System 1 against its non-model fallbacks.

Default: task routing. Runs scripts/data/system1_eval.json through Verdict and
reports keyword-rule accuracy, Verdict accuracy/coverage per threshold, and the
hybrid the router uses.

--retrieval: policy retrieval and revival blocking. Runs
scripts/data/retrieval_eval.json (all four workspaces) and reports overlap-only
retrieval vs the Verdict hybrid per threshold, plus revival catches and false
blocks per assist threshold.

Usage:
  .venv/bin/python scripts/calibrate_system1.py [--workspace demo_vault]
  .venv/bin/python scripts/calibrate_system1.py --retrieval
"""

from __future__ import annotations
import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aegis.core.config import config_manager
from aegis.core.ingestion import WorkspaceIngestor
from aegis.core.models import ChoiceQuery, NodeType
from aegis.system1.graph import MemoryGraph
from aegis.system1.policy_guard import find_forbidden, revival_probability
from aegis.system1.retrieval import Resolution, apply_tie_break, resolve, retrieve, tie_break
from aegis.system1.router import (
    TASK_OPTIONS,
    apply_keyword_rule,
    best_option,
    build_context,
    relative_confidence,
)
from aegis.system1.verdict_engine import VerdictDecisionEngine

THRESHOLDS = [0.4, 0.45, 0.5, 0.55, 0.6, 0.7]
DATA = ROOT / "scripts" / "data"


def mark(t: float, current: float) -> str:
    return "  <- configured" if abs(t - current) < 1e-9 else ""


def report_tasks(engine: VerdictDecisionEngine, workspace: str) -> None:
    data = json.loads((DATA / "system1_eval.json").read_text())
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
            res = engine.evaluate_choice(build_context(item["prompt"], workspace), query)
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
        print(f"\n== tasks / {split} ({n} prompts, median Verdict latency {lat:.1f} ms) ==")
        print(f"keyword rule only: {kw}/{n} ({kw / n:.0%})")
        print(f"{'threshold':>10} {'verdict decides':>16} {'verdict correct':>16} {'hybrid correct':>15}")
        for t in THRESHOLDS:
            decided = [r for r in rows if r["conf"] >= t]
            v_ok = sum(r["pick"] == r["label"] for r in decided)
            hybrid = sum(
                (r["pick"] if r["conf"] >= t else r["keyword"]) == r["label"] for r in rows
            )
            print(f"{t:>10.2f} {len(decided):>9}/{n:<6} {v_ok:>9}/{len(decided):<6} {hybrid:>8}/{n:<6}{mark(t, current)}")


def load_graph(workspace: str, tmp: Path) -> MemoryGraph:
    graph = MemoryGraph(storage_dir=tmp / workspace.replace("/", "_"))
    graph.replace_corpus(*WorkspaceIngestor.ingest_adrs(ROOT / workspace))
    return graph


def collect_retrieval(engine: VerdictDecisionEngine, items: list, graphs: dict) -> list:
    """Run the model once per prompt; thresholds are swept afterwards."""
    rows = []
    for item in items:
        ws = item["workspace"]
        graph = graphs[ws]
        decisions = [n for n in graph.all_nodes() if n.type == NodeType.ARCHITECTURE_DECISION]
        active = [n for n in decisions if n.is_active()]
        superseded = [n for n in decisions if not n.is_active()]
        r = retrieve(engine, item["prompt"], ROOT / ws, active, superseded)
        revival = {
            n.id: revival_probability(engine, item["prompt"], ROOT / ws, n)[0] for n in superseded
        }
        # Tie-break among overlapping decisions, computed once (thresholds are swept later)
        overlap_nodes = [n for _, n in r.overlap]
        tie = tie_break(engine, item["prompt"], ROOT / ws, overlap_nodes) if len(overlap_nodes) > 1 else None
        rows.append({**item, "retrieval": r, "revival": revival, "graph": graph, "tie": tie})
    return rows


def evaluate_row(row: dict, retrieval_t: float, assist_t: float, revival_t: float) -> dict:
    """Same decision path as Router.route for an implement_production request."""
    graph = row["graph"]
    task_t = config_manager.config.system1_confidence_threshold
    res = resolve(row["retrieval"], graph, retrieval_t)
    if res.source == "overlap" and len(res.policies) > 1:
        res = apply_tie_break(res, row["tie"], task_t)
    primary = res.primary.id if res.primary else "none"
    # Router before Verdict retrieval: overlap, Verdict tie-break when several overlap
    overlap_nodes = [n for _, n in row["retrieval"].overlap]
    old = Resolution(overlap_nodes, overlap_nodes[0] if overlap_nodes else None, "overlap")
    if len(overlap_nodes) > 1:
        old = apply_tie_break(old, row["tie"], task_t)
    overlap_primary = old.primary.id if old.primary else "none"

    negatives, seen = [], set()
    for pol in res.policies:
        for succ in graph.successors(pol.id, relation="supersedes"):
            if succ.id not in seen:
                seen.add(succ.id)
                negatives.append(succ)
    if res.revival_candidate and res.revival_candidate.id not in seen:
        negatives.append(res.revival_candidate)

    banned = [lit for n in res.policies + negatives for lit in n.forbidden_literals]
    blocked = bool(res.policies) and bool(find_forbidden(row["prompt"], banned))
    if not blocked and res.revival_candidate:
        blocked = row["revival"][res.revival_candidate.id] >= assist_t
    if not blocked and negatives:
        blocked = max(row["revival"][n.id] for n in negatives[:3]) >= revival_t
    return {"primary": primary, "overlap_primary": overlap_primary, "blocked": blocked}


def report_retrieval(engine: VerdictDecisionEngine) -> None:
    data = json.loads((DATA / "retrieval_eval.json").read_text())
    cfg = config_manager.config
    workspaces = {item["workspace"] for split in ("dev", "test") for item in data[split]}

    with tempfile.TemporaryDirectory() as tmp:
        graphs = {ws: load_graph(ws, Path(tmp)) for ws in sorted(workspaces)}
        for split in ("dev", "test"):
            rows = collect_retrieval(engine, data[split], graphs)
            n = len(rows)
            lat = sorted(r["retrieval"].latency_ms or 0 for r in rows)[n // 2]
            base = [evaluate_row(r, 1.01, 1.01, cfg.system1_revival_threshold) for r in rows]
            ov = sum(b["overlap_primary"] == r["expected"] for b, r in zip(base, rows))
            print(f"\n== retrieval / {split} ({n} prompts, 4 workspaces, median Verdict latency {lat:.1f} ms) ==")
            print(f"previous router (overlap + tie-break): {ov}/{n} ({ov / n:.0%}) correct decision or abstention")
            print(f"{'threshold':>10} {'hybrid correct':>15} {'abstain ok':>11} {'wrong ADR':>10}")
            for t in THRESHOLDS:
                ev = [evaluate_row(r, t, 1.01, cfg.system1_revival_threshold) for r in rows]
                ok = sum(e["primary"] == r["expected"] for e, r in zip(ev, rows))
                nones = [(e, r) for e, r in zip(ev, rows) if r["expected"] == "none"]
                ab = sum(e["primary"] == "none" for e, _ in nones)
                wrong = sum(e["primary"] not in ("none", r["expected"]) for e, r in zip(ev, rows))
                print(f"{t:>10.2f} {ok:>8}/{n:<6} {ab:>6}/{len(nones):<4} {wrong:>10}{mark(t, cfg.system1_retrieval_threshold)}")

            revives = [r for r in rows if r["revives"]]
            compliant = [r for r in rows if not r["revives"]]
            print(f"\nrevival blocking at retrieval threshold {cfg.system1_retrieval_threshold:.2f} "
                  f"({len(revives)} revival prompts, {len(compliant)} compliant):")
            print(f"{'assist t':>10} {'caught':>8} {'false blocks':>13}")
            for at in [1.01, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7]:
                ev = [evaluate_row(r, cfg.system1_retrieval_threshold, at, cfg.system1_revival_threshold) for r in rows]
                caught = sum(e["blocked"] for e, r in zip(ev, rows) if r["revives"])
                false = sum(e["blocked"] for e, r in zip(ev, rows) if not r["revives"])
                label = "off" if at > 1 else f"{at:.2f}"
                print(f"{label:>10} {caught:>4}/{len(revives):<3} {false:>8}/{len(compliant):<4}{mark(at, cfg.system1_revival_assist_threshold)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default="demo_vault")
    parser.add_argument("--retrieval", action="store_true")
    args = parser.parse_args()

    engine = VerdictDecisionEngine()
    if args.retrieval:
        report_retrieval(engine)
    else:
        report_tasks(engine, args.workspace)


if __name__ == "__main__":
    main()
