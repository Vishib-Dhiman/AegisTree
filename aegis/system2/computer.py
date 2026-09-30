"""Read-only computer access for No-workspace chat.

Lets the local model look things up on this machine (who the user is, what
files exist, what a file says) through three tools: run_command, read_file and
list_dir. Nothing here writes, deletes, or opens a network connection:

- commands run without a shell, from an allowlist, with per-command argument
  rules, a timeout and an output cap
- every path argument is checked against a deny list of secrets (SSH and cloud
  keys, keychains, browser profiles, mail, .env files, shell history)

The server additionally only enables these tools for requests that come from
this machine's own loopback address.
"""

from __future__ import annotations

import getpass
import json
import os
import platform
import re
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import pwd
except ImportError:  # Windows
    pwd = None

HOME = Path.home()
COMMAND_TIMEOUT_S = 8.0
MAX_OUTPUT_CHARS = 6000
MAX_FILE_BYTES = 12000
MAX_DIR_ENTRIES = 200
MAX_TOOL_ROUNDS = 5

# Directories (relative to home) whose contents are never read or listed
DENIED_DIRS = [
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".password-store",
    ".config/gcloud", ".config/gh", ".config/op",
    "Library/Keychains", "Library/Cookies", "Library/Safari", "Library/Messages",
    "Library/Mail", "Library/Accounts", "Library/Application Support/Google/Chrome",
    "Library/Application Support/Firefox", "Library/Application Support/BraveSoftware",
    "Library/Application Support/Microsoft Edge", "Library/Application Support/1Password",
    "Library/Application Support/com.apple.TCC",
]
# File names that usually hold credentials
DENIED_NAME_PATTERNS = [
    r"^\.netrc$", r"^\.git-credentials$", r"^\.pgpass$", r"^\.npmrc$", r"^\.pypirc$",
    r"^id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$", r".*\.(pem|key|p12|pfx|keychain|keychain-db)$",
    r"^\.env(\..*)?$", r"^credentials(\.json)?$", r"^token\.json$", r"^secrets?\.(json|ya?ml|toml)$",
    r"^\.(bash|zsh|python|node_repl|psql|mysql)_history$", r"^\.zhistory$",
]

# Commands the model may run, with an optional check on their arguments
SHELL_OPERATORS = {"|", "||", "&&", ";", ">", ">>", "<", "<<", "&"}
FIND_FORBIDDEN = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
GIT_SUBCOMMANDS = {"config", "log", "status", "branch", "rev-parse", "show", "describe", "shortlog", "diff", "ls-files"}
SYSTEM_PROFILER_TYPES = {"SPSoftwareDataType", "SPHardwareDataType", "SPDisplaysDataType", "SPStorageDataType"}


class ToolDenied(Exception):
    """The request is outside what the read-only tools allow."""


def _no_args(args: list[str]) -> None:
    if args:
        raise ToolDenied("this command takes no arguments here")


def _check_find(args: list[str]) -> None:
    bad = FIND_FORBIDDEN.intersection(args)
    if bad:
        raise ToolDenied(f"find {sorted(bad)[0]} is not allowed (read-only)")


def _check_grep(args: list[str]) -> None:
    for a in args:
        if a in ("-r", "-R", "--recursive", "--dereference-recursive") or (
            a.startswith("-") and not a.startswith("--") and ("r" in a[1:] or "R" in a[1:])
        ) or a.startswith("--directories=recurse") or a == "recurse":
            raise ToolDenied("recursive grep is not allowed; grep specific files instead")


def _check_git(args: list[str]) -> None:
    if not args or args[0].startswith("-"):
        raise ToolDenied("git needs a subcommand first (options like -c are not allowed)")
    if args[0] not in GIT_SUBCOMMANDS:
        raise ToolDenied(f"git {args[0]} is not allowed; use one of {', '.join(sorted(GIT_SUBCOMMANDS))}")
    if args[0] == "config" and not any(a in ("--get", "--get-all") for a in args[1:]):
        raise ToolDenied("git config is only allowed with --get")
    if args[0] == "diff" and any(a.startswith("--output") or a.startswith("--ext-diff") for a in args):
        raise ToolDenied("that git diff option is not allowed")


def _check_date(args: list[str]) -> None:
    for a in args:
        if not (a.startswith("+") or a in ("-u", "-R", "-I", "-j")):
            raise ToolDenied("date may only format the current time")


def _check_version_only(args: list[str]) -> None:
    if args not in (["--version"], ["-V"]):
        raise ToolDenied("only --version is allowed for this program")


def _check_scutil(args: list[str]) -> None:
    if len(args) != 2 or args[0] != "--get":
        raise ToolDenied("scutil is only allowed as: scutil --get ComputerName|LocalHostName|HostName")


def _check_dscl(args: list[str]) -> None:
    if len(args) < 3 or args[0] != "." or args[1] not in ("-read", "-list"):
        raise ToolDenied("dscl is only allowed as: dscl . -read /Users/<name> [key]")


def _check_sysctl(args: list[str]) -> None:
    if any("=" in a or a == "-w" for a in args):
        raise ToolDenied("sysctl may only read values")


def _check_system_profiler(args: list[str]) -> None:
    if not args or any(a not in SYSTEM_PROFILER_TYPES for a in args):
        raise ToolDenied(f"system_profiler is only allowed with {', '.join(sorted(SYSTEM_PROFILER_TYPES))}")


ALLOWED_COMMANDS = {
    "whoami": _no_args, "id": None, "hostname": _no_args, "uname": None, "sw_vers": None,
    "date": _check_date, "uptime": _no_args, "pwd": _no_args, "cal": None, "locale": None,
    "ls": None, "cat": None, "head": None, "tail": None, "wc": None, "file": None, "stat": None,
    "du": None, "df": None, "find": _check_find, "mdfind": None, "mdls": None, "grep": _check_grep,
    "which": None, "git": _check_git, "python3": _check_version_only, "node": _check_version_only,
    "scutil": _check_scutil, "dscl": _check_dscl, "sysctl": _check_sysctl,
    "system_profiler": _check_system_profiler,
}


@dataclass
class ToolResult:
    name: str
    args: dict
    ok: bool
    output: str
    error: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def for_model(self) -> str:
        if not self.ok:
            return f"ERROR: {self.error}"
        return self.output or "(no output)"


def is_denied_path(path: str | Path) -> Optional[str]:
    """Return a reason if the path points at secrets, else None."""
    p = Path(os.path.expanduser(str(path)))
    if not p.is_absolute():
        p = HOME / p
    try:
        p = p.resolve()
    except (OSError, RuntimeError):
        pass
    for d in DENIED_DIRS:
        blocked = (HOME / d).resolve() if (HOME / d).exists() else HOME / d
        if p == blocked or blocked in p.parents:
            return f"{d} is private and off limits"
    for part in p.parts:
        for pat in DENIED_NAME_PATTERNS:
            if re.match(pat, part, re.IGNORECASE):
                return f"{part} may contain credentials and is off limits"
    return None


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated, {len(text) - limit} more characters)"


def run_command(command: str) -> ToolResult:
    t0 = time.perf_counter()
    args = {"command": command}
    try:
        if "$(" in command or "`" in command:
            raise ToolDenied("command substitution is not allowed")
        try:
            argv = shlex.split(command)
        except ValueError as e:
            raise ToolDenied(f"could not parse command: {e}")
        if not argv:
            raise ToolDenied("empty command")
        if SHELL_OPERATORS.intersection(argv) or any(a.endswith((";", "|")) for a in argv):
            raise ToolDenied("pipes, redirects and chained commands are not allowed; run one command at a time")
        prog = os.path.basename(argv[0])
        if prog not in ALLOWED_COMMANDS:
            raise ToolDenied(f"'{prog}' is not an allowed read-only command")
        rest = [os.path.expanduser(a) for a in argv[1:]]
        check = ALLOWED_COMMANDS[prog]
        if check:
            check(rest)
        for a in rest:
            if not a.startswith("-"):
                reason = is_denied_path(a)
                if reason:
                    raise ToolDenied(reason)
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(HOME), "LANG": "en_US.UTF-8"}
        proc = subprocess.run(
            [prog, *rest], cwd=str(HOME), env=env, capture_output=True, text=True,
            timeout=COMMAND_TIMEOUT_S, stdin=subprocess.DEVNULL,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0 and not out:
            return ToolResult("run_command", args, False, "", _truncate(err or f"exit code {proc.returncode}", 1500),
                              (time.perf_counter() - t0) * 1000)
        if not out:
            out = "(no matches)" if prog in ("mdfind", "find", "grep") else (err or "(no output)")
        return ToolResult("run_command", args, True, _truncate(out), "", (time.perf_counter() - t0) * 1000)
    except ToolDenied as e:
        return ToolResult("run_command", args, False, "", f"denied: {e}", (time.perf_counter() - t0) * 1000)
    except subprocess.TimeoutExpired:
        return ToolResult("run_command", args, False, "", f"timed out after {COMMAND_TIMEOUT_S:.0f}s",
                          (time.perf_counter() - t0) * 1000)
    except FileNotFoundError:
        return ToolResult("run_command", args, False, "", f"'{argv[0]}' is not installed", (time.perf_counter() - t0) * 1000)


def read_file(path: str) -> ToolResult:
    t0 = time.perf_counter()
    args = {"path": path}
    reason = is_denied_path(path)
    if reason:
        return ToolResult("read_file", args, False, "", f"denied: {reason}")
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        p = HOME / p
    try:
        if not p.is_file():
            return ToolResult("read_file", args, False, "", "not a file (use list_dir for folders)")
        with open(p, "rb") as f:
            raw = f.read(MAX_FILE_BYTES + 1)
        if b"\x00" in raw[:2048]:
            return ToolResult("read_file", args, False, "", "binary file; cannot show as text")
        text = raw[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
        if len(raw) > MAX_FILE_BYTES:
            text += f"\n... (truncated at {MAX_FILE_BYTES} bytes)"
        return ToolResult("read_file", args, True, text, "", (time.perf_counter() - t0) * 1000)
    except OSError as e:
        return ToolResult("read_file", args, False, "", str(e), (time.perf_counter() - t0) * 1000)


def list_dir(path: str = "~") -> ToolResult:
    t0 = time.perf_counter()
    args = {"path": path}
    reason = is_denied_path(path)
    if reason:
        return ToolResult("list_dir", args, False, "", f"denied: {reason}")
    p = Path(os.path.expanduser(path or "~"))
    if not p.is_absolute():
        p = HOME / p
    try:
        def modified(e: Path) -> float:
            try:
                return e.stat().st_mtime
            except OSError:
                return 0.0
        # Newest first, with dates, so "latest"/"recent" questions can be answered directly
        entries = sorted(p.iterdir(), key=modified, reverse=True)
        lines = [
            f"{datetime.fromtimestamp(modified(e)).strftime('%Y-%m-%d %H:%M')}  {e.name}{'/' if e.is_dir() else ''}"
            for e in entries if not e.name.startswith(".")
        ]
        hidden = sum(1 for e in entries if e.name.startswith("."))
        more = len(lines) - MAX_DIR_ENTRIES
        text = "\n".join(lines[:MAX_DIR_ENTRIES])
        if more > 0:
            text += f"\n... ({more} more)"
        if hidden:
            text += f"\n({hidden} hidden entries not shown)"
        return ToolResult("list_dir", args, True, text or "(empty)", "", (time.perf_counter() - t0) * 1000)
    except OSError as e:
        return ToolResult("list_dir", args, False, "", str(e), (time.perf_counter() - t0) * 1000)


TOOLS = {"run_command": run_command, "read_file": read_file, "list_dir": list_dir}


def run_tool(call: dict) -> ToolResult:
    name = call.get("name", "")
    args = call.get("args") or {}
    if not isinstance(args, dict):
        args = {}
    fn = TOOLS.get(name)
    if not fn:
        hint = ""
        if name in ALLOWED_COMMANDS:
            hint = f' To run a program, call {{"name": "run_command", "args": {{"command": "{name} ..."}}}}.'
        return ToolResult(name or "?", args, False, "", f"unknown tool '{name}'; the tools are {', '.join(TOOLS)}.{hint}")
    try:
        if name == "run_command":
            return fn(str(args.get("command", "")))
        return fn(str(args.get("path", "~")))
    except Exception as e:  # never let a tool crash the stream
        return ToolResult(name, args, False, "", f"tool error: {e}")


_DECODER = json.JSONDecoder()


def parse_tool_call(text: str) -> Optional[dict]:
    """Find a tool call in model output.

    Accepts <tool>{...}</tool> (closing tag optional, trailing text ignored) or a
    reply that starts with the JSON object itself. Returns None until the JSON is
    complete, so it can be called on a partial stream.
    """
    visible = re.sub(r"<think>.*?(</think>|$)", "", text, flags=re.DOTALL)
    start = -1
    tag = visible.find("<tool>")
    if tag >= 0:
        start = visible.find("{", tag)
    else:
        stripped = re.sub(r"^\s*```(?:json)?\s*", "", visible)
        if re.match(r'\{\s*"name"\s*:', stripped):
            visible, start = stripped, 0
    if start < 0:
        return None
    try:
        call, _ = _DECODER.raw_decode(visible[start:])
    except json.JSONDecodeError:
        return None
    # Unknown names are still returned so the model gets a corrective error back
    if not isinstance(call, dict) or not isinstance(call.get("name"), str):
        return None
    return call


def _quiet(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=2, stdin=subprocess.DEVNULL)
        return out.stdout.strip()
    except Exception:
        return ""


def machine_context() -> dict:
    """Basic facts about this machine and its user, gathered locally."""
    user = getpass.getuser()
    full_name = ""
    if pwd:
        try:
            full_name = pwd.getpwnam(user).pw_gecos.split(",")[0].strip()
        except KeyError:
            pass
    ctx = {
        "username": user,
        "full_name": full_name,
        "git_name": _quiet(["git", "config", "--global", "--get", "user.name"]),
        "git_email": _quiet(["git", "config", "--global", "--get", "user.email"]),
        "home": str(HOME),
        "hostname": socket.gethostname(),
        "computer_name": _quiet(["scutil", "--get", "ComputerName"]) if platform.system() == "Darwin" else "",
        "os": (f"macOS {platform.mac_ver()[0]}" if platform.system() == "Darwin" else platform.platform()),
        "shell": os.environ.get("SHELL", ""),
        "local_time": datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M %Z"),
    }
    return {k: v for k, v in ctx.items() if v}


def computer_system_prompt(ctx: Optional[dict] = None) -> str:
    ctx = ctx if ctx is not None else machine_context()
    facts = "\n".join(f"- {k.replace('_', ' ')}: {v}" for k, v in ctx.items())
    allowed = ", ".join(sorted(ALLOWED_COMMANDS))
    return (
        "COMPUTER ACCESS IS ON. You are running on the user's own computer and may look things up on it.\n"
        "Facts about this computer and its user (already gathered, use them directly):\n"
        f"{facts}\n\n"
        "If the facts above do not answer the question, use a read-only tool. To call one, reply with ONLY:\n"
        '<tool>{"name": "run_command", "args": {"command": "ls ~/Documents"}}</tool>\n'
        "Tools:\n"
        '- run_command {"command": "..."}: one command, no pipes or redirects. Allowed programs: '
        f"{allowed}.\n"
        "  To find a file anywhere on the computer by name: mdfind -name resume\n"
        "  To search file contents: mdfind \"quarterly report\"\n"
        '- read_file {"path": "~/path/to/file.txt"}: read a text file.\n'
        '- list_dir {"path": "~/Desktop"}: list a folder, newest first, with modified dates.\n'
        f"You get each result back and may call up to {MAX_TOOL_ROUNDS} tools in total, one per reply. "
        "Keys, passwords, browser data and shell history are blocked. "
        "To locate a file, search with mdfind first instead of listing folders and guessing from names. "
        "When you have enough information, answer in plain language without a tool call. "
        "Never claim you lack access to this computer; look it up instead."
    )
