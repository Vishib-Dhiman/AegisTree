"""
Decision engine benchmark: openJev Verdict (151M) vs Laya (ModernBERT-large).

Both engines run locally on the 9 subtle-divergence tests below; every pass,
fail and latency printed here is measured in this run. No other engines are
compared: nothing else is run by this script.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
verdict_repo_path = ROOT / "Verdict-open-jev"
if str(verdict_repo_path) not in sys.path:
    sys.path.insert(0, str(verdict_repo_path))

import laya
import psutil
from rlcd import DecisionEngine as VerdictEngine, Choice as VChoice, Option as VOption
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

TEST_CASES = [
    {
        "id": "T1",
        "name": "Noul Bias",
        "desc": "Detect all choices are deprecated/invalid (Abstention)",
        "prompt": "The codebase has completely migrated to gRPC. REST, SOAP, and XML-RPC are strictly forbidden and deprecated.",
        "candidates": ["rest_client", "soap_client", "xmlrpc_client"],
        "expected": "__insufficient_evidence__",
    },
    {
        "id": "T2",
        "name": "Multi-Hop",
        "desc": "Chained constraint across 3 relational hops",
        "prompt": "Service A calls Service B. Service B migrated to Kafka streaming in Sprint 12 and dropped HTTP endpoints. Service A must trigger an audit log update in Service B.",
        "candidates": ["kafka_event", "direct_http", "shared_sql"],
        "expected": "kafka_event",
    },
    {
        "id": "T3",
        "name": "Distractor",
        "desc": "Adversarial legacy keyword in prompt",
        "prompt": "Developer Prompt: 'We used to rely on basic_auth and requests before the outage. Basic authentication was convenient. Write a telemetry client.' Active Rule: mTLS with httpx required. Basic auth is deprecated.",
        "candidates": ["mtls_httpx", "basic_auth_requests", "token_bearer"],
        "expected": "mtls_httpx",
    },
    {
        "id": "T4",
        "name": "AST Scope",
        "desc": "Test fixture vs production violation",
        "prompt": "File: tests/mocks/test_legacy.py. Snippet: with pytest.deprecated_call(): import requests. Is this an illegal production violation?",
        "candidates": ["compliant_test_mock", "illegal_prod_violation"],
        "expected": "compliant_test_mock",
    },
    {
        "id": "T5",
        "name": "Polysemy",
        "desc": "Disambiguate 'wipe the cache'",
        "prompt": "Active File: src/storage/redis_pool.py. Commit: Fix memory leak in cluster eviction. User command: 'Wipe the cache now'.",
        "candidates": ["redis_flush", "disk_lru_purge", "build_cache_clean"],
        "expected": "redis_flush",
    },
    {
        "id": "T6",
        "name": "Calibration",
        "desc": "Calibrate high security risk score (1-5)",
        "prompt": "Diff modifies core AES-256-GCM cipher to custom XOR cipher in auth/token.py.",
        "candidates": ["Level_1_Low", "Level_2_Minor", "Level_3_Moderate", "Level_4_High", "Level_5_Critical"],
        "expected": "Level_5_Critical",
    },
    {
        "id": "T7",
        "name": "Hierarchy",
        "desc": "Local Micro-ADR overrides Global Standard",
        "prompt": "Global Standard: All services log JSON to stdout. Micro-ADR-019: Service Gamma is an HFT engine; it MUST write binary flatbuffers to shared memory.",
        "candidates": ["binary_flatbuffers", "json_stdout", "text_syslog"],
        "expected": "binary_flatbuffers",
    },
    {
        "id": "T8",
        "name": "Sparse Diff",
        "desc": "Deduce fail-fast from 3-line syntax diff",
        "prompt": "Diff: - timeout = 30.0; - retry_count = 3; + timeout = 0.5; + retry_count = 0; + circuit_breaker = FastFail()",
        "candidates": ["fail_fast", "resilient_retry", "batch_worker"],
        "expected": "fail_fast",
    },
    {
        "id": "T9",
        "name": "Polyglot",
        "desc": "Enforce Rust Result<Option<T>, E> idiom",
        "prompt": "Language: Rust. Task: Function finds user by ID. Record may not exist in DB.",
        "candidates": ["result_option_user", "raw_ptr_user", "panic_on_missing"],
        "expected": "result_option_user",
    }
]


def external_connections() -> int:
    """Open non-loopback network connections held by this process right now."""
    conns = psutil.Process().net_connections(kind="inet")
    return sum(1 for c in conns if c.raddr and c.raddr.ip not in ("127.0.0.1", "::1"))


def run_verdict(engine, tc):
    options = [VOption(id=c, description=c.replace("_", " ")) for c in tc["candidates"]]
    t0 = time.perf_counter()
    res = engine.evaluate(context=tc["prompt"], queries=[VChoice(id=tc["id"], question=tc["desc"], options=options)]).results[0]
    lat = (time.perf_counter() - t0) * 1000
    if tc["expected"] == "__insufficient_evidence__":
        passed = res.is_abstention or res.selected_id == "__insufficient_evidence__"
    else:
        passed = res.selected_id == tc["expected"]
    return passed, lat, res.selected_id


def run_laya(agent, tc):
    t0 = time.perf_counter()
    if tc["expected"] == "__insufficient_evidence__":
        q = {
            "ch": {"type": "choice", "instructions": tc["desc"], "criteria": {c: c for c in tc["candidates"]}},
            "nl": {"type": "noul", "instructions": "Are all options invalid or deprecated?"},
        }
        res = agent.system_one(tc["prompt"], q)
        passed, picked = res["answers"]["nl"]["noul"] >= 0.80, "abstain?"
    else:
        q = {"ch": {"type": "choice", "instructions": tc["desc"], "criteria": {c: c for c in tc["candidates"]}}}
        res = agent.system_one(tc["prompt"], q)
        picked = res["answers"]["ch"]["choice"]
        passed = picked == tc["expected"]
    return passed, (time.perf_counter() - t0) * 1000, picked


def benchmark():
    console.print(Panel.fit(
        "[bold cyan]Decision engine benchmark[/bold cyan]\n"
        "[dim]openJev Verdict (151M) vs Laya (ModernBERT-large), 9 tests, all measured locally[/dim]"
    ))
    console.print("\n[yellow]Loading openJev Verdict...[/yellow]")
    verdict = VerdictEngine(model_name_or_path=str(verdict_repo_path / "artifacts/v2"), device="cpu")
    console.print("[yellow]Loading Laya...[/yellow]")
    agent = laya.Agent("convaiinnovations/laya", device="cpu")

    table = Table(title="Per-test results", show_lines=True)
    for col in ("Test", "Dimension", "Expected", "Verdict", "Laya"):
        table.add_column(col)
    totals = {"Verdict": [0, []], "Laya": [0, []]}

    for tc in TEST_CASES:
        v_pass, v_lat, v_pick = run_verdict(verdict, tc)
        l_pass, l_lat, l_pick = run_laya(agent, tc)
        for name, ok, lat in (("Verdict", v_pass, v_lat), ("Laya", l_pass, l_lat)):
            totals[name][0] += ok
            totals[name][1].append(lat)
        fmt = lambda ok, pick, lat: f"{'[green]PASS' if ok else '[red]FAIL'}[/] {pick} ({lat:.0f} ms)"
        table.add_row(tc["id"], tc["name"], tc["expected"], fmt(v_pass, v_pick, v_lat), fmt(l_pass, l_pick, l_lat))
    console.print(table)

    n = len(TEST_CASES)
    summary = Table(title="Summary", show_lines=True)
    for col in ("Engine", "Passed", "Median latency"):
        summary.add_column(col)
    for name, (passed, lats) in totals.items():
        summary.add_row(name, f"{passed}/{n}", f"{sorted(lats)[n // 2]:.0f} ms")
    console.print(summary)
    console.print(f"Open non-loopback network connections at end of run: {external_connections()}")


if __name__ == "__main__":
    benchmark()
