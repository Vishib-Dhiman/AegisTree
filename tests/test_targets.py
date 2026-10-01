from pathlib import Path

from aegis.core.models import ChoiceResult
from aegis.mcp.tools import apply_patch
from aegis.system1.graph import MemoryGraph
from aegis.system1.leaf import compile_leaf
from aegis.system1.router import RouteResult
from clearsky.targets import function_index, helper_signatures, new_function_name, resolve_target


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "shop"
    (root / "billing").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "billing" / "invoices.py").write_text(
        '"""Invoices."""\n\n\n'
        "def render_invoice(order):\n"
        '    """Turn an order into a printable invoice."""\n'
        "    return str(order)\n\n\n"
        "def total_with_tax(amount: float) -> float:\n"
        "    raise NotImplementedError\n"
    )
    (root / "billing" / "refunds.py").write_text(
        "def issue_refund(order, reason: str):\n"
        '    """Refund an order to its original payment method."""\n'
        "    ...\n"
    )
    (root / "tests" / "test_invoices.py").write_text("def test_total_with_tax():\n    pass\n")
    return root


def test_index_skips_tests_and_marks_stubs(tmp_path):
    index = {f.name: f for f in function_index(_project(tmp_path))}
    assert set(index) == {"render_invoice", "total_with_tax", "issue_refund"}
    assert index["total_with_tax"].stub and index["issue_refund"].stub and not index["render_invoice"].stub
    assert index["issue_refund"].doc.startswith("Refund an order")


def test_named_function_wins(tmp_path):
    root = _project(tmp_path)
    t = resolve_target("Implement total_with_tax with 18% GST.", root)
    assert (t.path, t.function, t.exists, t.source) == (root / "billing/invoices.py", "total_with_tax", True, "named")


def test_plain_words_match_by_overlap(tmp_path):
    root = _project(tmp_path)
    t = resolve_target("refund the order when the customer cancels", root)
    assert t.function == "issue_refund" and t.source == "overlap"


def test_unmatched_request_becomes_a_new_function(tmp_path):
    root = _project(tmp_path)
    t = resolve_target("Add a send reminder email function", root)
    assert t.function == "send_reminder_email" and not t.exists and t.source == "new"


def test_forbidden_names_are_never_targets(tmp_path):
    root = _project(tmp_path)
    t = resolve_target("Implement issue_refund", root, avoid={"issue_refund"})
    assert t.function == "issue_refund_new" and not t.exists


class PickNew:
    def evaluate_choice(self, context, query):
        ids = [o.id for o in query.options]
        probs = {i: 0.1 for i in ids}
        probs["__new_function__"] = 0.9
        return ChoiceResult(query_id=query.id, selected_id="__new_function__", confidence=0.9, probabilities=probs)


def test_verdict_breaks_close_ties(tmp_path):
    root = _project(tmp_path)
    # render_invoice and total_with_tax score within a point of each other, so Verdict decides
    t = resolve_target("render the invoice total", root, engine=PickNew())
    assert t.source == "verdict" and not t.exists


def test_new_function_names():
    assert new_function_name("Add a rotate session token function") == "rotate_session_token"
    assert new_function_name("add a function that parses the config file") == "parses_config_file"


def test_helpers_come_from_required_symbols(tmp_path):
    root = _project(tmp_path)
    assert helper_signatures(root, ["render_invoice", "kek-2026"]) == [
        "billing/invoices.py: def render_invoice(order):  # Turn an order into a printable invoice."
        "\n  every call must pass: order"
    ]


def test_leaf_outside_the_vault_has_no_vault_assumptions(tmp_path):
    root = _project(tmp_path)
    graph = MemoryGraph(storage_dir=tmp_path / ".aegis")
    route = RouteResult(status="ready", task_type="implement_production", task_source="keyword")
    leaf = compile_leaf(route, graph, "Implement total_with_tax", workspace_root=root)
    assert "billing/invoices.py" in leaf and "raise NotImplementedError" in leaf
    assert "vault" not in leaf and "retries=3" not in leaf and "session" not in leaf


def test_apply_patch_appends_a_new_function(tmp_path):
    root = _project(tmp_path)
    graph = MemoryGraph(storage_dir=tmp_path / ".aegis")
    route = RouteResult(
        status="ready", task_type="implement_production", task_source="keyword",
        target_file="billing/refunds.py", target_function="refund_reason_label", target_exists=False,
    )
    code = "def refund_reason_label(reason: str) -> str:\n    return reason.title()\n"
    result = apply_patch(graph, route, f"```python\n{code}```", True, workspace_root=root)
    assert result["applied"], result
    text = (root / "billing" / "refunds.py").read_text()
    assert "def issue_refund" in text and text.rstrip().endswith("return reason.title()")


def test_apply_patch_replaces_an_existing_function(tmp_path):
    root = _project(tmp_path)
    graph = MemoryGraph(storage_dir=tmp_path / ".aegis")
    route = RouteResult(
        status="ready", task_type="implement_production", task_source="keyword",
        target_file="billing/invoices.py", target_function="total_with_tax", target_exists=True,
    )
    code = "def total_with_tax(amount: float) -> float:\n    return round(amount * 1.18, 2)\n"
    assert apply_patch(graph, route, code, True, workspace_root=root)["applied"]
    text = (root / "billing" / "invoices.py").read_text()
    assert "NotImplementedError" not in text and text.count("def total_with_tax") == 1
    assert "def render_invoice" in text
