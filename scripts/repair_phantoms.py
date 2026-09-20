#!/usr/bin/env python3
"""Return posts that were recorded as scheduled but that LinkedIn does not hold.

A slot in content/posts_sent.txt means "we asked LinkedIn to schedule this, and
the poster believed it worked".  Sometimes it did not work.  The post was then
removed from the queue and will never be published, while the slot stays marked
taken forever.  Those are what this script calls phantoms.

It uses the list read by scripts/check_scheduled.py (logs/scheduled_list_dump.txt)
as the source of truth, because LinkedIn is the only thing that knows what
LinkedIn actually holds.

For every phantom record it:
    1. removes the record from content/posts_sent.txt, which frees the slot so
       the planner can fill that time again
    2. puts the post back at the end of content/posts_queue.txt so it gets
       scheduled again

Refuses to run on stale evidence: if the LinkedIn dump is older than
posts_sent.txt, the dump may not describe the file it is about to edit.

DRY RUN BY DEFAULT.  Nothing is written without --apply.

Usage:
    python3 scripts/check_scheduled.py          # refresh the evidence first
    python3 scripts/repair_phantoms.py          # show what would move
    python3 scripts/repair_phantoms.py --apply  # do it
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from check_scheduled import parse_linkedin_slots  # noqa: E402

SENT_FILE = PKG_ROOT / "content" / "posts_sent.txt"
QUEUE_FILE = PKG_ROOT / "content" / "posts_queue.txt"
DEFAULT_DUMP = PKG_ROOT / "logs" / "scheduled_list_dump.txt"

TIMESTAMP_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC\]", re.M)
SLOT_RE = re.compile(r"^scheduled_for=(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*$", re.M)
RECORD_ID_RE = re.compile(r"^record_id=([0-9a-f]{64})\s*$", re.M)


class Record:
    """One block of posts_sent.txt."""

    __slots__ = ("raw", "slot", "record_id", "body")

    def __init__(self, raw: str) -> None:
        self.raw = raw
        slot_match = SLOT_RE.search(raw)
        self.slot = slot_match.group(1) if slot_match else None
        id_match = RECORD_ID_RE.search(raw)
        self.record_id = id_match.group(1) if id_match else None
        self.body = self._extract_body(raw)

    @staticmethod
    def _extract_body(raw: str) -> str:
        """Everything after the header lines, which are timestamp, id, slot."""
        lines = raw.split("\n")
        index = 0
        for i, line in enumerate(lines):
            if line.startswith("[") and line.endswith("UTC]"):
                index = i + 1
                break
        while index < len(lines) and (
            lines[index].startswith("record_id=")
            or lines[index].startswith("scheduled_for=")
            or lines[index].startswith("status=")
            or lines[index].startswith("error=")
        ):
            index += 1
        return "\n".join(lines[index:]).strip()


def read_records(path: Path) -> tuple[list[Record], str]:
    """Split a queue-style history file into records.

    Returns (records, trailing_empty_block) so the file can be rebuilt exactly.
    """
    raw = path.read_text(encoding="utf-8")
    blocks = raw.split("\n---\n")
    trailing_empty = blocks and not blocks[-1].strip()
    if trailing_empty:
        blocks = blocks[:-1]
    return [Record(b) for b in blocks if b.strip()], trailing_empty


def render(records: list[Record], trailing_empty: bool = True) -> str:
    out = "\n---\n".join(r.raw for r in records)
    if trailing_empty:
        out += "\n---\n"
    return out


def local_now() -> datetime:
    """Slots in these files are stored in the account's local time."""
    return datetime.now()


def read_queue_bodies(path: Path) -> list[str]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    return [b.strip() for b in raw.split("\n---\n") if b.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Write the changes.")
    parser.add_argument("--dump", default=str(DEFAULT_DUMP), help="LinkedIn list dump to trust.")
    parser.add_argument("--force", action="store_true", help="Ignore the staleness check.")
    args = parser.parse_args()

    dump_path = Path(args.dump)
    if not dump_path.exists():
        print(f"No LinkedIn list dump at {dump_path}")
        print("Run scripts/check_scheduled.py first: it is the evidence this needs.")
        return 1

    if not SENT_FILE.exists():
        print(f"No {SENT_FILE}")
        return 1

    # The dump must not be older than the file it is about to judge.
    if not args.force and dump_path.stat().st_mtime < SENT_FILE.stat().st_mtime:
        dump_age = dump_path.stat().st_mtime
        sent_age = SENT_FILE.stat().st_mtime
        print("Refusing to run on stale evidence.")
        print(f"  {dump_path.name} is {sent_age - dump_age:.0f}s older than {SENT_FILE.name}")
        print("  posts_sent.txt changed after the LinkedIn read, so the read may not")
        print("  describe the file being edited. Re-run check_scheduled.py,")
        print("  or pass --force if you are sure.")
        return 2

    linkedin = set(parse_linkedin_slots(dump_path.read_text(encoding="utf-8")))
    records, trailing_empty = read_records(SENT_FILE)
    queue = read_queue_bodies(QUEUE_FILE)

    now = local_now()
    phantoms: list[Record] = []
    for record in records:
        if not record.slot:
            continue                      # posted immediately, no slot to check
        try:
            when = datetime.strptime(record.slot, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if when <= now:
            continue                      # already past; LinkedIn cannot confirm it
        if record.slot not in linkedin:
            phantoms.append(record)

    print("=" * 62)
    print("  Phantom repair")
    print("=" * 62)
    print(f"LinkedIn times in the dump:            {len(linkedin)}")
    print(f"Records in posts_sent.txt:             {len(records)}")
    print(f"Posts waiting in the queue:            {len(queue)}")
    print(f"Phantom records (future, not on LI):   {len(phantoms)}")

    if not phantoms:
        print("\nNothing to repair.")
        return 0

    phantom_slots = sorted({r.slot for r in phantoms})
    print(f"Distinct phantom slots:                {len(phantom_slots)}")

    phantom_ids = {r.record_id for r in phantoms}
    kept = [r for r in records if r.record_id not in phantom_ids]

    # A post must not be re-queued if the same text is already waiting there,
    # or it would be scheduled twice.
    existing = {b.strip() for b in queue}
    to_requeue: list[str] = []
    already_waiting: list[Record] = []
    for record in phantoms:
        body = record.body.strip()
        if not body:
            continue
        if body in existing:
            already_waiting.append(record)
            continue
        existing.add(body)
        to_requeue.append(body)

    print(f"\nPosts to put back in the queue:        {len(to_requeue)}")
    print(f"Already present in the queue (skipped): {len(already_waiting)}")
    print(f"Records that will be removed:          {len(phantoms)}")
    print(f"Records that will remain:              {len(kept)}")

    print("\nPhantom slots being freed:")
    for slot in phantom_slots:
        print(f"  {slot}")

    if not args.apply:
        print("\nDRY RUN. Nothing written. Re-run with --apply to make these changes.")
        return 0

    if not to_requeue and not phantoms:
        print("\nNothing to write.")
        return 0

    backup_dir = SENT_FILE.parent / "_backup_repair"
    backup_dir.mkdir(exist_ok=True)
    stamp = now.strftime("%Y-%m-%d_%H%M%S")
    (backup_dir / f"posts_sent.{stamp}.txt").write_text(SENT_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    (backup_dir / f"posts_queue.{stamp}.txt").write_text(
        QUEUE_FILE.read_text(encoding="utf-8") if QUEUE_FILE.exists() else "", encoding="utf-8"
    )

    SENT_FILE.write_text(render(kept, trailing_empty), encoding="utf-8")

    new_queue = queue + to_requeue
    QUEUE_FILE.write_text("\n---\n".join(new_queue) + "\n---\n", encoding="utf-8")

    print(f"\nWrote {SENT_FILE.name}: {len(records)} records -> {len(kept)}")
    print(f"Wrote {QUEUE_FILE.name}: {len(queue)} posts -> {len(new_queue)}")
    print(f"Backups in {backup_dir}")

    # Verify by re-reading what is now on disk.
    check_records, _ = read_records(SENT_FILE)
    check_queue = read_queue_bodies(QUEUE_FILE)
    remaining = [r for r in check_records if r.slot in set(phantom_slots)]
    duplicates = len(check_queue) - len({b.strip() for b in check_queue})

    print("\nVerification, re-read from disk:")
    print(f"  records now:                 {len(check_records)}")
    print(f"  queue now:                   {len(check_queue)}")
    print(f"  phantom slots still recorded: {len(remaining)}")
    print(f"  duplicate posts in the queue: {duplicates}")

    ok = (
        len(check_records) == len(kept)
        and len(check_queue) == len(new_queue)
        and not remaining
        and duplicates == 0
        and len(phantom_ids) == len(phantoms)
    )
    print("\n" + ("OK" if ok else "MISMATCH — check the backups before trusting this"))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
