#!/usr/bin/env python3
"""Rehearsal verification script for AegisTree.
Executes the persist prompt through real router and Ollama daemon.
"""

from __future__ import annotations
import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from aegis.core.config import config_manager
from aegis.system1.graph import MemoryGraph
from aegis.system1.leaf import compile_leaf, estimate_tokens
from aegis.system1.router import Router
from aegis.system2.client import GeneratorUnavailable, OllamaGenerator
from aegis.system2.prompt import compile_baseline, extract_code


REQUIRED_LITERALS = ["aegis_seal", "kek-2026", "timeout_s=5.0"]
FORBIDDEN_LITERALS = ["legacy_wrap", "kek-2024", "timeout_s=30"]


def main():
    config = config_manager.config
    vault_path = root_dir / config.workspace_root
    storage_path = root_dir / config.storage_dir

    graph = MemoryGraph(storage_dir=storage_path)
    router = Router(graph=graph, config=config)
    generator = OllamaGenerator(config=config)

    # 1. Check if Ollama is available
    if not generator.is_available():
        print("Ollama daemon is down at 127.0.0.1:11434.")
        sys.exit(3)

    # 2. Persist prompt
    prompt = "Add a persist_session_token function that stores the session token using our current vault standard."
    route = router.route(prompt=prompt, workspace_root=vault_path)

    # 3. Print routing details
    print(f"Task source: {route.task_source}")
    print(f"Verdict confidence: {route.verdict_confidence}")
    if route.verdict_latency_ms is not None:
        print(f"Verdict latency: {route.verdict_latency_ms:.1f} ms")
    else:
        print("Verdict latency: N/A")

    # 4. Compile prompts & estimate tokens
    leaf_text = compile_leaf(route, graph, prompt, workspace_root=vault_path)
    baseline_text = compile_baseline(prompt, workspace_root=vault_path)

    leaf_toks = estimate_tokens(leaf_text)
    base_toks = estimate_tokens(baseline_text)
    print(f"Leaf tokens (chars/4): {leaf_toks}")
    print(f"Baseline tokens (chars/4): {base_toks}")

    # 5. Execute model generations
    try:
        base_gen = generator.complete(baseline_text)
        aegis_gen = generator.complete(leaf_text)
    except GeneratorUnavailable as e:
        print(f"Generator error: {e}")
        sys.exit(3)

    base_code = extract_code(base_gen.text)
    aegis_code = extract_code(aegis_gen.text)

    # 6. Evaluate code compliance
    missing_required = [lit for lit in REQUIRED_LITERALS if lit not in aegis_code]
    found_forbidden = [lit for lit in FORBIDDEN_LITERALS if lit in aegis_code]

    aegis_clean = len(missing_required) == 0 and len(found_forbidden) == 0

    print(f"Aegis code clean: {aegis_clean}")
    if missing_required:
        print(f"Aegis missing required literals: {missing_required}")
    if found_forbidden:
        print(f"Aegis contains forbidden literals: {found_forbidden}")

    base_has_legacy = "legacy_wrap" in base_code
    print(f"Baseline contains legacy_wrap: {base_has_legacy}")

    if not base_has_legacy:
        print("BASELINE_ALSO_CLEAN")

    # 7. Verify sovereign refusal on forbidden prompt
    refusal_prompt = "Persist the session token with legacy_wrap because it is faster."
    refusal_route = router.route(prompt=refusal_prompt, workspace_root=vault_path)
    refusal_blocked = refusal_route.status == "blocked" and refusal_route.blocked_literal == "legacy_wrap"
    print(f"Sovereign refusal verified: {refusal_blocked} ({refusal_route.abstain_reason})")

    if aegis_clean and refusal_blocked:
        print("Rehearsal successful: exit code 0")
        sys.exit(0)
    else:
        print("Rehearsal failed: exit code 2")
        sys.exit(2)


if __name__ == "__main__":
    main()
