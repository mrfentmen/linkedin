"""Durable state for browser-based LinkedIn scheduling.

The scheduler can be interrupted after LinkedIn accepts a post but before the
process updates the queue.  This module records the outcome first, using an
atomic replace, so a later run can reconcile the queue without guessing.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class ScheduleStateCorrupt(RuntimeError):
    """Raised when the durable journal cannot be trusted."""


class ScheduleRunLocked(RuntimeError):
    """Raised when another scheduler process already owns the run lock."""


def _pid_alive(pid: int) -> bool:
    """True if a process with this pid currently exists.

    Signal 0 performs the permission and existence checks without delivering
    anything.  A PermissionError means the process exists but belongs to someone
    else, which still counts as alive.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


class ExclusiveRunLock:
    """Small cross-process lock for queue/scheduler mutations."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._owned = False

    def _owner_pid(self) -> int | None:
        """Pid recorded in the lock file, or None when it cannot be read."""
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        for token in raw.split():
            if token.startswith("pid="):
                value = token[4:].strip()
                if value.isdigit():
                    return int(value)
        return None

    def _break_if_stale(self) -> bool:
        """Drop the lock when the pid that wrote it is gone.

        A killed poster used to leave its lock file behind, and because acquire
        only ever checked for the file's existence, that dead lock blocked every
        later run forever.  Nothing recovers it except deleting the file by hand.
        Returns True only when a genuinely stale lock was removed.
        """
        pid = self._owner_pid()
        if pid is None or pid == os.getpid():
            return False
        if _pid_alive(pid):
            return False
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        return True

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in (1, 2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as exc:
                # One retry, and only after confirming the owner is dead.
                if attempt == 1 and self._break_if_stale():
                    continue
                raise ScheduleRunLocked(
                    f"Another scheduler appears to be running ({self.path})."
                ) from exc
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"pid={os.getpid()}\n")
            self._owned = True
            return
        raise ScheduleRunLocked(
            f"Another scheduler appears to be running ({self.path})."
        )

    def release(self) -> None:
        if self._owned:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self._owned = False

    def __enter__(self) -> "ExclusiveRunLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class PostStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    DRY_RUN = "dry_run"
    SCHEDULED = "scheduled"
    POSTED = "posted"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class PostResult:
    """Result of one browser attempt.

    AMBIGUOUS means the Schedule action may have been accepted but the browser
    closed or no reliable confirmation was observed.  It must never be
    retried automatically.
    """

    status: PostStatus
    content: str
    schedule_time: str | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {PostStatus.SCHEDULED, PostStatus.POSTED}

    @property
    def terminal(self) -> bool:
        return self.status in {
            PostStatus.SCHEDULED,
            PostStatus.POSTED,
            PostStatus.AMBIGUOUS,
        }

    @property
    def record_id(self) -> str:
        return make_record_id(self.content, self.schedule_time)


def make_record_id(content: str, schedule_time: str | None) -> str:
    raw = f"{schedule_time or ''}\n{content}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


class ScheduleState:
    """JSON-backed per-post state journal.

    The file is intentionally a compact object keyed by a deterministic
    record id.  Writes replace the whole document atomically, so a process
    dying during serialization cannot leave a half-written state file.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.records: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            records = raw.get("records", {}) if isinstance(raw, dict) else {}
            if isinstance(records, dict):
                self.records = records
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            # Failing closed is essential: treating a damaged journal as
            # empty could schedule already-processed posts again.
            raise ScheduleStateCorrupt(
                f"Cannot safely read schedule state at {self.path}; "
                "preserve/reconcile it before resuming."
            ) from exc

    def get(self, result_or_id: PostResult | str) -> dict[str, Any] | None:
        key = result_or_id if isinstance(result_or_id, str) else result_or_id.record_id
        return self.records.get(key)

    def record(self, result: PostResult) -> dict[str, Any]:
        entry = {
            "record_id": result.record_id,
            "status": result.status.value,
            "content": result.content,
            "schedule_time": result.schedule_time,
            "error": result.error,
            "updated_at": _now(),
        }
        previous = self.records.get(result.record_id)
        attempts = int(previous.get("attempts", 0)) if previous else 0
        entry["attempts"] = attempts + 1
        self.records[result.record_id] = entry
        _atomic_write(self.path, {"version": 1, "records": self.records})
        return entry

    def terminal_results(self) -> list[dict[str, Any]]:
        terminal = {s.value for s in (PostStatus.SCHEDULED, PostStatus.POSTED, PostStatus.AMBIGUOUS)}
        return [r for r in self.records.values() if r.get("status") in terminal]

    def is_finalized(self, result_or_id: PostResult | str) -> bool:
        key = result_or_id if isinstance(result_or_id, str) else result_or_id.record_id
        record = self.records.get(key)
        return bool(record and record.get("finalized"))

    def mark_finalized(self, result_or_id: PostResult | str) -> None:
        key = result_or_id if isinstance(result_or_id, str) else result_or_id.record_id
        if key in self.records:
            self.records[key]["finalized"] = True
            self.records[key]["updated_at"] = _now()
            _atomic_write(self.path, {"version": 1, "records": self.records})

    def recover_in_progress(self) -> int:
        """Convert interrupted attempts into ambiguous records.

        An in-progress attempt may have clicked LinkedIn's Schedule button
        immediately before the process died, so it is never safe to retry
        automatically.
        """
        changed = 0
        for entry in self.records.values():
            if entry.get("status") == PostStatus.IN_PROGRESS.value:
                entry["status"] = PostStatus.AMBIGUOUS.value
                entry["error"] = "Process interrupted while scheduling; verify in LinkedIn before retrying."
                entry["updated_at"] = _now()
                changed += 1
        if changed:
            _atomic_write(self.path, {"version": 1, "records": self.records})
        return changed
