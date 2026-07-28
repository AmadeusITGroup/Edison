#!/usr/bin/env python

import re
import logging
from collections.abc import Iterator
import platform

PYPY = platform.python_implementation() == "PyPy"

log = logging.getLogger(__name__)

__all__ = [
    "translate_ebcdic_separators",
    "normalize_ebcdic_separators",
    "escape",
    "unescape",
    "tokenize_segments",
    "tokenize_segments_iter",
    "tokenize_segments_with_blb",
]


# EBCDIC/ESCAPING CORNER
#
# Note that the backslash itself is not escaped, as in practice
# this character never appears in messages. If it ever does, it
# will only be an issue if it is just before an EBCDIC symbol, in
# that case the symbol will look like it is escaped, and this can
# mess up the parsing. This is most likely never going to happen.

ASCII_SYMBOLS = "+:*'"
EBCDIC_SYMBOLS = "\x1d\x1f\x19\x1c"

TABLE_FORMAT = str.maketrans(EBCDIC_SYMBOLS, ASCII_SYMBOLS)
TABLE_ESC = [(a, f"\\{a}") for a in ASCII_SYMBOLS]

_RE_FIND_ESCAPED = re.compile(rb"\\[+:*']")
_RE_SUB_ESCAPED = re.compile(r"\\([+:*'])")

# This will be used on a memoryview, where find() is not possible
_RE_QUOTE_B = re.compile(rb"'")


def translate_ebcdic_separators(edi: str) -> str:
    r"""Converts EBCDIC symbols to ASCII, with no escaping.

    >>> translate_ebcdic_separators("ORG\x1D00\x1C")
    "ORG+00'"
    """
    return edi.translate(TABLE_FORMAT)


def normalize_ebcdic_separators(edi: str, scan_limit: int = 100) -> str:
    r"""Converts EBCDIC symbols to ASCII, with escaping if necessary.

    We only look for EBCDIC symbols in the first hundred characters
    for performance reasons, as on very large strings it adds up.

    If already converted, this function is no-op.

    >>> normalize_ebcdic_separators("UNB\x1DSENDER\x1FREC")
    'UNB+SENDER:REC'
    >>> normalize_ebcdic_separators("UNB\x1DSENDER\x1FREC+\x1C")  # escaping
    "UNB+SENDER:REC\\+'"
    >>> normalize_ebcdic_separators(r"UNB+SENDER:REC\+'")  # no-op
    "UNB+SENDER:REC\\+'"
    """
    if edi.find("\x1d", 0, scan_limit) == -1:  # not found
        return edi
    return translate_ebcdic_separators(escape(edi))


def escape(data: str) -> str:
    r"""Escaping ASCII symbols that are used as EBCDIC control characters.

    This function is typically used right before generating EDIFACT or XML,
    to make sure there is a difference between control characters and true
    content that happens to be +:*'.

    Escaping is basically a re.sub(r"([+:*'])", r"\\\1", data), but it is
    actually faster to do repeated replace().

    >>> escape("REC+")
    'REC\\+'
    """
    for c, ec in TABLE_ESC:
        data = data.replace(c, ec)
    return data


def unescape(
    data: str,
    _re_escaped: re.Pattern[str] = _RE_SUB_ESCAPED,
) -> str:
    r"""Unescaping is the opposite of escaping: removing backslash where relevant.

    This function is typically used right after parsing the EDIFACT content,
    where we want to get rid of the escaping backslashes that were useful
    when tokenizing the segments.

    Unescaping is basically a re.sub(r"\\([+:*'])", r"\1", data), but on PyPy
    it is faster to do repeated replace().
    And if Unicode characters are involved, then PyPy has a bug (#4028) where
    the performance is completely broken using regular expressions.

    >>> unescape(r"REC\+")
    'REC+'
    """
    if not PYPY:
        return _re_escaped.sub(r"\1", data)

    for c, ec in TABLE_ESC:
        data = data.replace(ec, c)
    return data


# SEGMENTS TOKENIZING
#
_EOL = "& \t\r\n"
_EOL_ORD = frozenset(_EOL.encode())


def tokenize_segments(edi: str) -> Iterator[str]:
    r"""Tokenizer of EDIFACT segments.

    The only trick here is to split on quotes, but not if they were escaped
    with a backslash. For this we first replace escaped quotes but a special
    character, then we split normally on quotes.

    This is basically a re.split(r'(?<!\\)"', edi), but it is actually faster.

    >>> list(tokenize_segments(r"ERC'IFT+1+USER\'DATA'"))
    ['ERC', "IFT+1+USER\\'DATA"]
    >>> list(tokenize_segments("SDI'SPI+'UNZ'TRUNC"))
    ['SDI', 'SPI+', 'UNZ']
    """
    edi = normalize_ebcdic_separators(edi)

    segments = edi.replace(r"\'", "\x1a").split("'")
    segments.pop()  # remove the last empty segment after the last quote
    for segment in segments:
        yield segment.replace("\x1a", r"\'").lstrip(_EOL)


def tokenize_segments_iter(
    edi: str,
    reverse: bool = False,
) -> Iterator[str]:
    r"""Tokenizer of EDIFACT segments, the iterator version.

    This is the iterator version of the normal tokenizer, in the sense that it
    lazily yields segments without processing the whole string. It is used to
    parse EDIFACT headers, where you only care about the first segments.
    This is not the default tokenizer as it is 2-3x slower than the normal version,
    if you use it to tokenize the full message. But it is 2-15x faster to use this
    version if you just want the first segments, depending on message size.

    Note that we exclude manually the escaped quotes, we could do it using a
    lookbehind clause with a regular expression, but it is a bit slower.

    We support a reverse mode to tokenize from the end of the EDI, this is useful
    when testing for truncation.

    >>> # Same tests as tokenize_segments
    >>> list(tokenize_segments_iter(r"ERC'IFT+1+USER\'DATA'"))
    ['ERC', "IFT+1+USER\\'DATA"]
    >>> list(tokenize_segments_iter("SDI'SPI+'UNZ'TRUNC"))
    ['SDI', 'SPI+', 'UNZ']
    >>>
    >>> # The reverse mode that starts from the end
    >>> list(tokenize_segments_iter(r"ERC'IFT+1+USER\'DATA'", reverse=True))
    ["IFT+1+USER\\'DATA", 'ERC']
    >>> list(tokenize_segments_iter("SDI'SPI+'UNZ'TRUNC", reverse=True))
    ['UNZ', 'SPI+', 'SDI']
    """
    edi = normalize_ebcdic_separators(edi)

    if not reverse:
        # * find_start_index is the index for the beginning of the find()
        # * start_index is the index for the beginning of the segment
        find_start_index = start_index = 0
        while True:
            index = edi.find("'", find_start_index)
            if index == -1:  # between the last quote and the end
                return
            if index == 0 or edi[index - 1] != "\\":
                yield edi[start_index:index].lstrip(_EOL)
                start_index = index + 1
            find_start_index = index + 1
    else:
        # * rfind_end_index is the index for the end of the rfind()
        # * end_index is the index for the end of the segment
        # We use those end indices "plus one" as we use them for slicing.
        rfind_end_index_plus_one = end_index_plus_one = edi_len = len(edi)
        while True:
            index = edi.rfind("'", 0, rfind_end_index_plus_one)
            if index == -1:
                if end_index_plus_one < edi_len:  # before last quote
                    yield edi[:end_index_plus_one].lstrip(_EOL)
                return
            if index == 0 or edi[index - 1] != "\\":
                if end_index_plus_one < edi_len:  # before last quote
                    yield edi[index + 1 : end_index_plus_one].lstrip(_EOL)
                end_index_plus_one = index
            rfind_end_index_plus_one = index


def tokenize_segments_with_blb(
    edi: str,
    _re_quote: re.Pattern[bytes] = _RE_QUOTE_B,
) -> Iterator[str]:
    r"""Tokenizer of EDIFACT segments, handling BLB segments as well.

    Note that this tokenizer could be used everywhere instead of tokenize_segments,
    but it 10x slower. This version understands that BLB segments may contain
    quotes, so we cannot just tokenize on them. When finding a BLB segment, it will
    read the number of bytes specified, and basically "jump over" it.

    >>> list(tokenize_segments_with_blb("BLB+8++EQN'PTK''"))
    ["BLB+8++EQN'PTK'"]
    >>> list(tokenize_segments_with_blb("BLB+8++EQN'PTK''UNT'"))
    ["BLB+8++EQN'PTK'", 'UNT']
    >>> list(tokenize_segments_with_blb("BLB'AAA'"))
    ['BLB', 'AAA']
    >>>
    >>> # Even though the BLB count is 0, the BLB extends until a quote is found
    >>> list(tokenize_segments_with_blb("UNH'BLB+0++<xml>A</xml>'UNT'"))
    ['UNH', 'BLB+0++<xml>A</xml>', 'UNT']
    >>>
    >>> # Quotes are jumped over, because of the BLB count
    >>> list(tokenize_segments_with_blb("UNH'BLB+26++<xml>Quotes''inside'</xml>'UNT'"))
    ['UNH', "BLB+26++<xml>Quotes''inside'</xml>", 'UNT']
    >>>
    >>> # Escaped characters (not normal backslashes) are excluded from the BLB count
    >>> for s in tokenize_segments_with_blb(r"UNH'BLB+2++1\''BLB+2++\\:'UNT'"):
    ...     print(s)
    UNH
    BLB+2++1\'
    BLB+2++\\:
    UNT
    >>>
    >>> # Unicode characters are counted as their bytes length
    >>> list(tokenize_segments_with_blb("UNH'BLB+11++TRADEMARK®'UNT'"))
    ['UNH', 'BLB+11++TRADEMARK®', 'UNT']
    """
    edi = normalize_ebcdic_separators(edi)

    # The BLB length is given in bytes, so to perform the BLB extraction properly,
    # we need to convert the EDI to bytes(). In this context, every character is
    # actually an int, so comparisons are done against their ASCII numbers via ord().
    edi_as_bytes = edi.encode()

    # The additional memoryview() is to avoid copying the data when slicing, before
    # converting to str(). It is a bit faster and reduces memory consumption for large
    # messages, but then we cannot use view.find(b"'"), and rely on a regex instead.
    view = memoryview(edi_as_bytes)

    index, edi_len = 0, len(view)

    while index < edi_len:
        while index < edi_len and view[index] in _EOL_ORD:  # skip over EOL, if any
            index += 1

        if view[index : index + 3].tobytes() == b"BLB":  # BLB+270++BLOB
            minimum_end_index = _get_blb_end_index(view, index, edi_len)
        else:
            minimum_end_index = index + 3

        # We now look for a true quote, one that is not coming after a backslash:
        # * if we find one, we yield the segment and move the index further
        # * if we never find one, it means the segment is truncated and we exit
        for match in _re_quote.finditer(view, pos=minimum_end_index):
            quote_index = match.start()
            if quote_index == 0 or view[quote_index - 1] != 92:  # ord("\\")
                yield str(view[index:quote_index], "utf8")
                index = quote_index + 1
                break
        else:
            break

    # We do not return the last truncated segment unless it is a BLB, in that case
    # the parser of the BLB should exclude its own last truncated segment
    if view[index : index + 3].tobytes() == b"BLB":
        yield str(view[index:], "utf8")


def _get_blb_end_index(
    view: memoryview,
    index: int,
    edi_len: int,
    _re_escaped: re.Pattern[bytes] = _RE_FIND_ESCAPED,
) -> int:
    r"""Compute the minimum possible index of the end of BLB.

    From a beginning "index", this function returns an integer representing the
    index of the end of BLB. We read the BLB length and compute that index.
    Note that sometimes the BLB will extend further, so we need to find the next
    true quote in the caller.

    >>> _get_blb_end_index(memoryview(b"BLB+3++ABC'UNT'"), 0, 15)
    10
    >>> _get_blb_end_index(memoryview(b"BLB+3++AB\\+'UNT'"), 0, 16)
    11
    >>> _get_blb_end_index(memoryview(b"BLB'"), 0, 4)
    3
    >>> _get_blb_end_index(memoryview(b"BLB+30"), 0, 6)
    6
    >>> _get_blb_end_index(memoryview(b"BLB+30++AAA"), 0, 11)
    38
    >>> _get_blb_end_index(memoryview(b"BLB+COMPUTED++AAA'"), 0, 18)
    16
    >>> _get_blb_end_index(memoryview(b"BLB+ERROR++AAA"), 0, 14)
    11
    """
    # We begin by jumping over the segment name
    index += 3

    # We move the index forward, until the beginning of the actual BLB content
    field_number = 0
    while field_number != 3 and index < edi_len:
        if view[index] == 39:  # ord("'")
            return index
        if view[index] == 43:  # ord("+")
            field_number += 1
            if field_number == 1:
                blb_len_start = index + 1
            elif field_number == 2:
                blb_len_end = index - 1
        index += 1

    # This means the message was probably truncated, because we reached the
    # end of message, despite only trying to move until the beginning of the
    # actual BLB content.
    if index == edi_len:
        return index

    blb_len_view = view[blb_len_start : blb_len_end + 1]

    # This can happen as some test messages have a 'COMPUTED' in place of the
    # length. In that case we return the end of message, as it seems this works
    # best in most cases, meaning the BLB is effectively "running until the end
    # of message".
    # Note that in the general case this is a bad idea: some messages have
    # multiple BLB segments, or other segments after the first BLB.
    # We could also return the current index, and leave it to the caller to
    # extend it until the next true quote, but this is going to cause issues
    # if the BLB itself contains quotes.
    if blb_len_view.tobytes() == b"COMPUTED":
        log.info("BLB length was set to 'COMPUTED', assuming the rest is BLB")
        return edi_len - 2  # penultimate character (last would be the quote)

    try:
        blb_len = int(blb_len_view)
    except ValueError:
        # In that case we return the current index, as we do not want to
        # "go too far" in estimating the BLB end index. The caller will then
        # extend it until the next true quote. Obviously, this is going to
        # cause issues if the BLB itself contains quotes ¯\_(ツ)_/¯
        log.error("Could not parse BLB length from %r", blb_len_view.tobytes())
        return index

    blb_end_index = index + blb_len

    # We have to scan the BLB for potential escaped delimiters:
    # if we find any, we have to increment the BLB end index
    for match in _re_escaped.finditer(view, pos=index):
        # match spans 2 characters and we want match.end() before/at blb_end_index
        if match.start() < blb_end_index:
            blb_end_index += 1
        else:
            break

    return blb_end_index
