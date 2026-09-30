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
from typing import Callable, Dict, Iterable, List, Optional, Tuple, Union

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
    root: str = ""


class WorkspaceWatcher:
    """Calls on_change(changes) whenever the watched files of a watched root change.

    get_root returns the workspace(s) to watch: one path, a list (several users
    in different workspaces), or None to pause. A root that starts being
    watched is baselined silently (opening a workspace already loads it); one
    that stops being watched is forgotten. changes["root"] names the workspace.
    """

    def __init__(
        self,
        get_root: Callable[[], Union[None, Path, Iterable[Path]]],
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
        self._prints: Dict[Path, Fingerprint] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _current_roots(self) -> List[Path]:
        roots = self.get_root()
        if roots is None:
            return []
        if isinstance(roots, (str, Path)):
            return [Path(roots)]
        return [Path(r) for r in roots]

    def poll_once(self) -> Optional[ChangeEvent]:
        """Check every watched root; returns the last event raised, if any."""
        roots = self._current_roots()
        for gone in set(self._prints) - set(roots):
            del self._prints[gone]
        last: Optional[ChangeEvent] = None
        for root in roots:
            if root not in self._prints:
                self._prints[root] = fingerprint(root)
                continue
            new = fingerprint(root)
            changes = diff_fingerprints(self._prints[root], new)
            if not any(changes.values()):
                continue
            self._prints[root] = new

            error = None
            try:
                self.on_change({**changes, "root": str(root)})
            except Exception as ex:  # keep watching even if one reload fails
                error = str(ex)
            with self._lock:
                self._seq += 1
                last = ChangeEvent(self._seq, time.time(), root.name, error=error, root=str(root), **changes)
                self.events = (self.events + [last])[-self.max_events:]
        return last

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
