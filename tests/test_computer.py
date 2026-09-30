import json

import pytest

from aegis.system2 import computer
from aegis.system2.computer import (
    ALLOWED_COMMANDS,
    is_denied_path,
    list_dir,
    parse_tool_call,
    read_file,
    run_command,
    run_tool,
)


# --- Sandbox: commands -------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "rm -rf ~",
    "curl https://example.com",
    "ls | wc -l",
    "ls; whoami",
    "ls && whoami",
    "cat ~/notes.txt > out.txt",
    "echo $(whoami)",
    "echo `whoami`",
    "find ~ -name x -delete",
    "find ~ -name x -exec cat {} ;",
    "grep -r password ~",
    "grep -Rn token ~/Documents",
    "git -c core.pager=sh log",
    "git push",
    "git config user.name hacked",
    "python3 -c 'print(1)'",
    "node -e 1",
    "sysctl -w kern.maxfiles=1",
    "date 010100002030",
    "hostname evil",
])
def test_unsafe_commands_are_denied(cmd):
    result = run_command(cmd)
    assert not result.ok
    assert result.error.startswith("denied")


@pytest.mark.parametrize("cmd", [
    "cat ~/.ssh/id_rsa",
    "head ~/.aws/credentials",
    "cat .netrc",
    "cat ~/Documents/../.ssh/config",
    "cat ~/project/.env",
    "cat ~/.zsh_history",
    "ls ~/Library/Keychains",
    "cat server.pem",
])
def test_secret_paths_are_denied(cmd):
    result = run_command(cmd)
    assert not result.ok
    assert "off limits" in result.error


def test_safe_commands_run():
    result = run_command("whoami")
    assert result.ok
    assert result.output.strip()


def test_every_allowed_program_has_a_known_name():
    assert "whoami" in ALLOWED_COMMANDS and "rm" not in ALLOWED_COMMANDS


# --- Sandbox: files ----------------------------------------------------------

def test_read_file_and_list_dir_respect_deny_list(tmp_path, monkeypatch):
    monkeypatch.setattr(computer, "HOME", tmp_path)
    (tmp_path / "notes.txt").write_text("my name is Ada")
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_ed25519").write_text("PRIVATE")

    assert read_file(str(tmp_path / "notes.txt")).output == "my name is Ada"
    assert not read_file(str(tmp_path / ".ssh" / "id_ed25519")).ok
    assert not list_dir(str(tmp_path / ".ssh")).ok
    listing = list_dir(str(tmp_path))
    assert listing.ok and "notes.txt" in listing.output


def test_binary_files_are_not_dumped(tmp_path):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\x00\x01\x02" * 10)
    assert "binary" in read_file(str(f)).error


def test_env_files_are_denied_anywhere():
    assert is_denied_path("/tmp/app/.env")
    assert is_denied_path("/tmp/app/.env.local")
    assert is_denied_path("/tmp/app/readme.md") is None


# --- Parsing ------------------------------------------------------------------

def test_parse_tool_call_forms():
    assert parse_tool_call('<tool>{"name": "run_command", "args": {"command": "whoami"}}</tool>')["name"] == "run_command"
    # closing tag missing and made-up results after it
    assert parse_tool_call('<tool>{"name": "list_dir", "args": {"path": "~"}}\n```json\n{"fake": 1}\n```')["args"] == {"path": "~"}
    assert parse_tool_call('```json\n{"name": "read_file", "args": {"path": "~/a.txt"}}\n```')["name"] == "read_file"
    assert parse_tool_call('<think>maybe <tool>{"name": "x"}</tool></think>Your name is Ada.') is None
    assert parse_tool_call("Your name is Ada.") is None
    assert parse_tool_call('<tool>{"name": "run_command", "args": {"comm') is None  # still streaming


def test_unknown_tool_gets_a_corrective_hint():
    result = run_tool({"name": "mdfind", "args": {"query": "resume"}})
    assert not result.ok
    assert "run_command" in result.error


# --- Server loop --------------------------------------------------------------

class ScriptedGenerator:
    """Replies with a tool call first, then answers using the tool result."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def chat_stream(self, messages):
        self.seen.append(messages)
        reply = self.replies.pop(0)
        for i in range(0, len(reply), 7):
            yield {"thinking": "", "response": reply[i:i + 7], "done": False}


def _events(stream):
    return [json.loads(e[len("data: "):]) for e in stream]


def test_free_stream_runs_tools_for_local_requests(monkeypatch):
    import aegis.ui.server as srv

    gen = ScriptedGenerator([
        '<tool>{"name": "run_command", "args": {"command": "whoami"}}</tool>\nFAKE RESULT',
        "You are logged in as the current user.",
    ])
    monkeypatch.setattr(srv, "generator", gen)
    events = _events(srv._free_stream("r1", "what is my name?", [], computer=True, local=True))

    tools = [e for e in events if e["type"] == "tool"]
    assert [t["status"] for t in tools] == ["running", "done"]
    assert tools[1]["ok"] and tools[1]["args"] == {"command": "whoami"}
    final = events[-1]
    assert final["computer"]["status"] == "on"
    assert final["aegis"]["text"] == "You are logged in as the current user."
    # The model saw machine facts and then the real tool result, not its own invention
    assert "COMPUTER ACCESS IS ON" in gen.seen[0][0]["content"]
    assert "TOOL RESULT" in gen.seen[1][-1]["content"]
    assert "FAKE RESULT" not in gen.seen[1][-2]["content"]


def test_free_stream_refuses_computer_access_for_remote_requests(monkeypatch):
    import aegis.ui.server as srv

    gen = ScriptedGenerator(['<tool>{"name": "run_command", "args": {"command": "whoami"}}</tool>'])
    monkeypatch.setattr(srv, "generator", gen)
    events = _events(srv._free_stream("r2", "what is my name?", [], computer=True, local=False))

    assert not [e for e in events if e["type"] == "tool"]
    assert events[-1]["computer"]["status"] == "remote"
    assert "COMPUTER ACCESS" not in gen.seen[0][0]["content"]


def test_free_stream_respects_config_switch(monkeypatch):
    import aegis.ui.server as srv

    gen = ScriptedGenerator(["I can't check that."])
    monkeypatch.setattr(srv, "generator", gen)
    monkeypatch.setattr(srv.config_manager.config, "allow_computer_access", False)
    events = _events(srv._free_stream("r3", "what is my name?", [], computer=True, local=True))
    assert events[-1]["computer"]["status"] == "disabled"
