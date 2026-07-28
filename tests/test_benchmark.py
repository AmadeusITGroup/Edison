from collections.abc import Callable, Iterator
from typing import Any

import pytest

from edison.parser import BaseParser
from edison.envelope import (
    EnvelopeFooters,
    EnvelopeHeaders,
    extract_envelope_footers,
    extract_envelope_headers,
)
from edison.tokenizer import (
    tokenize_segments,
    tokenize_segments_iter,
    tokenize_segments_with_blb,
)

TOKENIZERS = [
    pytest.param(tokenize_segments, id="tokenize_segments"),
    pytest.param(tokenize_segments_iter, id="tokenize_segments_iter"),
    pytest.param(tokenize_segments_with_blb, id="tokenize_segments_with_blb"),
]

EDI = "".join(
    (
        f"SEG{i % 10}+FIELD:VALUE+USER\\'DATA'"
        if i % 10 == 0
        else f"SEG{i % 10}+FIELD:VALUE'"
    )
    for i in range(1_000)
)
SEGMENT_COUNT = 1_000
ENVELOPED_EDI = f"UNB+SENDER+RECEIVER'UNH+1+PIZZAQ:1:1:1A'{EDI}UNT+1002+1'UNZ+1+1'"
ENVELOPE_HEADERS = EnvelopeHeaders(
    unb="UNB+SENDER+RECEIVER",
    unh="UNH+1+PIZZAQ:1:1:1A",
)
ENVELOPE_FOOTERS = EnvelopeFooters(
    unt="UNT+1002+1",
    unz="UNZ+1+1",
)


class CompilationBenchmarkParser(BaseParser):
    header = [["UNH"]]
    footer = [["UNT"]]
    schemas = {
        (0, 0): [[f"S{i:03}"] for i in range(200)],
        (1, 0): [
            [
                f"G{i:03}",
                [[f"C{i:03}_{j:03}"] for j in range(5)],
            ]
            for i in range(40)
        ],
    }


@pytest.mark.parametrize("tokenizer", TOKENIZERS)
@pytest.mark.benchmark(group="tokenizers")
def test_tokenizer_performance(
    benchmark: Any,
    tokenizer: Callable[[str], Iterator[str]],
) -> None:
    segments = benchmark.pedantic(
        lambda: list(tokenizer(EDI)),
        rounds=25,
        iterations=1,
    )

    assert len(segments) == SEGMENT_COUNT


@pytest.mark.benchmark(group="envelope")
def test_envelope_header_extraction_performance(benchmark: Any) -> None:
    segments = benchmark.pedantic(
        lambda: extract_envelope_headers(ENVELOPED_EDI),
        rounds=25,
        iterations=1,
    )

    assert segments == ENVELOPE_HEADERS


@pytest.mark.benchmark(group="envelope")
def test_envelope_footer_extraction_performance(benchmark: Any) -> None:
    segments = benchmark.pedantic(
        lambda: extract_envelope_footers(ENVELOPED_EDI),
        rounds=25,
        iterations=1,
    )

    assert segments == ENVELOPE_FOOTERS


@pytest.mark.benchmark(group="schemas")
def test_schema_compilation_performance(benchmark: Any) -> None:
    benchmark.pedantic(
        CompilationBenchmarkParser.compile,
        rounds=25,
        iterations=1,
    )

    assert len(CompilationBenchmarkParser._compiled_schemas) == 2
