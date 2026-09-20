"""Tests for the phantom repair.

A phantom is a record in posts_sent.txt that claims a slot LinkedIn does not
hold.  The post was taken out of the queue and will never publish.  Repair
frees the slot and puts the post back in the queue.

These tests cover the parsing, the record/no-record decision, and a full
--apply run against temp files, including that a file with no phantoms is left
byte identical.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import repair_phantoms as repair  # noqa: E402

RECORD_ID_1 = "a" * 64
RECORD_ID_2 = "b" * 64


def sent_file_text(*slots: str) -> str:
    out = []
    for index, slot in enumerate(slots):
        body = f"Body for slot {slot}."
        out.append(
            f"[2026-09-20 10:00:00 UTC]\n"
            f"record_id={(RECORD_ID_1 if index == 0 else RECORD_ID_2)}\n"
            f"scheduled_for={slot}\n"
            f"{body}"
        )
    return "\n---\n".join(out) + "\n---\n"


def linkedin_dump(*slots: list[tuple[str, int, str]]) -> str:
    """slots are (month, day, '8:30 AM') tuples for year 2030."""
    return "\n".join(
        f"Posting Mon, {month} {day}, 2030 at {time}" for month, day, time in slots
    )


def test_read_records_extracts_slot_and_body(tmp_path: Path):
    path = tmp_path / "sent.txt"
    path.write_text(sent_file_text("2030-01-05 09:00"), encoding="utf-8")
    records, trailing_empty = repair.read_records(path)
    assert trailing_empty is True
    assert len(records) == 1
    assert records[0].slot == "2030-01-05 09:00"
    assert records[0].record_id == RECORD_ID_1
    assert records[0].body == "Body for slot 2030-01-05 09:00."


def test_read_records_and_render_round_trip_is_byte_identical(tmp_path: Path):
    original = sent_file_text("2030-01-05 09:00", "2030-01-06 10:00")
    path = tmp_path / "sent.txt"
    path.write_text(original, encoding="utf-8")
    records, trailing_empty = repair.read_records(path)
    assert repair.render(records, trailing_empty) == original


def _patch_paths(monkeypatch, tmp_path: Path, sent_text: str, dump_text: str) -> tuple[Path, Path, Path]:
    sent = tmp_path / "posts_sent.txt"
    queue = tmp_path / "posts_queue.txt"
    dump = tmp_path / "scheduled_list_dump.txt"
    sent.write_text(sent_text, encoding="utf-8")
    queue.write_text("A post that is already waiting.\n---\n", encoding="utf-8")
    dump.write_text(dump_text, encoding="utf-8")
    # Evidence must not be older than the file it judges.
    os.utime(sent, (1_000_000, 1_000_000))
    os.utime(dump, (2_000_000, 2_000_000))
    monkeypatch.setattr(repair, "SENT_FILE", sent)
    monkeypatch.setattr(repair, "QUEUE_FILE", queue)
    return sent, queue, dump


def _argv(dump: Path, *extra: str) -> list[str]:
    """Always pass the temp dump, or the real one would be used as evidence."""
    return ["repair_phantoms.py", "--dump", str(dump), *extra]


def test_apply_frees_the_slot_and_requeues_the_post(monkeypatch, tmp_path: Path, capsys):
    # Slot 2030-01-05 09:00 is claimed but LinkedIn only holds 2030-01-06 10:00.
    sent, queue, dump = _patch_paths(
        monkeypatch,
        tmp_path,
        sent_file_text("2030-01-05 09:00", "2030-01-06 10:00"),
        linkedin_dump(("Jan", 6, "10:00 AM")),
    )
    monkeypatch.setattr(sys, "argv", _argv(dump, "--apply"))

    assert repair.main() == 0

    kept = sent.read_text(encoding="utf-8")
    assert "2030-01-05 09:00" not in kept
    assert "2030-01-06 10:00" in kept

    queued = [b.strip() for b in queue.read_text(encoding="utf-8").split("\n---\n") if b.strip()]
    assert "A post that is already waiting." in queued
    assert "Body for slot 2030-01-05 09:00." in queued
    assert len(queued) == 2
    assert len(queued) == len(set(queued)), "no duplicates in the queue"

    out = capsys.readouterr().out
    assert "Phantom records (future, not on LI):   1" in out
    assert "OK" in out


def test_dry_run_changes_nothing(monkeypatch, tmp_path: Path):
    sent, queue, dump = _patch_paths(
        monkeypatch,
        tmp_path,
        sent_file_text("2030-01-05 09:00"),
        linkedin_dump(("Jan", 6, "10:00 AM")),
    )
    before_sent = sent.read_text(encoding="utf-8")
    before_queue = queue.read_text(encoding="utf-8")
    monkeypatch.setattr(sys, "argv", _argv(dump))

    assert repair.main() == 0
    assert sent.read_text(encoding="utf-8") == before_sent
    assert queue.read_text(encoding="utf-8") == before_queue


def test_a_slot_linkedin_holds_is_left_alone(monkeypatch, tmp_path: Path, capsys):
    sent, _queue, dump = _patch_paths(
        monkeypatch,
        tmp_path,
        sent_file_text("2030-01-05 09:00"),
        linkedin_dump(("Jan", 5, "9:00 AM")),
    )
    before = sent.read_text(encoding="utf-8")
    monkeypatch.setattr(sys, "argv", _argv(dump, "--apply"))

    assert repair.main() == 0
    assert sent.read_text(encoding="utf-8") == before
    assert "Nothing to repair." in capsys.readouterr().out


def test_a_past_slot_is_never_treated_as_a_phantom(monkeypatch, tmp_path: Path, capsys):
    """LinkedIn only lists future posts, so a past slot proves nothing."""
    sent, _queue, dump = _patch_paths(
        monkeypatch,
        tmp_path,
        sent_file_text("2020-01-05 09:00"),
        linkedin_dump(("Jan", 6, "10:00 AM")),
    )
    before = sent.read_text(encoding="utf-8")
    monkeypatch.setattr(sys, "argv", _argv(dump, "--apply"))

    assert repair.main() == 0
    assert sent.read_text(encoding="utf-8") == before
    assert "Nothing to repair." in capsys.readouterr().out


def test_refuses_to_run_on_stale_evidence(monkeypatch, tmp_path: Path, capsys):
    sent, _queue, dump = _patch_paths(
        monkeypatch,
        tmp_path,
        sent_file_text("2030-01-05 09:00"),
        linkedin_dump(("Jan", 6, "10:00 AM")),
    )
    # Make the dump older than the file it would judge.
    os.utime(sent, (3_000_000, 3_000_000))
    before = sent.read_text(encoding="utf-8")
    monkeypatch.setattr(sys, "argv", _argv(dump, "--apply"))

    assert repair.main() == 2
    assert sent.read_text(encoding="utf-8") == before
    assert "stale evidence" in capsys.readouterr().out


def test_a_post_already_in_the_queue_is_not_added_twice(monkeypatch, tmp_path: Path, capsys):
    sent_text = sent_file_text("2030-01-05 09:00")
    sent, queue, dump = _patch_paths(
        monkeypatch,
        tmp_path,
        sent_text,
        linkedin_dump(("Jan", 6, "10:00 AM")),
    )
    # The same text is already waiting in the queue.
    queue.write_text("Body for slot 2030-01-05 09:00.\n---\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", _argv(dump, "--apply"))

    assert repair.main() == 0
    queued = [b.strip() for b in queue.read_text(encoding="utf-8").split("\n---\n") if b.strip()]
    assert queued == ["Body for slot 2030-01-05 09:00."]
    assert "Already present in the queue (skipped): 1" in capsys.readouterr().out


def test_missing_dump_is_refused(monkeypatch, tmp_path: Path, capsys):
    sent = tmp_path / "posts_sent.txt"
    sent.write_text(sent_file_text("2030-01-05 09:00"), encoding="utf-8")
    monkeypatch.setattr(repair, "SENT_FILE", sent)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path / "nope.txt"))

    assert repair.main() == 1
    assert "No LinkedIn list dump" in capsys.readouterr().out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
