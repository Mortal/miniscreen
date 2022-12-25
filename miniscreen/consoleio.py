# SPDX-License-Identifier: GPL-3.0-only
from .consolestreaming import parse_one_keystroke
from .unicodeio import wait_stdin_read1


def read_one_keystroke(
    timeout: float | None, extra_timeout: float | None = 0.1, fd=0
) -> str:
    "Read exactly one Linux console keystroke from stdin"
    return parse_one_keystroke(
        wait_stdin_read1(timeout, fd=fd), lambda: wait_stdin_read1(extra_timeout, fd=fd)
    )
