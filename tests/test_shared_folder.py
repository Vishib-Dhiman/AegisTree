import json
import threading
import time

import pytest

from clearsky.shared_folder import ClientToolBridge, client_rules, normalize_call, shared_folder_system_prompt


def test_answer_reaches_the_waiting_run():
    bridge = ClientToolBridge()
    bridge.open("run1", "t1", owner=7, call={"name": "read_file", "args": {"path": "README.md"}})
    threading.Timer(0.05, lambda: bridge.deliver("run1", "t1", 7, {"ok": True, "output": "# Hello"})).start()
    result = bridge.wait("run1", "t1", timeout_s=2)
    assert result.ok and result.output == "# Hello" and result.args == {"path": "README.md"}
    assert bridge.pending_count() == 0


def test_only_the_run_owner_can_answer():
    bridge = ClientToolBridge()
    bridge.open("run1", "t1", owner=7, call={"name": "list_dir", "args": {"path": ""}})
    assert bridge.deliver("run1", "t1", 8, {"ok": True, "output": "stolen"}) == "forbidden"
    assert bridge.deliver("run1", "t9", 7, {"ok": True}) == "unknown"
    assert bridge.wait("run1", "t1", timeout_s=0.05).ok is False  # nobody legitimate answered


def test_timeout_explains_what_happened():
    bridge = ClientToolBridge()
    bridge.open("run1", "t1", owner=1, call={"name": "list_dir", "args": {}})
    result = bridge.wait("run1", "t1", timeout_s=0.05)
    assert not result.ok and "browser didn't answer" in result.error
    assert bridge.deliver("run1", "t1", 1, {"ok": True}) == "unknown"  # too late


def test_unknown_tool_is_corrected_without_asking_the_browser():
    bridge = ClientToolBridge()
    bridge.open("run1", "t1", owner=1, call={"name": "run_command", "args": {"command": "ls"}})
    result = bridge.wait("run1", "t1", timeout_s=5)
    assert not result.ok and "list_dir, read_file, find_files, search_text" in result.error


def test_long_output_is_capped():
    bridge = ClientToolBridge()
    bridge.open("r", "t", owner=1, call={"name": "read_file", "args": {"path": "big.txt"}})
    bridge.deliver("r", "t", 1, {"ok": True, "output": "x" * 50_000})
    result = bridge.wait("r", "t", timeout_s=1)
    assert len(result.output) < 7000 and "truncated" in result.output


def test_prompt_and_rules():
    prompt = shared_folder_system_prompt('my "project"\n', 312)
    assert '"my "project""' in prompt and "312 files" in prompt and "cannot change files" in prompt
    rules = client_rules()
    assert any(".env" in p for p in rules["denied_name_patterns"])
    assert ".ssh" in rules["denied_dir_names"] and rules["limits"]["max_file_bytes"] == 12000


class ToolCallingModel:
    """First round asks to read a file; second round answers using the tool result."""

    def __init__(self):
        self.calls = []

    def chat_stream(self, messages):
        self.calls.append(messages)
        if len(self.calls) == 1:
            yield {"response": '<tool>{"name": "read_file", "args": {"path": "notes/todo.md"}}</tool>'}
        else:
            yield {"response": "Your TODO says: " + messages[-1]["content"].split("\n")[1]}


def test_folder_mode_asks_the_browser_and_never_touches_host_files(monkeypatch):
    import aegis.ui.server as srv

    model = ToolCallingModel()
    monkeypatch.setattr(srv, "_generator_for", lambda images: (model, "fake", False))
    monkeypatch.setattr(srv, "run_tool", lambda call: pytest.fail("host tools must not run in folder mode"))
    folder = srv.SharedFolderIn(name="my-project", files=12)
    events = []

    def browser():
        # Answer the client_tool call like the page does
        for _ in range(200):
            if srv.folder_bridge.pending_count():
                srv.folder_bridge.deliver("run-x", "t1", 5, {"ok": True, "output": "ship the demo"})
                return
            time.sleep(0.01)

    threading.Thread(target=browser, daemon=True).start()
    for chunk in srv._free_stream("run-x", "what's on my todo?", [], shared_folder=folder, owner=5):
        events.append(json.loads(chunk[len("data: "):]))

    init = events[0]
    assert init["computer"] == "folder" and init["shared_folder"] == "my-project"
    asked = [e for e in events if e["type"] == "client_tool"]
    assert asked == [{"type": "client_tool", "id": "t1", "name": "read_file", "args": {"path": "notes/todo.md"}}]
    final = events[-1]
    assert final["computer"]["status"] == "folder" and final["computer"]["tools"][0]["ok"]
    assert "ship the demo" in final["aegis"]["text"]
    assert 'SHARED FOLDER IS ON' in model.calls[0][0]["content"] or any(
        "SHARED FOLDER IS ON" in m["content"] for m in model.calls[0] if m["role"] == "system")


def test_non_streaming_requests_cannot_use_a_shared_folder(monkeypatch):
    import aegis.ui.server as srv

    model = ToolCallingModel()
    monkeypatch.setattr(srv, "_generator_for", lambda images: (model, "fake", False))
    folder = srv.SharedFolderIn(name="p", files=1)
    events = [json.loads(c[len("data: "):]) for c in srv._free_stream("r", "hi", [], shared_folder=folder, owner=1, streaming=False)]
    assert events[0]["computer"] == "folder-unavailable"
    assert not [e for e in events if e["type"] == "client_tool"]


@pytest.mark.parametrize("call, expected", [
    ({"name": "read_file", "args": {"path": "a.md"}}, {"path": "a.md"}),
    ({"name": "read_file", "arguments": {"path": "a.md"}}, {"path": "a.md"}),
    ({"name": "read_file", "parameters": {"path": "a.md"}}, {"path": "a.md"}),
    ({"name": "read_file", "path": "a.md"}, {"path": "a.md"}),
    ({"name": "read_file", "args": "a.md"}, {"path": "a.md"}),
    ({"name": "search_text", "args": "TODO"}, {"query": "TODO"}),
    ({"name": "list_dir"}, {}),
    ({"name": "list_dir", "args": ["x"]}, {}),
])
def test_tool_calls_are_normalized(call, expected):
    assert normalize_call(call) == {"name": call["name"], "args": expected}
