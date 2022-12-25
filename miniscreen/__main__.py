# SPDX-License-Identifier: GPL-3.0-only
from .consoleio import read_one_keystroke
from .miniscreen import MiniScreen


def main() -> None:
    with MiniScreen() as screen:
        while True:
            s = read_one_keystroke(None)
            screen.print_line(s)
            if s in ("CTRL-C", "CTRL-D"):
                break


if __name__ == "__main__":
    main()
