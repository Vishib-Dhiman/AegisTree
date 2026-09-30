"""Live ingestion: reload the memory graph when ADRs or notes change on disk.

Polls instead of using OS file events so it needs no extra dependency and
behaves the same on every machine. A workspace has tens of Markdown files, so
fingerprinting them once a second is cheap.
"""

from __future__ import annotations
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# Same locations WorkspaceIngestor reads
WATCHED_DIRS = ("docs/adr", "adr", "docs/decisions", "notes")

Fingerprint = Dict[str, Tuple[int, int]]


def fingerprint(root: Path) -> Fingerprint:
    """{relative path: (mtime_ns, size)} for every watched Markdown file."""
    prints: Fingerprint = {}
    for rel in WATCHED_DIRS:
        d = root / rel
        if not d.is_dir():
            continue
        for md in d.glob("*.md"):
            try:
                st = md.stat()
            except OSError:
                continue
            prints[str(md.relative_to(root))] = (st.st_mtime_ns, st.st_size)
    return prints


def diff_fingerprints(old: Fingerprint, new: Fingerprint) -> Dict[str, List[str]]:
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "modified": sorted(p for p in set(old) & set(new) if old[p] != new[p]),
    }


@dataclass
class ChangeEvent:
    seq: int
    at: float
    workspace: str
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    modified: List[str] = field(default_factory=list)
    error: Optional[str] = None


class WorkspaceWatcher:
    """Calls on_change(changes) whenever the watched files of the current root change.

    get_root returns the workspace to watch, or None to pause (No-workspace mode).
    A change of root re-baselines silently: switching workspaces already reloads.
    """

    def __init__(
        self,
        get_root: Callable[[], Optional[Path]],
        on_change: Callable[[Dict[str, List[str]]], None],
        interval: float = 1.0,
        max_events: int = 50,
    ):
        self.get_root = get_root
        self.on_change = on_change
        self.interval = interval
        self.max_events = max_events
        self.events: List[ChangeEvent] = []
        self._seq = 0
        self._root: Optional[Path] = None
        self._prints: Fingerprint = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def poll_once(self) -> Optional[ChangeEvent]:
        root = self.get_root()
        if root is None:
            self._root = None
            return None
        if root != self._root:
            self._root, self._prints = root, fingerprint(root)
            return None

        new = fingerprint(root)
        changes = diff_fingerprints(self._prints, new)
        if not any(changes.values()):
            return None
        self._prints = new

        error = None
        try:
            self.on_change(changes)
        except Exception as ex:  # keep watching even if one reload fails
            error = str(ex)
        with self._lock:
            self._seq += 1
            event = ChangeEvent(self._seq, time.time(), root.name, error=error, **changes)
            self.events = (self.events + [event])[-self.max_events:]
        return event

    def events_since(self, seq: int) -> List[ChangeEvent]:
        with self._lock:
            return [e for e in self.events if e.seq > seq]

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.poll_once()  # baseline now, so nothing saved in the first interval is missed
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="adr-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.poll_once()
            except Exception:
                continue
