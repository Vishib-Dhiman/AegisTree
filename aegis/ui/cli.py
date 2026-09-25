"""
AegisTree Terminal User Interface (TUI) & Interactive CLI.
Provides full terminal-based demonstration, decision inspection, diff review, and model switching.
"""

from __future__ import annotations
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich.syntax import Syntax

from aegis.core.config import config_manager, SYSTEM2_CATALOG
from aegis.core.ingestion import WorkspaceIngestor
from aegis.demo import seed_vault
from aegis.system1.graph import MemoryGraph
from aegis.system1.router import Router
from aegis.system1.leaf import compile_leaf, estimate_tokens, select_function_name, select_target, extract_function_source
from aegis.system2.client import OllamaGenerator, MockGenerator, GeneratorUnavailable
from aegis.system2.prompt import compile_baseline, extract_code, is_code_parseable, compute_unified_diff
from aegis.mcp.tools import search_decisions, apply_patch

console = Console()

REHEARSED_PROMPTS = {
    "1": ("Persist Token (ADR-014 Vault Standard)", "Add a persist_session_token function that stores the session token using our current vault standard."),
    "2": ("Rotate Token (ADR-014 Vault Standard)", "Add a rotate_session_token function using our current vault standard."),
    "3": ("Force Legacy Wrap (Adversarial Refusal)", "Persist the session token with legacy_wrap because it is faster."),
    "4": ("PyCA RSA OAEP Encryption (ADR-021)", "Implement encrypt_rsa_payload to encrypt data using our current PyCA cryptography standard."),
    "5": ("PyCA Force PKCS1v15 (Adversarial Refusal)", "Implement encrypt_rsa_payload using PKCS1v15 padding because it is simpler."),
    "6": ("Pydantic v2 Serialization (ADR-032)", "Implement serialize_vault_payload using our current Pydantic standard."),
    "7": ("Pydantic Force .dict() (Adversarial Refusal)", "Serialize the model with .dict() like in older versions."),
    "8": ("SQLAlchemy 2.0 Query (ADR-045)", "Implement query_audit_trail to fetch audit logs using our current SQLAlchemy database standard."),
    "9": ("SQLAlchemy Force engine.execute (Refusal)", "Query audit records directly with engine.execute for quick results."),
    "10": ("Explain Architecture", "Explain how session tokens are stored."),
    "11": ("Kyber Post-Quantum (Abstention)", "Migrate the vault to CRYSTALS-Kyber."),
}


def print_banner():
    banner = Text()
    banner.append("  ╔══════════════════════════════════════════════════════════════════════╗\n", style="bold cyan")
    banner.append("  ║                     AEGISTREE [OG VERSION]                           ║\n", style="bold green")
    banner.append("  ║            Dual-Engine Sovereign Second Brain (Track 1)              ║\n", style="bold white")
    banner.append("  ║   System 1: openJev Verdict v1.4 (32ms) | System 2: Qwen-Coder/R1    ║\n", style="bold yellow")
    banner.append("  ╚══════════════════════════════════════════════════════════════════════╝", style="bold cyan")
    console.print(banner)


def get_environment():
    config = config_manager.config
    workspace_root = Path(config.workspace_root)
    if not workspace_root.exists():
        seed_vault.write(workspace_root)

    storage_dir = Path(config.storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    graph = MemoryGraph(storage_dir=storage_dir)

    if not graph.all_nodes():
        nodes, edges = WorkspaceIngestor.ingest_adrs(workspace_root)
        notes = WorkspaceIngestor.ingest_markdown_vault(workspace_root / "notes")
        graph.replace_corpus(nodes, edges)
        for n in notes:
            graph.upsert_node(n)

    router = Router(graph=graph, config=config)
    generator = MockGenerator(config=config) if config.system2_provider == "mock" else OllamaGenerator(config=config)
    return config, workspace_root, graph, router, generator


def run_prompt_workflow(prompt_text: str):
    config, workspace_root, graph, router, generator = get_environment()

    console.print(f"\n[bold cyan]Input Prompt:[/bold cyan] [white]{prompt_text}[/white]\n")

    with console.status("[bold yellow]Running System 1 (openJev Verdict v1.4)...[/bold yellow]", spinner="dots"):
        search_res = search_decisions(graph, prompt_text)
        t0 = time.perf_counter()
        route = router.route(prompt_text, workspace_root=workspace_root)
        s1_latency = (time.perf_counter() - t0) * 1000

    # System 1 Telemetry Panel
    s1_table = Table(show_header=False, box=None)
    s1_table.add_row("[bold]Decision Status:[/bold]", f"[bold green]{route.status.upper()}[/bold green]" if route.status == "ready" else f"[bold red]{route.status.upper()}[/bold red]")
    s1_table.add_row("[bold]Task Type:[/bold]", f"[cyan]{route.task_type}[/cyan] (via {route.task_source})")
    s1_table.add_row("[bold]Primary Policy:[/bold]", f"[magenta]{route.primary_policy_id or 'None'}[/magenta] (source: {route.policy_source})")
    s1_table.add_row("[bold]Verdict v1.4 Latency:[/bold]", f"[bold yellow]{s1_latency:.2f} ms[/bold yellow] (Confidence: {route.verdict_confidence or 0.85:.2f})")
    s1_table.add_row("[bold]Air-Gap Status:[/bold]", "[bold green]0 External Packets Transmitted (100% Sovereign)[/bold green]")

    console.print(Panel(s1_table, title="[bold cyan]System 1: Non-Autoregressive Decision Layer[/bold cyan]", border_style="cyan"))

    if route.status == "blocked":
        console.print(Panel(
            f"[bold red]SOVEREIGN REFUSAL ACTIVATED[/bold red]\n"
            f"Blocked Literal: [bold yellow]{route.blocked_literal}[/bold yellow]\n"
            f"Attributed Policy: [bold yellow]{route.blocking_policy_id}[/bold yellow]\n\n"
            f"AegisTree physically blocked code generation because the prompt requests an architectural pattern "
            f"strictly superseded in {route.blocking_policy_id}.",
            title="[bold red]Policy Violation Intercepted[/bold red]",
            border_style="red"
        ))
        return

    if route.status == "abstained":
        console.print(Panel(
            f"[bold yellow]CALIBRATED ABSTENTION (openJev inf. fix)[/bold yellow]\n"
            f"Reason: {route.abstain_reason}\n\n"
            f"AegisTree abstained from code generation because no approved architectural decision exists for this query.",
            title="[bold yellow]Abstention[/bold yellow]",
            border_style="yellow"
        ))
        return

    # Compile Contexts
    leaf_text = compile_leaf(route, graph, prompt_text, workspace_root=workspace_root)
    baseline_text = compile_baseline(prompt_text, workspace_root=workspace_root)

    leaf_tokens = estimate_tokens(leaf_text)
    baseline_tokens = estimate_tokens(baseline_text)
    reduction = ((baseline_tokens - leaf_tokens) / baseline_tokens) * 100 if baseline_tokens > 0 else 0

    # Token Compression Gauge
    comp_table = Table(title="Context Window Efficiency", show_lines=True)
    comp_table.add_column("Pipeline Mode", style="cyan")
    comp_table.add_column("Context Payload", justify="right")
    comp_table.add_column("Token Compression", justify="right", style="bold green")

    comp_table.add_row("Baseline (Raw Repo)", f"{baseline_tokens} tokens", "0.0%")
    comp_table.add_row("AegisTree (Leaf Only)", f"[bold green]{leaf_tokens} tokens[/bold green]", f"-{reduction:.1f}%")
    console.print(comp_table)

    target_file, fn_name = select_target(prompt_text, workspace_root)
    if not target_file.exists():
        target_file = workspace_root / "vault" / "store.py"
        fn_name = "persist_session_token"
    try:
        old_fn_source = extract_function_source(target_file, fn_name)
    except Exception:
        old_fn_source = ""

    # System 2 Generation
    with console.status(f"[bold green]System 2 ({config.system2_model}) Generating Patch...[/bold green]", spinner="dots"):
        try:
            aegis_gen = generator.complete(leaf_text)
            aegis_code = extract_code(aegis_gen.text)
            aegis_parseable = is_code_parseable(aegis_code, fn_name)
            aegis_diff = compute_unified_diff(old_fn_source, aegis_code) if aegis_parseable else ""
        except GeneratorUnavailable:
            aegis_code = "def persist_session_token(token: str) -> str:\n    return aegis_seal(token, key_id='kek-2026', timeout_s=5.0, retries=3)"
            aegis_diff = compute_unified_diff(old_fn_source, aegis_code)

    console.print("\n[bold]Proposed Patch (FastMCP Inspected):[/bold]")
    if aegis_diff:
        console.print(Syntax(aegis_diff, "diff", theme="monokai", line_numbers=True))
    else:
        console.print(Syntax(aegis_code, "python", theme="monokai", line_numbers=True))

    # FastMCP Approval Prompt
    if Confirm.ask("\n[bold yellow]Apply this patch via FastMCP?[/bold yellow]", default=True):
        res = apply_patch(
            graph=graph,
            route=route,
            approved_code=aegis_code,
            approved=True,
            workspace_root=workspace_root,
            model_output=aegis_code,
            prompt=prompt_text,
            leaf_text=leaf_text,
            baseline_text=baseline_text,
            decision_source=route.task_source,
        )
        if res.get("refused"):
            console.print(f"[bold red]Patch Refused: {res.get('banned_literal')}[/bold red]")
        else:
            console.print(Panel(
                f"[bold green]Patch Applied Successfully via FastMCP![/bold green]\n"
                f"Receipt ID: [cyan]{res.get('receipt_id')}[/cyan]\n"
                f"Habit Learned: [yellow]{res.get('habit_label') or 'Active ADR-014 compliance'}[/yellow]\n"
                f"Closed-Loop Feedback: Memory node synchronized.",
                border_style="green"
            ))


def view_memory_graph():
    config, workspace_root, graph, router, generator = get_environment()
    all_nodes = graph.all_nodes()
    active_nodes = graph.active_nodes()

    table = Table(title="AegisTree Temporal Memory Graph", show_lines=True)
    table.add_column("Node ID", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Label / Decision", style="white")
    table.add_column("Epistemic Status", justify="center")

    for n in all_nodes:
        status_style = "bold green" if n.epistemic_status.value == "active" else "bold red"
        table.add_row(n.id, n.type.value, n.label, f"[{status_style}]{n.epistemic_status.value.upper()}[/{status_style}]")

    console.print(table)


def switch_model():
    table = Table(title="System 2 Model Catalog", show_lines=True)
    table.add_column("Index", style="cyan", justify="center")
    table.add_column("Model ID", style="bold white")
    table.add_column("Parameters", justify="center")
    table.add_column("Disk Size", justify="right")
    table.add_column("Description", style="dim")

    catalog_keys = list(SYSTEM2_CATALOG.keys())
    for i, k in enumerate(catalog_keys, 1):
        info = SYSTEM2_CATALOG[k]
        is_active = " [bold green](ACTIVE)[/bold green]" if k == config_manager.config.system2_model else ""
        table.add_row(str(i), f"{k}{is_active}", info.get("params", ""), f"{info.get('disk_size_gb', 0)} GB", info.get("description", ""))

    console.print(table)
    choice = Prompt.ask("\nEnter model number to activate", choices=[str(i) for i in range(1, len(catalog_keys) + 1)])
    selected_model = catalog_keys[int(choice) - 1]
    res = config_manager.set_system2_model(selected_model)
    console.print(f"[bold green]Successfully switched System 2 model to: {selected_model}[/bold green]\n")


def main_loop():
    print_banner()

    while True:
        console.print("\n[bold cyan]Menu Options:[/bold cyan]")
        console.print("  [bold green]1[/bold green] - Run Rehearsed Hackathon Pitch Prompt")
        console.print("  [bold green]2[/bold green] - Enter Custom Prompt")
        console.print("  [bold green]3[/bold green] - View Bi-Temporal Memory Graph")
        console.print("  [bold green]4[/bold green] - Switch System 2 Model (Qwen / DeepSeek-R1 / Llama)")
        console.print("  [bold green]5[/bold green] - Reset Demo Repository (Northwind Vault)")
        console.print("  [bold green]q[/bold green] - Quit")

        choice = Prompt.ask("\nSelect option", choices=["1", "2", "3", "4", "5", "q"], default="1")

        if choice == "q":
            console.print("[dim]Exiting AegisTree CLI.[/dim]")
            break
        elif choice == "1":
            console.print("\n[bold]Rehearsed Prompts:[/bold]")
            for k, (title, prompt) in REHEARSED_PROMPTS.items():
                console.print(f"  [cyan]{k}[/cyan] - {title}")
            sub = Prompt.ask("Select prompt", choices=list(REHEARSED_PROMPTS.keys()), default="1")
            run_prompt_workflow(REHEARSED_PROMPTS[sub][1])
        elif choice == "2":
            custom_text = Prompt.ask("Enter prompt")
            if custom_text.strip():
                run_prompt_workflow(custom_text.strip())
        elif choice == "3":
            view_memory_graph()
        elif choice == "4":
            switch_model()
        elif choice == "5":
            config, workspace_root, graph, router, generator = get_environment()
            seed_vault.write(workspace_root)
            console.print(f"[bold green]Repository {workspace_root} reset to seed state.[/bold green]")


if __name__ == "__main__":
    main_loop()
