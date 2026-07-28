#!/usr/bin/env python

import logging
from typing import NamedTuple

from .tokenizer import tokenize_segments_iter

log = logging.getLogger(__name__)

__all__ = [
    "EnvelopeFooters",
    "EnvelopeHeaders",
    "extract_envelope_footers",
    "extract_envelope_headers",
]


class EnvelopeHeaders(NamedTuple):
    unb: str | None = None
    unh: str | None = None


class EnvelopeFooters(NamedTuple):
    unt: str | None = None
    unz: str | None = None


def extract_envelope_headers(edi: str) -> EnvelopeHeaders:
    r"""Extract EDIFACT envelope headers from the beginning of a message.

    This uses the iterative tokenizer from the start and stops as soon as the
    message header boundary is found.

    >>> extract_envelope_headers("UNB+1'UNH+2+ORDERS:D:96A:UN'BGM'")
    EnvelopeHeaders(unb='UNB+1', unh='UNH+2+ORDERS:D:96A:UN')
    """
    unb = unh = None

    for segment in tokenize_segments_iter(edi):
        tag = segment[:3]
        if tag == "UNB" and unb is None:
            unb = segment
        elif tag == "UNH":
            unh = segment
            break

    return EnvelopeHeaders(unb, unh)


def extract_envelope_footers(edi: str) -> EnvelopeFooters:
    r"""Extract EDIFACT envelope footers from the end of a message.

    This uses the iterative tokenizer from the end and stops as soon as the
    message footer boundary is found.

    >>> extract_envelope_footers("BGM'UNT+3'UNZ+4'")
    EnvelopeFooters(unt='UNT+3', unz='UNZ+4')
    """
    unt = unz = None

    for segment in tokenize_segments_iter(edi, reverse=True):
        tag = segment[:3]
        if tag == "UNZ" and unz is None:
            unz = segment
        elif tag == "UNT":
            unt = segment
            break

    return EnvelopeFooters(unt, unz)
