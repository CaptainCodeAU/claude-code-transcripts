"""Stdlib arrow-key picker: the dependency-free replacement for questionary.select.

Renders an interactive single-select list to the terminal using termios/tty raw
mode. Up/Down (or k/j) move the highlight, Enter selects, and q or Esc cancels.

POSIX-only by design: callers use it for interactive sessions. When stdin is not
a usable interactive terminal (piped/redirected input, or the controlling
terminal has gone away -- termios.tcgetattr raises, which is EIO on Linux and
ENOTTY elsewhere), the picker cancels gracefully by returning None, the same as
an EOF. The terminal is always restored through a try/finally, even when the
body raises. The list is drawn to stderr so stdout stays clean for piping.
"""

import os
import select
import sys
import termios
import tty

_ESC_TIMEOUT = 0.05  # seconds to wait for the rest of an escape sequence


def _render(out, prompt, choices, index, first):
    """Draw (or redraw) the prompt and choice list with `index` highlighted."""
    if not first:
        out.write(f"\x1b[{len(choices) + 1}A")  # move the cursor back up to the prompt
    out.write("\r\x1b[K" + prompt + "\r\n")
    for i, (display, _value) in enumerate(choices):
        line = ("> " if i == index else "  ") + display
        if i == index:
            line = "\x1b[7m" + line + "\x1b[0m"  # reverse video on the current row
        out.write("\r\x1b[K" + line + "\r\n")
    out.flush()


def select_from_list(prompt, choices, stream=None):
    """Show an interactive picker over `choices` (a list of (display, value) pairs).

    Returns the chosen value, or None if the user cancels (q / Esc / EOF).
    Raises KeyboardInterrupt on Ctrl-C, after restoring the terminal.
    """
    if not choices:
        return None
    in_stream = stream if stream is not None else sys.stdin
    fd = in_stream.fileno()
    out = sys.stderr
    try:
        old_attrs = termios.tcgetattr(fd)
    except (termios.error, OSError):
        # Not a usable interactive terminal: piped/redirected stdin, or the
        # controlling terminal has gone away (a closed pty master surfaces as
        # EIO on Linux, ENOTTY elsewhere). Treat it like EOF and cancel
        # gracefully instead of letting termios.error escape to the caller.
        return None
    index = 0
    try:
        # TCSANOW (not the setraw default TCSAFLUSH) so we do not discard any
        # keystrokes the user already typed ahead before the picker opened.
        tty.setraw(fd, termios.TCSANOW)
        _render(out, prompt, choices, index, first=True)
        while True:
            try:
                ch = os.read(fd, 1)
            except OSError:
                return None  # terminal went away (e.g. master closed) -> cancel
            if not ch:
                return None  # EOF / closed input -> cancel
            if ch in (b"\r", b"\n"):
                return choices[index][1]
            if ch == b"\x03":  # Ctrl-C
                raise KeyboardInterrupt
            if ch in (b"q", b"Q"):
                return None
            if ch == b"k":
                index = (index - 1) % len(choices)
                _render(out, prompt, choices, index, first=False)
            elif ch == b"j":
                index = (index + 1) % len(choices)
                _render(out, prompt, choices, index, first=False)
            elif ch == b"\x1b":
                ready, _, _ = select.select([fd], [], [], _ESC_TIMEOUT)
                if not ready:
                    return None  # lone Esc -> cancel
                seq = os.read(fd, 2)
                if seq == b"[A":
                    index = (index - 1) % len(choices)
                    _render(out, prompt, choices, index, first=False)
                elif seq == b"[B":
                    index = (index + 1) % len(choices)
                    _render(out, prompt, choices, index, first=False)
                else:
                    return None  # unrecognized escape -> cancel
    finally:
        # TCSANOW (not TCSADRAIN): restore immediately without waiting for the
        # input fd's output queue to drain. Our rendered output went to stderr
        # and was already flushed, and TCSADRAIN would block if the terminal's
        # output sink ever stalls.
        termios.tcsetattr(fd, termios.TCSANOW, old_attrs)
        out.write("\r\n")
        out.flush()
