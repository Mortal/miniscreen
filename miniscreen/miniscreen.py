# SPDX-License-Identifier: GPL-3.0-only
import contextlib
import os
import signal
import sys
import termios
import tty

from .consoleio import read_one_keystroke


class MiniScreen:
    def __init__(self, stdin=0, stdout=sys.stdout) -> None:
        self._stdin = stdin
        self._stdout = stdout

        self._screen_lines: list[str] = []
        self._linebuf = ""
        self._cursor = 0

    @contextlib.contextmanager
    def minimize(self):
        self.cleanup()
        try:
            yield
        finally:
            self.start()

    def minimize_sigstop(self) -> None:
        with self.minimize():
            os.kill(os.getpid(), signal.SIGSTOP)

    def cleanup(self) -> None:
        # Set stdin to cooked mode
        termios.tcsetattr(self._stdin, termios.TCSAFLUSH, self.old)
        del self.old
        # Enable autowrap
        self._stdout.write("\x1b[?7h")
        # Disable bracketed paste
        self._stdout.write("\x1b[?2004l")
        self._stdout.flush()

    def start(self) -> None:
        # Enable bracketed paste
        self._stdout.write("\x1b[?2004h")
        # Disable autowrap
        self._stdout.write("\x1b[?7l")
        # Set stdin to raw mode
        self.old = termios.tcgetattr(self._stdin)
        tty.setraw(self._stdin)
        # Hack: use set_window() to redraw screen_lines+linebuf and flush
        lines = self._screen_lines[:]
        del self._screen_lines[:]
        self.set_window(lines)
        self._stdout.flush()

    def __enter__(self) -> "MiniScreen":
        self.start()
        return self

    def __exit__(self, ext, exv, exb) -> None:
        self.cleanup()

    def __iter__(self) -> "MiniScreen":
        return self

    def __next__(self) -> str:
        s = read_one_keystroke(None, fd=self._stdin)
        if s == "CTRL-D":
            raise StopIteration
        if s == "CTRL-C":
            raise KeyboardInterrupt
        ev = self.handle_keystroke(s)
        if ev is not None:
            return ev
        return s

    def set_line(self, s: str, c: int | None = None) -> None:
        if c is None:
            c = len(s)
        c = max(0, min(c, len(s)))
        self._linebuf = s
        self._stdout.write("\r\x1b[K" + self._linebuf)
        self._cursor = c
        if self._cursor != len(self._linebuf):
            self._stdout.write("\x1b[%sD" % (len(self._linebuf) - self._cursor))
        self._stdout.flush()

    def _move_up(self, nlines: int) -> None:
        if nlines:
            self._stdout.write("\x1b[%sA" % nlines)

    def _move_down(self, nlines: int) -> None:
        if nlines:
            self._stdout.write("\x1b[%sB" % nlines)

    def _insert_line(self) -> None:
        self._stdout.write("\x1b[1L")

    def _print_line_1(self, line: str) -> None:
        self._stdout.write("\r")
        self._move_up(len(self._screen_lines))
        self._insert_line()
        self._stdout.write("%s\r" % (line,))
        self._move_down(len(self._screen_lines))
        self._stdout.write("\n")

    def print_line(self, line: str) -> None:
        self._print_line_1(line)
        if self._cursor != 0:
            self._stdout.write("\x1b[%sD" % self._cursor)
        self._stdout.flush()

    def set_window(self, lines: list[str]) -> None:
        self._move_up(len(self._screen_lines))
        i = 0
        for line in lines:
            if i == 0:
                self._stdout.write("\r")
            if i == len(self._screen_lines):
                self._stdout.write("\x1b[1L")
                self._stdout.write("%s\r\n" % line)
                self._screen_lines.append(line)
                i += 1
            else:
                self._screen_lines[i] = line
                i += 1
                self._stdout.write("\x1b[K%s\r\n" % (line,))
        if i < len(self._screen_lines):
            self._stdout.write("\r\x1b[%sM" % (len(self._screen_lines) - i))
            del self._screen_lines[i:]
        self._stdout.write("\r\x1b[K")
        self._stdout.write(self._linebuf)
        if self._cursor != len(self._linebuf):
            self._stdout.write("\x1b[%sD" % (len(self._linebuf) - self._cursor))
        self._stdout.flush()

    def handle_keystroke(self, s: str) -> str | None:
        if s in ("return", "newline"):
            self._print_line_1(self._linebuf)
            self._linebuf = ""
            self._cursor = 0
            self._stdout.write("\x1b[K")
            self._stdout.flush()
            return "newline"
        elif s == "backspace":
            if self._cursor:
                self._linebuf = (
                    self._linebuf[: self._cursor - 1] + self._linebuf[self._cursor :]
                )
                self._cursor -= 1
                self._stdout.write("\x08\x1b[1P")
                self._stdout.flush()
            return "erase"
        elif len(s) == 1:
            if self._cursor != len(self._linebuf):
                self._stdout.write("\x1b[1@")
            self._linebuf = (
                self._linebuf[: self._cursor] + s + self._linebuf[self._cursor :]
            )
            self._cursor += 1
            self._stdout.write(s)
            self._stdout.flush()
            return "input"
        elif s in ("CTRL-A", "home"):
            self._cursor = 0
            self._stdout.write("\r")
            self._stdout.flush()
            return "arrow"
        elif s in ("CTRL-E", "end"):
            self._cursor = len(self._linebuf)
            self._stdout.write("\r")
            if self._cursor:
                self._stdout.write("\x1b[%sC" % self._cursor)
            self._stdout.flush()
            return "arrow"
        elif s == "CTRL-U":
            self._cursor = 0
            self._linebuf = ""
            self._stdout.write("\r\x1b[K")
            self._stdout.flush()
            return "erase"
        elif s == "ALT-backspace":
            i = self._cursor
            while i > 0 and not self._linebuf[i - 1].isalnum():
                i -= 1
            while i > 0 and self._linebuf[i - 1].isalnum():
                i -= 1
            self._linebuf = self._linebuf[:i] + self._linebuf[self._cursor :]
            self._stdout.write("\x1b[%sD" % (self._cursor - i))
            self._stdout.write("\x1b[%sP" % (self._cursor - i))
            self._cursor = i
            self._stdout.flush()
            return "erase"
        elif s == "CTRL-W":
            i = self._cursor
            while i > 0 and self._linebuf[i - 1].isspace():
                i -= 1
            while i > 0 and not self._linebuf[i - 1].isspace():
                i -= 1
            self._linebuf = self._linebuf[:i] + self._linebuf[self._cursor :]
            self._stdout.write("\x1b[%sD" % (self._cursor - i))
            self._stdout.write("\x1b[%sP" % (self._cursor - i))
            self._cursor = i
            self._stdout.flush()
            return "erase"
        elif s == "leftarrow":
            if self._cursor > 0:
                self._cursor -= 1
                self._stdout.write("\x1b[D")
                self._stdout.flush()
            return "arrow"
        elif s == "rightarrow":
            if self._cursor < len(self._linebuf):
                self._cursor += 1
                self._stdout.write("\x1b[C")
                self._stdout.flush()
            return "arrow"
        return None
