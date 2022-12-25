# SPDX-License-Identifier: GPL-3.0-only
def parse_one_character(first_byte: bytes, get_next_byte) -> str:
    "Parse one UTF-8 character from first byte and a callable to get more bytes"
    assert len(first_byte) == 1
    b = first_byte
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError as e:
        if e.reason != "unexpected end of data":
            raise
    for i in range(10):
        bb = get_next_byte()
        if not bb:
            # Just bubble up the UnicodeDecodeError
            return b.decode("utf-8")
        assert len(bb) == 1
        b += bb
        try:
            return b.decode("utf-8")
        except UnicodeDecodeError as e:
            if e.reason != "unexpected end of data":
                raise
    # Just bubble up the UnicodeDecodeError
    return b.decode("utf-8")
