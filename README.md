<div align="center">
    <img src="https://raw.githubusercontent.com/AmadeusITGroup/Edison/main/docs/edison.png" width="360" height="360" alt="Edison">
    <h1>Edison</h1>
    <p><strong>An EDIFACT parser with a real syntax tree.</strong></p>
    <p>
        <a href="https://github.com/AmadeusITGroup/Edison/actions/workflows/ci.yml"><img src="https://github.com/AmadeusITGroup/Edison/actions/workflows/ci.yml/badge.svg" alt="Build"></a>
        <a href="https://pypi.org/project/edison-parser/"><img src="https://img.shields.io/pypi/v/edison-parser.svg" alt="Version"></a>
        <a href="https://pypi.org/project/edison-parser/"><img src="https://img.shields.io/pypi/pyversions/edison-parser.svg" alt="Python versions"></a>
        <a href="https://github.com/AmadeusITGroup/Edison/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
      <!--  <a href="https://pepy.tech/project/edison-parser"><img src="https://static.pepy.tech/badge/edison-parser" alt="Downloads"></a>  -->
    </p>
</div>

Edison is a Python library for parsing EDIFACT messages. Instead of treating a message as a flat list of segments,
it models messages as a syntax tree: segments can define groups of child segments, recursively.

You define the syntax tree once, then parse, validate, or pretty-print messages against that structure.  
It works by converting the syntax tree to a state machine of possible transitions between segments.

## Highlights

- Define EDIFACT syntax trees directly in Python.
- Segments can define groups of child segments, which can be conditional, mandatory, or repeatable.
- Attach parsing callbacks to the segments you care about.
- Select syntax tree by message version.
- Handle escaped EDIFACT separators and EBCDIC control characters.
- Properly tokenize segments with specified lengths like `BLB`
- Export transition graphs with `pydot`.

## Installation

Edison requires Python 3.12 or newer.

```bash
pip install edison-parser
```

## Quick start

Subclass `BaseParser`, define one or more schemas, and attach callback method
names to the schema nodes you want to process.

```python
from edison import BaseParser


class PIZZAQParser(BaseParser):
    schemas = {
        (0, 0): [
            ["UNH"],
            ["CVR"],
            ["REF"],
            [
                "PIZ",
                [
                    ["TYP", [], "parse_typ"],
                    ["REF", [], "parse_ref"],
                ],
            ],
            ["UNT"],
        ],
    }

    def __init__(self):
        self.summary = {}
        self.pizza = None

    def parse_typ(self, segment: str):
        self.pizza = segment[4:]

    def parse_ref(self, segment: str):
        refs = segment[4:].split("*")
        self.summary[self.pizza] = len(refs)


edi = """
UNH+1+PIZZAQ:1:1:1A+00012480825035'
CVR+USD'
REF+LUIS'
PIZ+1'
TYP+MARGARITA'
REF+1*2'
PIZ+2'
TYP+PESTO'
REF+3'
UNT+19+1'
"""

# Create the parser and parse this EDIFACT message.
# The `summary` attribute is populated by the callbacks.
parser = PIZZAQParser()
parser.parse(edi)
parser.summary  # {"MARGARITA": 2, "PESTO": 1}

# Validate and pretty-print the message.
PIZZAQParser.validate(edi)  # True/False
PIZZAQParser.show(edi)  # to print
```

Here is the output of `PIZZAQParser.show(edi)`.

<div align="center">
    <img src="https://raw.githubusercontent.com/AmadeusITGroup/Edison/main/docs/Image.png" width="364" alt="Edison">
    <p><strong>Tree-based structure.</strong></p>
</div>

## Schema format

A schema is a dictionary keyed by the minimum supported version:

```python
schemas = {
    (0, 0): [
        ["UNH"],
        ["BGM"],
        ["UNT"],
    ],
}
```

Each segment node accepts these positional fields:

```python
["TAG", children, action, repetition, flag]
```

| Field | Default | Meaning |
| --- | --- | --- |
| `TAG` | required | Three-character EDIFACT segment tag. |
| `children` | `[]` | Nested segment group. |
| `action` | `None` | Parser method name called with the raw segment. |
| `repetition` | `99999` | `1` means single-use; any higher value means repeatable. |
| `flag` | `"C"` | `"C"` for conditional, `"M"` for mandatory. |

## Main API

| API | Use |
| --- | --- |
| `parser.parse(edi, version=None)` | Walk an EDI message and call matching segment actions. |
| `Parser.validate(edi, version=None)` | Return `True` when all segments follow the schema transitions. |
| `Parser.show(edi, version=None, colorize=True)` | Return a formatted, indented representation of an EDI message. |
| `Parser.build_dot_object(version=None, include_up_links=True)` | Build a `pydot.Dot` transition graph. |
| `extract_envelope_headers(edi)` | Quickly return the `UNB` and `UNH` envelope segments. |
| `extract_envelope_footers(edi)` | Quickly return the `UNT` and `UNZ` envelope segments. |
| `escape(data)` / `unescape(data)` | Escape or unescape EDIFACT separators: `+`, `:`, `*`, `'`. |
| `normalize_ebcdic_separators(edi)` | Convert EBCDIC EDIFACT separators to ASCII safely. |

## Advanced usage

<details>
<summary>Versioned syntax trees</summary>

Define multiple syntax trees when the same message evolves across versions. The
parser selects the highest schema version less than or equal to the `version`
argument, while parsing callbacks can stay the same.

```python
from edison import BaseParser


class RouteParser(BaseParser):
    schemas = {
        (0, 0): [
            ["UNH"],
            ["ORG", [], "parse_origin"],
            ["DST", [], "parse_destination"],
            ["UNT"],
        ],
        (2, 0): [
            ["UNH"],
            [
                "LEG",
                [
                    ["ORG", [], "parse_origin"],
                    ["DST", [], "parse_destination"],
                ],
            ],
            ["UNT"],
        ],
    }

    def __init__(self):
        self.route = {}

    def parse_origin(self, segment: str):
        self.route["origin"] = segment[4:]

    def parse_destination(self, segment: str):
        self.route["destination"] = segment[4:]


legacy = RouteParser()
legacy.parse("UNH'ORG+PAR'DST+NCE'UNT'", version=(1, 0))

modern = RouteParser()
modern.parse("UNH'LEG+1'ORG+PAR'DST+NCE'UNT'", version=(2, 0))

assert legacy.route == modern.route == {
    "origin": "PAR",
    "destination": "NCE",
}
assert RouteParser.validate("UNH'ORG+PAR'DST+NCE'UNT'", version=(1, 0))
assert RouteParser.validate("UNH'LEG+1'ORG+PAR'DST+NCE'UNT'", version=(2, 0))
```

When `version` is omitted, incomplete, or newer than all known schemas, Edison
uses the latest schema. If a requested version is older than the first schema,
`find_transitions()` raises `ValueError`.

</details>

<details>
<summary>Mandatory and repeatable segments</summary>

`repetition` controls whether the transition graph can come back to the same
node:

- `1` means the node can be used once in a given sequence.
- Any value greater than `1` means the node is repeatable. The transition graph
  only distinguishes `1` from "repeatable"; it does not count exact occurrence
  limits such as `2` versus `99999`.

Mandatory nodes constrain valid paths through the tree. Once a mandatory node is
next in a sequence, the parser cannot skip over it to reach a later sibling, a
parent, or a child that would bypass it. A mandatory child does not make its
parent mandatory by itself: if the whole group is required, mark the group node
as `"M"` too.

```python
from edison import BaseParser


class OrderParser(BaseParser):
    schemas = {
        (0, 0): [
            ["UNH"],
            [
                "ITM",
                [
                    ["DSC"],
                    ["QTY", [], "parse_quantity", 1, "M"],
                    ["PRI"],
                ],
                None,
                99999,
                "M",
            ],
            ["UNT"],
        ],
    }

    def __init__(self):
        self.quantities = []

    def parse_quantity(self, segment: str):
        self.quantities.append(segment[4:])


assert OrderParser.validate("UNH'ITM'DSC'QTY+2'PRI'ITM'QTY+1'UNT'")
assert not OrderParser.validate("UNH'UNT'")  # ITM is mandatory.
assert not OrderParser.validate("UNH'ITM'PRI'UNT'")  # QTY is mandatory.
assert not OrderParser.validate("UNH'ITM'QTY+2'QTY+3'UNT'")  # QTY repeats once.
```

</details>

<details>
<summary>Shared headers, footers, and parser hooks</summary>

Use `header` and `footer` when several schemas share envelope segments. They are
automatically prepended and appended to every schema at class compilation time.

```python
from edison import BaseParser


class EnvelopeParser(BaseParser):
    header = [["UNH", [], "on_segment"]]
    footer = [["UNT", [], "on_segment"]]
    schemas = {(0, 0): [["BGM", [], "on_segment"]]}

    def __init__(self):
        self.segments = []

    def set_up(self):
        self.segments.clear()

    def on_segment(self, segment: str):
        self.segments.append(segment)

    def tear_down(self):
        self.count = len(self.segments)
```

`set_up()` runs before parsing starts, and `tear_down()` runs after parsing
finishes.

</details>

<details>
<summary>Transition graphs</summary>

Internally, Edison builds a directed graph of transitions between segments, when the parser class is created.  
Each node is a specific segment, and each edge is a valid transition to the next segment.  
With this, parsing is just a walk through the graph, and validation is checking if the path exists.

You can visualize the transition graph with `build_dot_object()`, which returns a `pydot.Dot` object.  
`pydot` is installed with Edison. To write PNG files, make sure Graphviz is available on your system.

```python
from edison import BaseParser


class Parser(BaseParser):
    schemas = {
        (0, 0): [
            ["UNH"],
            [
                "BGM",
                [
                    ["DTM"],
                ],
            ],
            ["UNT"],
        ],
    }


dot = Parser.build_dot_object()
dot.write_png("transitions.png")
```

Here is the resulting graph for the above schema.

<p align="center">
    <img src="https://raw.githubusercontent.com/AmadeusITGroup/Edison/main/docs/transitions.png" alt="pydot">
</p>

You can pass the same version selector used by parsing, and hide upward links
for a simpler tree-like graph:

```python
dot = Parser.build_dot_object(version=(13, 2), include_up_links=False)
dot.write_png("transitions-v13.png")
```

Because `build_dot_object()` returns the underlying `pydot.Dot` object, you can
customize it before writing.

</details>

<details>
<summary>Escaping and EBCDIC EDIFACT separators</summary>

Edison understands escaped EDIFACT separators and can normalize EBCDIC separator
characters often found in binary payloads.

```python
from edison import normalize_ebcdic_separators, escape, unescape


assert escape("REC+") == r"REC\+"
assert unescape(r"REC\+") == "REC+"
assert normalize_ebcdic_separators("UNB\x1dSENDER\x1fREC") == "UNB+SENDER:REC"
```

The segment tokenizer also handles escaped quotes, so content such as
`IFT+1+AIRLINE\'SERVER'` stays in a single EDIFACT segment.

</details>

<details>
<summary>EDIFACT envelope extraction</summary>

For the common case of reading EDIFACT envelope boundaries, use
`extract_envelope_headers()` to lazily return the first `UNB`/`UNH` segments or
`extract_envelope_footers()` to lazily return the last `UNT`/`UNZ` segments:

```python
from edison import extract_envelope_footers, extract_envelope_headers

edi = "UNB+SENDER+RECEIVER'UNH+1+PIZZAQ:1:1:1A'BGM+1'UNT+3+1'UNZ+1+1'"
headers = extract_envelope_headers(edi)
footers = extract_envelope_footers(edi)

assert headers.unb == "UNB+SENDER+RECEIVER"
assert headers.unh == "UNH+1+PIZZAQ:1:1:1A"
assert footers.unt == "UNT+3+1"
assert footers.unz == "UNZ+1+1"
```

</details>

## Development

<details>
<summary>Local commands</summary>

This repository uses `uv`, `tox`, `pytest`, `ruff`, `black`, `ty`, and
pre-commit hooks.

```bash
uv tool install tox --with tox-uv
tox -e py
```

Build distributions with:

```bash
uv build --sdist --wheel -o dist/
```

Run the full pre-commit suite with:

```bash
uv tool install prek==0.4.10
prek run --all-files
```

CI runs tests through tox on CPython 3.12 and 3.14 across Linux, Windows, and
macOS, then builds source and wheel distributions.

</details>
