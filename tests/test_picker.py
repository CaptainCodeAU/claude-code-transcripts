"""Tests for the stdlib arrow-key picker (the questionary.select replacement).

The picker drives a real terminal via termios/tty, so these tests exercise it
through a pseudo-terminal (pty): we pre-load the picker's input by writing the
key bytes to the pty master, then run select_from_list against the slave fd.
"""

import os
import pty
import termios
import tty

import pytest

from claude_code_transcripts.picker import select_from_list


class _PtyStdin:
    """A minimal stdin stand-in backed by a real pty slave fd."""

    def __init__(self, fd):
        self._fd = fd

    def fileno(self):
        return self._fd


CHOICES = [("first", "A"), ("second", "B"), ("third", "C")]


def _lflag_masked(attrs):
    """Copy of a termios array with the volatile PENDIN lflag bit cleared.

    PENDIN ("input pending re-read") gets set transiently while a tty has
    unread input, so it is not meaningful for an equality comparison of the
    saved-vs-restored terminal state.
    """
    masked = list(attrs)
    masked[3] = masked[3] & ~termios.PENDIN
    return masked


def _run_with_input(input_bytes, choices=CHOICES):
    """Feed input_bytes through a pty and run the picker against it."""
    master, slave = pty.openpty()
    try:
        os.write(master, input_bytes)
        return select_from_list("Select:", choices, stream=_PtyStdin(slave))
    finally:
        os.close(master)
        os.close(slave)


def test_enter_selects_highlighted_first():
    assert _run_with_input(b"\r") == "A"


def test_newline_also_selects():
    assert _run_with_input(b"\n") == "A"


def test_arrow_down_then_enter_selects_second():
    assert _run_with_input(b"\x1b[B\r") == "B"


def test_two_downs_select_third():
    assert _run_with_input(b"\x1b[B\x1b[B\r") == "C"


def test_arrow_up_wraps_to_last():
    assert _run_with_input(b"\x1b[A\r") == "C"


def test_down_wraps_around_to_first():
    assert _run_with_input(b"\x1b[B\x1b[B\x1b[B\r") == "A"


def test_vim_keys_navigate():
    # j moves down, k moves up
    assert _run_with_input(b"jj\r") == "C"
    assert _run_with_input(b"k\r") == "C"


def test_q_cancels_returns_none():
    assert _run_with_input(b"q") is None


def test_lone_esc_cancels_returns_none():
    assert _run_with_input(b"\x1b") is None


def test_eof_cancels_returns_none():
    # Closed input (no bytes) must not spin forever; it cancels.
    master, slave = pty.openpty()
    try:
        os.close(master)  # EOF on the slave
        assert select_from_list("Select:", CHOICES, stream=_PtyStdin(slave)) is None
    finally:
        os.close(slave)


def test_empty_choices_returns_none():
    # Guard runs before any terminal access, so no stream is needed.
    assert select_from_list("Select:", []) is None


def test_terminal_restored_after_normal_selection():
    master, slave = pty.openpty()
    try:
        os.write(master, b"\r")
        # Pin a known cooked baseline at the picker's entry point so the restore
        # assertion is deterministic regardless of pty defaults in the wider run.
        cooked = termios.tcgetattr(slave)
        cooked[3] |= termios.ICANON | termios.ECHO | termios.ISIG
        termios.tcsetattr(slave, termios.TCSANOW, cooked)
        before = termios.tcgetattr(slave)
        select_from_list("Select:", CHOICES, stream=_PtyStdin(slave))
        after = termios.tcgetattr(slave)
        assert _lflag_masked(after) == _lflag_masked(before)  # restored to entry state
        assert after[3] & termios.ICANON  # canonical mode restored (not left raw)
        assert after[3] & termios.ECHO  # echo restored

    finally:
        os.close(master)
        os.close(slave)


def test_ctrl_c_raises_and_restores_terminal():
    master, slave = pty.openpty()
    try:
        tty.setraw(slave)  # so Ctrl-C arrives as a byte, not a SIGINT
        before = termios.tcgetattr(slave)
        os.write(master, b"\x03")
        with pytest.raises(KeyboardInterrupt):
            select_from_list("Select:", CHOICES, stream=_PtyStdin(slave))
        after = termios.tcgetattr(slave)
        # finally-block restore runs even on exception (PENDIN is volatile)
        assert _lflag_masked(after) == _lflag_masked(before)
    finally:
        os.close(master)
        os.close(slave)
