# SPDX-License-Identifier: GPL-3.0-only
def parse_one_keystroke(first_char: str, get_next_char) -> str:
    "Parse one Linux console keystroke using rules from console_codes(4)"
    s = first_char
    assert len(s) == 1
    codes = {
        "\x01": "CTRL-A",
        "\x02": "CTRL-B",
        "\x03": "CTRL-C",
        "\x04": "CTRL-D",
        "\x05": "CTRL-E",
        "\x06": "CTRL-F",
        "\x07": "CTRL-G",
        "\x08": "CTRL-H",
        "\t": "tab",
        "\n": "newline",
        "\x0B": "CTRL-K",
        "\x0C": "CTRL-L",
        "\r": "return",
        "\x0E": "CTRL-N",
        "\x0F": "CTRL-O",
        "\x10": "CTRL-P",
        "\x11": "CTRL-Q",
        "\x12": "CTRL-R",
        "\x13": "CTRL-S",
        "\x14": "CTRL-T",
        "\x15": "CTRL-U",
        "\x16": "CTRL-V",
        "\x17": "CTRL-W",
        "\x18": "CTRL-X",
        "\x19": "CTRL-Y",
        "\x1A": "CTRL-Z",
        "\x7f": "backspace",
    }
    esccodes = {
        "\x7f": "ALT-backspace",
    }
    altocodes = {
        "P": "F1",
        "Q": "F2",
        "R": "F3",
        "S": "F4",
    }
    csicodes = {
        "A": "uparrow",
        "B": "downarrow",
        "C": "rightarrow",
        "D": "leftarrow",
        "F": "end",
        "H": "home",
        "2~": "insert",
        "3~": "delete",
        "5~": "pageup",
        "6~": "pagedown",
        "15~": "F5",
        "17~": "F6",
        "18~": "F7",
        "19~": "F8",
        "20~": "F9",
        "22~": "F10",
        "23~": "F11",
        "24~": "F12",
        "15;2~": "SHIFT-F5",
        "17;2~": "SHIFT-F6",
        "18;2~": "SHIFT-F7",
        "19;2~": "SHIFT-F8",
        "20;2~": "SHIFT-F9",
        "22;2~": "SHIFT-F10",
        "23;2~": "SHIFT-F11",
        "24;2~": "SHIFT-F12",
        "15;5~": "CTRL-F5",
        "17;5~": "CTRL-F6",
        "18;5~": "CTRL-F7",
        "19;5~": "CTRL-F8",
        "20;5~": "CTRL-F9",
        "21;5~": "CTRL-F10",
        "23;5~": "CTRL-F11",
        "24;5~": "CTRL-F12",
        "15;3~": "ALT-F5",
        "17;3~": "ALT-F6",
        "18;3~": "ALT-F7",
        "19;3~": "ALT-F8",
        "20;3~": "ALT-F9",
        "21;3~": "ALT-F10",
        "23;3~": "ALT-F11",
        "24;3~": "ALT-F12",
        "15;4~": "ALT-SHIFT-F5",
        "17;4~": "ALT-SHIFT-F6",
        "18;4~": "ALT-SHIFT-F7",
        "19;4~": "ALT-SHIFT-F8",
        "20;4~": "ALT-SHIFT-F9",
        "21;4~": "ALT-SHIFT-F10",
        "23;4~": "ALT-SHIFT-F11",
        "24;4~": "ALT-SHIFT-F12",
        "15;8~": "CTRL-ALT-SHIFT-F5",
        "17;8~": "CTRL-ALT-SHIFT-F6",
        "18;8~": "CTRL-ALT-SHIFT-F7",
        "19;8~": "CTRL-ALT-SHIFT-F8",
        "20;8~": "CTRL-ALT-SHIFT-F9",
        "21;8~": "CTRL-ALT-SHIFT-F10",
        "23;8~": "CTRL-ALT-SHIFT-F11",
        "24;8~": "CTRL-ALT-SHIFT-F12",
        "5;3~": "ALT-pageup",
        "6;3~": "ALT-pagedown",
        "5;7~": "CTRL-ALT-pageup",
        "6;7~": "CTRL-ALT-pagedown",
        "1;2P": "SHIFT-F1",
        "1;2Q": "SHIFT-F2",
        "1;2R": "SHIFT-F3",
        "1;2S": "SHIFT-F4",
        "1;5P": "CTRL-F1",
        "1;5Q": "CTRL-F2",
        "1;5R": "CTRL-F3",
        "1;5S": "CTRL-F4",
        "1;3P": "ALT-F1",
        "1;3Q": "ALT-F2",
        "1;3R": "ALT-F3",
        "1;3S": "ALT-F4",
        "1;4P": "ALT-SHIFT-F1",
        "1;4Q": "ALT-SHIFT-F2",
        "1;4R": "ALT-SHIFT-F3",
        "1;4S": "ALT-SHIFT-F4",
        "1;8P": "CTRL-ALT-SHIFT-F1",
        "1;8Q": "CTRL-ALT-SHIFT-F2",
        "1;8R": "CTRL-ALT-SHIFT-F3",
        "1;8S": "CTRL-ALT-SHIFT-F4",
        "1;6P": "CTRL-ALT-F1",
        "1;6Q": "CTRL-ALT-F2",
        "1;6R": "CTRL-ALT-F3",
        "1;6S": "CTRL-ALT-F4",
        "1;3A": "ALT-uparrow",
        "1;3B": "ALT-downarrow",
        "1;3C": "ALT-rightarrow",
        "1;3D": "ALT-leftarrow",
        "1;3F": "ALT-end",
        "1;3H": "ALT-home",
        "1;5A": "CTRL-uparrow",
        "1;5B": "CTRL-downarrow",
        "1;5C": "CTRL-rightarrow",
        "1;5D": "CTRL-leftarrow",
        "1;5F": "CTRL-end",
        "1;5H": "CTRL-home",
        "1;7F": "CTRL-ALT-end",
        "1;7H": "CTRL-ALT-home",
        "2;3~": "ALT-insert",
        "2;5~": "CTRL-insert",
        "3;2~": "SHIFT-delete",
        "3;3~": "ALT-delete",
        "3;5~": "CTRL-delete",
        "200~": "pastestart",
        "201~": "pasteend",
    }
    o = ord(s)
    if 32 <= o != 127:
        return s
    if s == "\x1b":
        s = get_next_char()
        if s == "":
            return "escape"
        if s == "[":
            s = get_next_char()
            while 0x20 <= ord(s[-1]) < 0x3C:
                ss = get_next_char()
                if not ss:
                    break
                s += ss
            try:
                return csicodes[s]
            except KeyError:
                raise NotImplementedError("Need csicodes entry: %r: ''" % (s,))
        if s == "O":
            s = get_next_char()
            if not s:
                return "ALT-O"
            try:
                return altocodes[s]
            except KeyError:
                raise NotImplementedError("Need altocodes entry: %r: ''" % (s,))
        o = ord(s)
        if 32 <= o < 127 or 255 < o:
            return "ALT-" + s
        try:
            return esccodes[s]
        except KeyError:
            raise NotImplementedError("Need esccodes entry: %r: ''" % (s,))
    try:
        return codes[s]
    except KeyError:
        raise NotImplementedError("Need codes entry: %r: ''" % (s,))
