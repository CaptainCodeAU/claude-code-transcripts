"""Tests for the drifted-folder merge mode in scripts/reconcile_sessions.py.

The flagship CLI now resolves project names cwd-first via the fixed
``get_project_display_name``, but the archive still contains sessions misrouted
by the old buggy plugin (e.g. ``CaptainCodeAU-claude-transcripts/`` when the
correct folder is ``CaptainCodeAU-claude-code-transcripts/``). The drift mode
re-derives each session's correct project from its JSONL ``cwd`` and either
moves it (no collision), de-dupes (byte-equal collision), or refuses (content-
differing collision — never auto-resolves; honors the no-delete rule).
"""

import sys
from pathlib import Path

import pytest

# Make the script importable.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from reconcile_sessions import (
    DriftAction,
    DriftedSession,
    DriftPlanItem,
    DriftReport,
    classify_drift,
    execute_drift_plan,
    find_drifted_sessions,
    format_drift_plan,
    main,
)

# ---- fixture helpers ----


def _make_session(
    archive: Path, project: str, uuid: str, cwd: str, jsonl_body: str = ""
) -> Path:
    """Create archive/<project>/<uuid>/<uuid>.jsonl with the given cwd field."""
    session_dir = archive / project / uuid
    session_dir.mkdir(parents=True)
    body = jsonl_body or f'{{"type":"user","cwd":"{cwd}","message":{{}}}}\n'
    (session_dir / f"{uuid}.jsonl").write_text(body)
    return session_dir


# A cwd whose fixed get_project_display_name derives to "Owner-claude-code-transcripts".
CWD_CORRECT = "/Users/test/CODE/Owner/claude-code-transcripts"
PROJ_CORRECT = "Owner-claude-code-transcripts"
PROJ_WRONG = "Owner-claude-transcripts"  # the misroute (dropped "code")

U1 = "aaaaaaaa-0000-0000-0000-000000000001"
U2 = "aaaaaaaa-0000-0000-0000-000000000002"
U3 = "aaaaaaaa-0000-0000-0000-000000000003"


# ---- find_drifted_sessions ----


class TestFindDriftedSessions:
    def test_no_drift_when_cwd_matches_folder(self, tmp_path):
        _make_session(tmp_path, PROJ_CORRECT, U1, CWD_CORRECT)
        drifted, skipped = find_drifted_sessions(tmp_path)
        assert drifted == []
        assert skipped == []

    def test_detects_session_whose_cwd_disagrees_with_folder(self, tmp_path):
        _make_session(tmp_path, PROJ_WRONG, U1, CWD_CORRECT)
        drifted, skipped = find_drifted_sessions(tmp_path)
        assert len(drifted) == 1
        d = drifted[0]
        assert d.current_project == PROJ_WRONG
        assert d.correct_project == PROJ_CORRECT
        assert d.cwd == CWD_CORRECT
        assert d.uuid_dir.name == U1

    def test_skips_session_with_no_cwd_in_jsonl(self, tmp_path):
        _make_session(
            tmp_path,
            PROJ_WRONG,
            U1,
            "",
            jsonl_body='{"type":"user","message":{}}\n',
        )
        drifted, skipped = find_drifted_sessions(tmp_path)
        assert drifted == []
        assert len(skipped) == 1
        assert skipped[0][0].name == U1
        assert "no cwd" in skipped[0][1].lower()

    def test_skips_underscore_prefixed_folders(self, tmp_path):
        # _DELETE/ subfolders must NOT be scanned for drift.
        _make_session(tmp_path, "_DELETE/drift-dedupe", U1, CWD_CORRECT)
        drifted, skipped = find_drifted_sessions(tmp_path)
        assert drifted == []
        assert skipped == []

    def test_ignores_files_at_archive_root(self, tmp_path):
        # The master index.html sits at the archive root; iteration must not break.
        (tmp_path / "index.html").write_text("<html></html>")
        _make_session(tmp_path, PROJ_CORRECT, U1, CWD_CORRECT)
        drifted, skipped = find_drifted_sessions(tmp_path)
        assert drifted == []


# ---- classify_drift ----


class TestClassifyDrift:
    def _drifted(self, tmp_path) -> DriftedSession:
        uuid_dir = _make_session(tmp_path, PROJ_WRONG, U1, CWD_CORRECT)
        return DriftedSession(
            uuid_dir=uuid_dir,
            current_project=PROJ_WRONG,
            correct_project=PROJ_CORRECT,
            cwd=CWD_CORRECT,
        )

    def test_no_collision_is_move(self, tmp_path):
        d = self._drifted(tmp_path)
        item = classify_drift(d, tmp_path)
        assert item.action == DriftAction.MOVE
        assert item.target_path == tmp_path / PROJ_CORRECT / U1

    def test_identical_size_collision_is_dedupe(self, tmp_path):
        d = self._drifted(tmp_path)
        # Create a byte-equal JSONL in the correct folder.
        _make_session(tmp_path, PROJ_CORRECT, U1, CWD_CORRECT)
        item = classify_drift(d, tmp_path)
        assert item.action == DriftAction.DEDUPE_IDENTICAL

    def test_differing_content_collision_is_conflict(self, tmp_path):
        d = self._drifted(tmp_path)
        # Same UUID exists in correct folder but with a bigger/different JSONL.
        other = tmp_path / PROJ_CORRECT / U1
        other.mkdir(parents=True)
        (other / f"{U1}.jsonl").write_text(
            f'{{"type":"user","cwd":"{CWD_CORRECT}","message":{{}}}}\n'
            f'{{"type":"assistant","cwd":"{CWD_CORRECT}","message":{{}}}}\n'
        )
        item = classify_drift(d, tmp_path)
        assert item.action == DriftAction.CONFLICT


# ---- execute_drift_plan ----


class TestExecuteDriftPlan:
    def _plan_one(self, tmp_path) -> list[DriftPlanItem]:
        d = DriftedSession(
            uuid_dir=_make_session(tmp_path, PROJ_WRONG, U1, CWD_CORRECT),
            current_project=PROJ_WRONG,
            correct_project=PROJ_CORRECT,
            cwd=CWD_CORRECT,
        )
        return [classify_drift(d, tmp_path)]

    def test_dry_run_makes_no_filesystem_changes(self, tmp_path):
        plan = self._plan_one(tmp_path)
        report = execute_drift_plan(plan, tmp_path, dry_run=True)
        assert report.moved == 0
        assert report.deduped == 0
        assert (tmp_path / PROJ_WRONG / U1).exists()
        assert not (tmp_path / PROJ_CORRECT / U1).exists()
        assert not (tmp_path / "_DELETE").exists()

    def test_move_relocates_session_to_correct_project(self, tmp_path):
        plan = self._plan_one(tmp_path)
        report = execute_drift_plan(plan, tmp_path, dry_run=False)
        assert report.moved == 1
        assert (tmp_path / PROJ_CORRECT / U1 / f"{U1}.jsonl").exists()
        assert not (tmp_path / PROJ_WRONG / U1).exists()

    def test_dedupe_soft_deletes_wrong_copy_keeps_correct(self, tmp_path):
        # Set up an identical-size collision.
        wrong = _make_session(tmp_path, PROJ_WRONG, U1, CWD_CORRECT)
        correct = _make_session(tmp_path, PROJ_CORRECT, U1, CWD_CORRECT)
        d = DriftedSession(
            uuid_dir=wrong,
            current_project=PROJ_WRONG,
            correct_project=PROJ_CORRECT,
            cwd=CWD_CORRECT,
        )
        plan = [classify_drift(d, tmp_path)]
        assert plan[0].action == DriftAction.DEDUPE_IDENTICAL
        report = execute_drift_plan(plan, tmp_path, dry_run=False)
        assert report.deduped == 1
        # Correct copy untouched.
        assert (correct / f"{U1}.jsonl").exists()
        # Wrong copy soft-deleted (somewhere under _DELETE/).
        assert not wrong.exists()
        delete_root = tmp_path / "_DELETE"
        assert delete_root.exists()
        assert any(p.name == U1 for p in delete_root.rglob(U1))

    def test_conflict_leaves_both_intact(self, tmp_path):
        wrong = _make_session(tmp_path, PROJ_WRONG, U1, CWD_CORRECT)
        other = tmp_path / PROJ_CORRECT / U1
        other.mkdir(parents=True)
        (other / f"{U1}.jsonl").write_text(
            f'{{"type":"user","cwd":"{CWD_CORRECT}","message":{{}}}}\n' * 3
        )
        d = DriftedSession(
            uuid_dir=wrong,
            current_project=PROJ_WRONG,
            correct_project=PROJ_CORRECT,
            cwd=CWD_CORRECT,
        )
        plan = [classify_drift(d, tmp_path)]
        assert plan[0].action == DriftAction.CONFLICT
        report = execute_drift_plan(plan, tmp_path, dry_run=False)
        assert report.moved == 0
        assert report.deduped == 0
        assert len(report.conflicts) == 1
        # Both copies still present, untouched.
        assert wrong.exists()
        assert other.exists()

    def test_empty_source_project_soft_deleted_after_drain(self, tmp_path):
        # PROJ_WRONG has only this one session; after move it should be empty,
        # then soft-deleted to _DELETE/.
        plan = self._plan_one(tmp_path)
        execute_drift_plan(plan, tmp_path, dry_run=False)
        assert not (tmp_path / PROJ_WRONG).exists()
        delete_root = tmp_path / "_DELETE"
        assert any(p.name == PROJ_WRONG for p in delete_root.rglob(PROJ_WRONG))

    def test_drain_ignores_dotfiles_like_ds_store(self, tmp_path):
        # macOS .DS_Store at project level must not block drain.
        plan = self._plan_one(tmp_path)
        (tmp_path / PROJ_WRONG / ".DS_Store").write_bytes(b"\x00" * 8)
        (tmp_path / PROJ_WRONG / "index.html").write_text("<html></html>")
        execute_drift_plan(plan, tmp_path, dry_run=False)
        assert not (tmp_path / PROJ_WRONG).exists()

    def test_drains_leftover_empty_projects_from_prior_run(self, tmp_path):
        # No drift to merge, but a stale wrong-name folder is sitting empty
        # (index.html + .DS_Store only). Re-running --merge-drift should drain it
        # — keeps the mode idempotent / recoverable from earlier partial runs.
        empty_proj = tmp_path / PROJ_WRONG
        empty_proj.mkdir()
        (empty_proj / "index.html").write_text("<html></html>")
        (empty_proj / ".DS_Store").write_bytes(b"\x00" * 8)
        # A real, non-empty project must NOT be drained.
        _make_session(tmp_path, PROJ_CORRECT, U1, CWD_CORRECT)

        report = execute_drift_plan([], tmp_path, dry_run=False)
        assert not empty_proj.exists()
        assert any(
            p.name == PROJ_WRONG for p in (tmp_path / "_DELETE").rglob(PROJ_WRONG)
        )
        assert (tmp_path / PROJ_CORRECT / U1).exists()  # real project untouched

    def test_partial_drain_leaves_remaining_sessions_in_place(self, tmp_path):
        # Drift one session out, but a sibling under PROJ_WRONG genuinely belongs
        # there (its cwd derives to PROJ_WRONG). Folder must stay.
        _make_session(tmp_path, PROJ_WRONG, U1, CWD_CORRECT)  # drifted out
        good_cwd = "/Users/test/CODE/Owner/claude-transcripts"  # derives to PROJ_WRONG
        keeper = _make_session(tmp_path, PROJ_WRONG, U2, good_cwd)
        drifted, _ = find_drifted_sessions(tmp_path)
        plan = [classify_drift(d, tmp_path) for d in drifted]
        execute_drift_plan(plan, tmp_path, dry_run=False)
        assert keeper.exists()
        assert (tmp_path / PROJ_WRONG).exists()


# ---- format_drift_plan ----


class TestFormatDriftPlan:
    def test_summarizes_counts_and_target_projects(self, tmp_path):
        d1 = DriftedSession(
            _make_session(tmp_path, PROJ_WRONG, U1, CWD_CORRECT),
            PROJ_WRONG,
            PROJ_CORRECT,
            CWD_CORRECT,
        )
        d2 = DriftedSession(
            _make_session(tmp_path, PROJ_WRONG, U2, CWD_CORRECT),
            PROJ_WRONG,
            PROJ_CORRECT,
            CWD_CORRECT,
        )
        # Make d2 collide identically in correct folder.
        _make_session(tmp_path, PROJ_CORRECT, U2, CWD_CORRECT)
        plan = [classify_drift(d1, tmp_path), classify_drift(d2, tmp_path)]
        out = format_drift_plan(plan, skipped=[])
        assert PROJ_WRONG in out
        assert PROJ_CORRECT in out
        assert "move" in out.lower()
        assert "dedupe" in out.lower() or "identical" in out.lower()

    def test_lists_conflicts_explicitly(self, tmp_path):
        wrong = _make_session(tmp_path, PROJ_WRONG, U1, CWD_CORRECT)
        other = tmp_path / PROJ_CORRECT / U1
        other.mkdir(parents=True)
        (other / f"{U1}.jsonl").write_text("x" * 100)
        d = DriftedSession(wrong, PROJ_WRONG, PROJ_CORRECT, CWD_CORRECT)
        plan = [classify_drift(d, tmp_path)]
        out = format_drift_plan(plan, skipped=[])
        assert "conflict" in out.lower()
        assert U1 in out


# ---- CLI integration via main() ----


class TestMainMergeDriftFlag:
    def _drifted_archive(self, tmp_path):
        _make_session(tmp_path, PROJ_WRONG, U1, CWD_CORRECT)  # unique to wrong
        _make_session(tmp_path, PROJ_CORRECT, U2, CWD_CORRECT)  # already correct

    def test_flag_absent_skips_drift_mode(self, tmp_path, capsys):
        self._drifted_archive(tmp_path)
        main(["--dry-run", "--yes", str(tmp_path)])
        out = capsys.readouterr().out
        # Use markers that only appear in the drift section (not in tmp_path
        # names, which pytest derives from the test function name).
        assert "Scanning for drifted" not in out
        assert "Drifted-folder merge plan" not in out
        # Drifted session not moved.
        assert (tmp_path / PROJ_WRONG / U1).exists()

    def test_dry_run_with_merge_drift_prints_plan_no_changes(self, tmp_path, capsys):
        self._drifted_archive(tmp_path)
        main(["--merge-drift", "--dry-run", "--yes", str(tmp_path)])
        out = capsys.readouterr().out
        assert "Scanning for drifted" in out
        assert "Drifted-folder merge plan" in out
        assert (tmp_path / PROJ_WRONG / U1).exists()  # not moved

    def test_apply_with_merge_drift_executes_moves(self, tmp_path, capsys):
        self._drifted_archive(tmp_path)
        main(["--merge-drift", "--yes", str(tmp_path)])
        # The unique drifted session should now be in the correct folder.
        assert (tmp_path / PROJ_CORRECT / U1 / f"{U1}.jsonl").exists()
        assert not (tmp_path / PROJ_WRONG / U1).exists()

    def test_apply_drains_leftover_empties_even_with_no_drift(self, tmp_path, capsys):
        # No drifted sessions, but an empty wrong-name folder is leftover from a
        # prior incomplete run. --merge-drift apply must still drain it.
        _make_session(tmp_path, PROJ_CORRECT, U1, CWD_CORRECT)
        leftover = tmp_path / PROJ_WRONG
        leftover.mkdir()
        (leftover / "index.html").write_text("<html></html>")
        (leftover / ".DS_Store").write_bytes(b"\x00" * 8)

        main(["--merge-drift", "--yes", str(tmp_path)])

        out = capsys.readouterr().out
        assert "Empty project folders to drain" in out
        assert not leftover.exists()
        assert any(
            p.name == PROJ_WRONG for p in (tmp_path / "_DELETE").rglob(PROJ_WRONG)
        )
        # Real project untouched.
        assert (tmp_path / PROJ_CORRECT / U1).exists()

    def test_dry_run_previews_leftover_empties(self, tmp_path, capsys):
        _make_session(tmp_path, PROJ_CORRECT, U1, CWD_CORRECT)
        leftover = tmp_path / PROJ_WRONG
        leftover.mkdir()
        (leftover / "index.html").write_text("<html></html>")

        main(["--merge-drift", "--dry-run", "--yes", str(tmp_path)])

        out = capsys.readouterr().out
        assert "Empty project folders to drain" in out
        assert PROJ_WRONG in out
        # Nothing actually moved.
        assert leftover.exists()
