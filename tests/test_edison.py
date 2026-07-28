from collections.abc import Callable, Iterator
from typing import Any
import pytest

from edison.parser import BaseParser, build_transitions, Transition
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


class Parser(BaseParser):
    header = [["UNH", []]]
    footer = [["UNT", []]]
    schemas = {
        (0, 0): [
            ["AAA", []],
            ["BBB", [], None, 1, "C"],
            ["CCC", [], None, 1, "M"],
        ],
    }


# Complex schemas
#
class ComplexParser(BaseParser):
    schemas = {
        (0, 0): [
            #
            # 1 - simple stuff
            #
            ["PTC"],
            [
                "PTK",
                [["COR", [], "increment"]],
            ],
            ["EQN", [], "increment"],
            #
            # 2 - to test segments with same names
            #
            ["TFI"],
            ["DUM"],
            ["TFI", [], "increment"],
            #
            # 3 - to test child/sibling priority
            #
            [
                "FAF",
                [
                    ["FAF", [], "increment"],
                    ["TVL"],
                ],
            ],
            ["TVL", [], "increment"],
            #
            # 4 - to test max repetition
            #
            ["FOP", [], None, 1],
            ["FOP", [], "increment"],
            ["DUM"],
            #
            # 5 - to test mandatory children
            #
            [
                "TPS",
                [
                    ["FAF"],
                    ["NTD", [], None, 99, "M"],
                    ["TVL", [], "increment"],
                ],
            ],
            ["CPD", [], "increment"],
            #
            # 5 - to test mandatory + max repetition
            #
            ["ODR"],
            ["NTD", [], "increment", 1, "M"],
            ["PSD", [], "increment"],
        ]
    }

    def __init__(self) -> None:
        self.test = 0

    def increment(self, segment: str) -> None:
        self.test += 1


# TESTS FOR SEGMENTS TOKENIZATION
#
TOKENIZERS: list[Callable[[str], Iterator[str]]] = [
    tokenize_segments,
    tokenize_segments_iter,
    tokenize_segments_with_blb,
]

EDI_AND_SEGMENTS: list[tuple[str, list[str]]] = [
    (" EQN' PTK+RP:RU' ", ["EQN", "PTK+RP:RU"]),
    ("ERC'IFT+1+USER\\'DATA'", ["ERC", "IFT+1+USER\\'DATA"]),
    ("SDI'SPI+'UNZ'TRUNC", ["SDI", "SPI+", "UNZ"]),
    (" EQN ", []),
    ("\\'", []),
]


@pytest.mark.parametrize("edi,segments", EDI_AND_SEGMENTS)
@pytest.mark.parametrize("tokenizer", TOKENIZERS)
def test_tokenize_segments(
    edi: str,
    segments: list[str],
    tokenizer: Callable[[str], Iterator[str]],
) -> None:
    assert list(tokenizer(edi)) == segments


@pytest.mark.parametrize("edi,segments", EDI_AND_SEGMENTS)
def test_tokenize_segments_reverse(edi: str, segments: list[str]) -> None:
    tokenizer = tokenize_segments_iter
    assert list(tokenizer(edi, reverse=True)) == list(tokenizer(edi))[::-1]


def test_build_transitions_accepts_optional_segments_before_mandatory_segment() -> None:
    transitions = build_transitions(
        Parser.header + Parser.schemas[0, 0] + Parser.footer
    )

    assert "AAA" in transitions[0]
    assert "BBB" in transitions[1]
    assert "CCC" in transitions[1]
    assert "UNT" not in transitions[1]


def test_parser_validate_and_parse_follow_schema_transitions() -> None:
    calls: list[str] = []

    class ActionParser(BaseParser):
        header = [["UNH", [], "on_segment"]]
        footer = [["UNT", [], "on_segment"]]
        schemas = {(0, 0): [["AAA", [], "on_segment"]]}

        def on_segment(self, segment: str) -> None:
            calls.append(segment)

    parser = ActionParser()
    parser.parse("UNH+1'AAA+2'UNT+3'")

    assert calls == ["UNH+1", "AAA+2", "UNT+3"]
    assert ActionParser.validate("UNH+1'AAA+2'UNT+3'")
    assert not ActionParser.validate("UNH+1'UNT+3'AAA+2'")


def test_tokenizer_is_selected_per_schema_version() -> None:
    class CustomParser(BaseParser):
        schemas = {
            (0, 0): [["AAA"]],
            (1, 0): [["BLB"]],
        }

    old = CustomParser.find_transitions((0, 0))
    new = CustomParser.find_transitions((1, 0))

    assert old.tokenize is tokenize_segments
    assert new.tokenize is tokenize_segments_with_blb


@pytest.mark.parametrize(
    ("edi", "segments"),
    [
        (
            "UNB+SENDER+RECEIVER'UNH+1+ORDERS:D:96A:UN'BGM+1'UNT+3+1'UNZ+1+1'",
            EnvelopeHeaders(
                unb="UNB+SENDER+RECEIVER",
                unh="UNH+1+ORDERS:D:96A:UN",
            ),
        ),
        (
            "UNH+1+IFTMIN'UNT+2+1'",
            EnvelopeHeaders(unh="UNH+1+IFTMIN"),
        ),
        (
            (
                "UNB\x1dSENDER\x1dRECEIVER\x1cUNH\x1d1"
                "\x1dORDERS\x1fD\x1f96A\x1fUN"
                "\x1cUNT\x1d3\x1d1\x1cUNZ\x1d1\x1d1\x1c"
            ),
            EnvelopeHeaders(
                unb="UNB+SENDER+RECEIVER",
                unh="UNH+1+ORDERS:D:96A:UN",
            ),
        ),
        (
            "UNB+SENDER+RECEIVER'UNZ+1+1'",
            EnvelopeHeaders(unb="UNB+SENDER+RECEIVER"),
        ),
        ("UNH+1+ORDERS:D:96A:UN", EnvelopeHeaders()),
    ],
)
def test_extract_envelope_headers(edi: str, segments: EnvelopeHeaders) -> None:
    assert extract_envelope_headers(edi) == segments


@pytest.mark.parametrize(
    ("edi", "segments"),
    [
        (
            "UNB+SENDER+RECEIVER'UNH+1+ORDERS:D:96A:UN'BGM+1'UNT+3+1'UNZ+1+1'",
            EnvelopeFooters(
                unt="UNT+3+1",
                unz="UNZ+1+1",
            ),
        ),
        (
            "UNH+1+IFTMIN'UNT+2+1'",
            EnvelopeFooters(unt="UNT+2+1"),
        ),
        (
            "UNH+1+ORDERS:D:96A:UN'BGM+1'UNT+3+1'UNZ+1+1'TRUNC",
            EnvelopeFooters(
                unt="UNT+3+1",
                unz="UNZ+1+1",
            ),
        ),
        (
            (
                "UNB\x1dSENDER\x1dRECEIVER\x1cUNH\x1d1"
                "\x1dORDERS\x1fD\x1f96A\x1fUN"
                "\x1cUNT\x1d3\x1d1\x1cUNZ\x1d1\x1d1\x1c"
            ),
            EnvelopeFooters(
                unt="UNT+3+1",
                unz="UNZ+1+1",
            ),
        ),
        (
            "UNB+SENDER+RECEIVER'UNZ+1+1'",
            EnvelopeFooters(unz="UNZ+1+1"),
        ),
        ("UNH+1+ORDERS:D:96A:UN", EnvelopeFooters()),
    ],
)
def test_extract_envelope_footers(edi: str, segments: EnvelopeFooters) -> None:
    assert extract_envelope_footers(edi) == segments


# TESTS FOR COMPLEX SCHEMAS
#
class TestComplexParser:
    def test_void(self) -> None:
        p = ComplexParser()
        assert p.test == 0

    def test_empty_string(self) -> None:
        p = ComplexParser()
        p.parse("")
        assert p.test == 0

    # PART 1
    #
    def test_simple_path(self) -> None:
        p = ComplexParser()
        p.parse("PTC'PTK'COR'EQN'")
        assert p.test == 2

    def test_optional_tag(self) -> None:
        p = ComplexParser()
        p.parse("PTK'COR'EQN'")
        assert p.test == 2

    def test_truncated_path(self) -> None:
        p = ComplexParser()
        p.parse("PTK'COR'EQN")  # missing last "'"
        assert p.test == 1

    def test_unknown_nodes(self) -> None:
        p = ComplexParser()
        p.parse("UNK'PTK'UNK'COR'EQN'")
        assert p.test == 2

    def test_father_is_mandatory_to_jump_to_son(self) -> None:
        p = ComplexParser()
        p.parse("COR'")
        assert p.test == 0

    def test_order_matters(self) -> None:
        p = ComplexParser()
        p.parse("EQN'PTK'COR'")
        assert p.test == 1

    # PART 2
    #
    def test_same_segment_name_1(self) -> None:
        p = ComplexParser()
        p.parse("TFI'")
        assert p.test == 0

    def test_repetition_1(self) -> None:
        p = ComplexParser()
        p.parse("TFI'TFI'")
        assert p.test == 0

    def test_same_segment_name_2(self) -> None:
        p = ComplexParser()
        p.parse("TFI'DUM'TFI'")
        assert p.test == 1

    def test_repetition_2(self) -> None:
        p = ComplexParser()
        p.parse("TFI'DUM'TFI'TFI'")
        assert p.test == 2

    # PART 3
    #
    def test_son_priority_over_self(self) -> None:
        p = ComplexParser()
        p.parse("FAF'FAF'")
        assert p.test == 1

    def test_son_priority_over_brother(self) -> None:
        p = ComplexParser()
        p.parse("FAF'TVL'")
        assert p.test == 0

    def test_brother_priority_over_parent(self) -> None:
        p = ComplexParser()
        p.parse("FAF'FAF'TVL'")
        assert p.test == 1

    def test_loop_back_to_parent(self) -> None:
        p = ComplexParser()
        p.parse("FAF'FAF'TVL'FAF'FAF'")
        assert p.test == 2

    # PART 4
    #
    def test_max_repetition_1(self) -> None:
        p = ComplexParser()
        p.parse("FOP'")
        assert p.test == 0

    def test_max_repetition_2(self) -> None:
        p = ComplexParser()
        p.parse("FOP'FOP'")
        assert p.test == 1

    def test_max_repetition_3(self) -> None:
        p = ComplexParser()
        p.parse("FOP'FOP'FOP'")
        assert p.test == 2

    def test_max_repetition_4(self) -> None:
        p = ComplexParser()
        p.parse("FOP'FOP'DUM'FOP'")
        assert p.test == 1

    # PART 5
    #
    def test_mandatory_is_normal_1(self) -> None:
        p = ComplexParser()
        p.parse("TPS'NTD'TVL'")
        assert p.test == 1

    def test_mandatory_is_normal_2(self) -> None:
        p = ComplexParser()
        p.parse("TPS'FAF'NTD'TVL'")
        assert p.test == 1

    def test_cannot_jump_over_mandatory(self) -> None:
        p = ComplexParser()
        p.parse("TPS'FAF'TVL'")
        assert p.test == 0

    def test_cannot_go_to_parent_if_mandatory_brother(self) -> None:
        p = ComplexParser()
        p.parse("TPS'FAF'CPD'")
        assert p.test == 0

    def test_cannot_go_to_son_after_mandatory_brother(self) -> None:
        p = ComplexParser()
        p.parse("TPS'TVL'")
        assert p.test == 0

    def test_cannot_go_to_brother_if_mandatory_son(self) -> None:
        p = ComplexParser()
        p.parse("TPS'CPD'")
        assert p.test == 0

    def test_can_jump_over_group_with_mandatory_son(self) -> None:
        p = ComplexParser()
        p.parse("CPD'")
        assert p.test == 1

    # PART 6
    #
    def test_missing_mandatory(self) -> None:
        p = ComplexParser()
        p.parse("ODR'PSD'")
        assert p.test == 0

    def test_missing_mandatory_from_root(self) -> None:
        p = ComplexParser()
        p.parse("PSD'")
        assert p.test == 0

    def test_mandatory(self) -> None:
        p = ComplexParser()
        p.parse("NTD'PSD'")
        assert p.test == 2

    def test_mandatory_with_max_repetition(self) -> None:
        p = ComplexParser()
        p.parse("NTD'NTD'PSD'")
        assert p.test == 2


# TESTS FOR DIRECT PARSER MANIPULATION
#
def test_baseparser_compile_is_idempotent() -> None:
    class CustomParser(BaseParser):
        # fmt: off
        schemas = {
            (0, 0): [
                ["PTC"],
                ["PTK", [
                    ["COR", [], "increment"]
                ]],
                ["TFI"],
            ],
        }
        # fmt: on

    # Schemas are no longer modified by compilation
    CustomParser.compile()
    assert CustomParser.schemas == {
        (0, 0): [
            ["PTC"],
            ["PTK", [["COR", [], "increment"]]],
            ["TFI"],
        ]
    }
    assert len(CustomParser._compiled_schemas) == 1

    CustomParser.compile()
    assert CustomParser.schemas == {
        (0, 0): [
            ["PTC"],
            ["PTK", [["COR", [], "increment"]]],
            ["TFI"],
        ]
    }
    assert len(CustomParser._compiled_schemas) == 1


def test_compilation_internals() -> None:
    class CustomParser(BaseParser):
        # fmt: off
        schemas = {
            (0, 0): [
                ["ED1"],
                ["ED2"],
                ["ED3"],
            ],
        }
        # fmt: on

    assert len(CustomParser._compiled_schemas) == 1
    version, tokenize, transitions = CustomParser._compiled_schemas[0]
    assert version == (0, 0)
    # 0 is the root
    # 1 is ED1
    # 2 is ED2
    # 3 is ED3
    assert tokenize is tokenize_segments
    assert transitions == {
        0: {
            "ED1": Transition(id_=1, path=("ED1",), action=None),
            "ED2": Transition(id_=2, path=("ED2",), action=None),
            "ED3": Transition(id_=3, path=("ED3",), action=None),
        },
        1: {
            "ED1": Transition(id_=1, path=("ED1",), action=None),
            "ED2": Transition(id_=2, path=("ED2",), action=None),
            "ED3": Transition(id_=3, path=("ED3",), action=None),
        },
        2: {
            "ED2": Transition(id_=2, path=("ED2",), action=None),
            "ED3": Transition(id_=3, path=("ED3",), action=None),
        },
        3: {"ED3": Transition(id_=3, path=("ED3",), action=None)},
    }

    # Check that Transition objects are the same object for a given id
    assert transitions[0]["ED1"] is transitions[1]["ED1"]
    assert transitions[0]["ED2"] is transitions[1]["ED2"]
    assert transitions[0]["ED2"] is transitions[2]["ED2"]
    assert transitions[0]["ED3"] is transitions[1]["ED3"]
    assert transitions[0]["ED3"] is transitions[2]["ED3"]
    assert transitions[0]["ED3"] is transitions[3]["ED3"]


def test_find_transitions_picks_highest_covered_version() -> None:
    class CustomParser(BaseParser):
        # fmt: off
        schemas = {
            (0, 0): [["OLD"]],
            (13, 2): [["CUR"]],
            (14, 0): [["NEW"]],
        }
        # fmt: on

    assert [t.version for t in CustomParser._compiled_schemas] == [
        (0, 0),
        (13, 2),
        (14, 0),
    ]

    assert CustomParser.find_transitions((0, 0))[0] == (0, 0)
    assert CustomParser.find_transitions((13, 1))[0] == (0, 0)
    assert CustomParser.find_transitions((13, 2))[0] == (13, 2)
    assert CustomParser.find_transitions((13, 9))[0] == (13, 2)
    assert CustomParser.find_transitions((99, 0))[0] == (14, 0)

    # Corner cases
    assert CustomParser.find_transitions()[0] == (14, 0)
    assert CustomParser.find_transitions(None)[0] == (14, 0)
    assert CustomParser.find_transitions((None, None))[0] == (14, 0)


def test_find_transitions_raises_when_version_is_not_covered() -> None:
    class CustomParser(BaseParser):
        # fmt: off
        schemas = {
            (13, 2): [["CUR"]],
        }
        # fmt: on

    with pytest.raises(ValueError) as excinfo:
        CustomParser.find_transitions((13, 1))

    assert str(excinfo.value) == (
        "Schemas do not cover all versions for CustomParser: [(13, 2)]"
    )


def test_baseparser_is_not_compiled() -> None:
    assert BaseParser.schemas == {}
    assert BaseParser._compiled_schemas == []

    with pytest.raises(ValueError) as excinfo:
        BaseParser.validate("AAA'")
    assert str(excinfo.value) == "No transitions found, did you forget to set a schema?"


def test_custom_parser_usage() -> None:
    class CustomParser(BaseParser):
        # fmt: off
        schemas = {
            (0, 0): [
                ["PTC"],
                ["PTK", [
                    ["COR", [], "increment"]
                ]],
                ["TFI"],
            ],
        }
        # fmt: on

        def __init__(self, message: dict[str, int]) -> None:
            self.message = message
            self.test = 0

        def increment(self, segment: str) -> None:
            self.test += 2
            self.message["counter"] += 1

    m = {"counter": 0}
    parser = CustomParser(m)

    assert parser.test == 0
    assert m["counter"] == 0

    parser.parse("PTK'COR'")
    assert parser.test == 2
    assert m["counter"] == 1

    parser.parse("PTK'COR'", (0, 0))
    assert parser.test == 4
    assert m["counter"] == 2

    assert parser.validate("PTK'COR'") is True
    assert parser.validate("COR'") is False

    assert isinstance(parser.show("PTK'"), str)


# TESTS FOR DOT OBJECT BUILDING
#
def test_build_dot_object_uses_selected_transitions_and_options() -> None:
    class CustomParser(BaseParser):
        # fmt: off
        schemas = {
            (0, 0): [["OLD"]],
            (1, 0): [
                ["CVR"],
                ["PIZ", [
                    ["TYP"],
                    ["REF"],
                ]],
            ],
        }
        # fmt: on

    old_dot = CustomParser.build_dot_object((0, 0))
    new_dot = CustomParser.build_dot_object((1, 0), include_up_links=False)
    assert old_dot.get_type() == "digraph"
    assert new_dot.get_type() == "digraph"

    assert {node.get("label") for node in old_dot.get_nodes()} == {None, "OLD"}
    nodes = {node.get("label"): node for node in new_dot.get_nodes()}
    assert set(nodes) == {None, "CVR", "PIZ", "PIZ\\nTYP", "PIZ\\nREF"}
    assert nodes["PIZ"].get("fontname") == "Monospace"
    assert nodes["PIZ"].get("shape") == "box"
    assert nodes["PIZ"].get("style") == "filled"
    assert nodes["PIZ"].get("fillcolor") == "bold"
    assert nodes["PIZ"].get("fontcolor") == "white"
    assert nodes["PIZ\\nTYP"].get("fillcolor") == "blue"

    labels: dict[Any, Any] = {
        node.get_name(): node.get("label") for node in new_dot.get_nodes()
    }
    edges = {
        (labels[edge.get_source()], labels[edge.get_destination()])
        for edge in new_dot.get_edges()
    }
    assert (None, "CVR") in edges
    assert ("PIZ", "PIZ\\nTYP") in edges
    assert ("PIZ", "PIZ\\nREF") in edges
    assert ("PIZ\\nTYP", "PIZ") not in edges
    assert ("PIZ\\nREF", "PIZ") not in edges

    dot_with_up_links = CustomParser.build_dot_object((1, 0))
    labels_with_up_links: dict[Any, Any] = {
        node.get_name(): node.get("label") for node in dot_with_up_links.get_nodes()
    }
    edges_with_up_links = {
        (
            labels_with_up_links[edge.get_source()],
            labels_with_up_links[edge.get_destination()],
        )
        for edge in dot_with_up_links.get_edges()
    }
    assert ("PIZ\\nTYP", "PIZ") in edges_with_up_links
    assert ("PIZ\\nREF", "PIZ") in edges_with_up_links
