# SPDX-License-Identifier: GPL-3.0-only
import os
import select

from .unicodestreaming import parse_one_character


def stdin_read1(fd=0) -> str:
    "Read exactly one UTF-8 character from stdin using the read(2) syscall"
    return parse_one_character(os.read(fd, 1), lambda: os.read(fd, 1))


def wait_stdin_read1(
    timeout: float | None, extra_timeout: float | None = 0.1, fd=0
) -> str:
    "Read exactly one UTF-8 character from stdin with read(2) and select(2)"

    def get_next_byte() -> bytes:
        if timeout is not None:
            a, b, c = select.select([fd], [], [], timeout)
            if not a:
                return b""
        return os.read(fd, 1)

    b = get_next_byte()
    if not b:
        return ""
    # Update the variable "timeout", which is captured in get_next_byte()
    timeout = extra_timeout
    return parse_one_character(b, get_next_byte)
