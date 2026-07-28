#!/usr/bin/env python

import logging
from bisect import bisect_right
from operator import itemgetter
from collections.abc import Iterator, Callable, Sequence
from typing import Any, NamedTuple, Literal, TypedDict, TYPE_CHECKING
from typing_extensions import TypeIs
import platform

from .tokenizer import tokenize_segments, tokenize_segments_with_blb

PYPY = platform.python_implementation() == "PyPy"

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    import pydot


__all__ = ["BaseParser"]


type VersionTuple = tuple[int | None, int | None]
type SchemaVersion = tuple[int, int]

type EDITag = str
type EDIPath = tuple[EDITag, ...]
type EDIAction = str | None  # method to call when this segment is found
type EDIRepetition = int  # number of times you can pass on a node
type EDIFlag = Literal["M", "C"]  # mandatory or conditional

# NodeId is the index of a node in the schema, starting at 0 for the root node.
type NodeId = int

# RawEDISegment is the input schema, which is a recursive lists of lists.
# EDISegment is the normalized view used while building transitions.
type RawEDISegment = list[Any]


class EDISegment(NamedTuple):
    id_: NodeId
    tag: EDITag
    children_raw: Sequence[RawEDISegment] = ()
    action: EDIAction = None
    repetition: EDIRepetition = 99999
    flag: EDIFlag = "C"


class EDISegmentFactory:
    def __init__(self, start_id: NodeId) -> None:
        self._next_id = start_id

    def create_from_raw(self, raw_segment: RawEDISegment) -> EDISegment:
        node = EDISegment(self._next_id, *raw_segment)
        if not isinstance(node.children_raw, (list, tuple)):
            raise ValueError(f"{raw_segment!r} should have a list in second position")
        self._next_id += 1
        return node


class Transition(NamedTuple):
    id_: NodeId
    path: EDIPath
    action: str | None


type NodeTransitions = dict[EDITag, Transition]
type NodeTransitionsList = list[tuple[EDITag, Transition]]
type SegmentTokenizer = Callable[[str], Iterator[str]]


class CompiledSchema(NamedTuple):
    version: SchemaVersion
    tokenize: SegmentTokenizer
    transitions: dict[NodeId, NodeTransitions]


def format_path(path: EDIPath, sep: str = "/") -> str:
    """Format a path in transition object.

    >>> format_path(())
    '/'
    >>> format_path(("PTK",))
    '/PTK'
    >>> format_path(("PTK", "COR"))
    '/PTK/COR'
    """
    return f"{sep}{sep.join(path)}"


def build_transitions(schema: list[RawEDISegment]) -> dict[NodeId, NodeTransitions]:
    transitions: dict[NodeId, NodeTransitions] = {}
    transitions_cache: dict[NodeId, Transition] = {}

    def get_transition(parent_path: EDIPath, node: EDISegment) -> Transition:
        # We cache the transition objects to avoid creating multiple instances for
        # the same node. Indeed the transitions object we return is a mapping of
        # tag -> Transition(node_id, path, action), so this object can be reused
        # for all incoming transitions to the same node.
        # We also delay the creation of the path until we actually need it.
        try:
            return transitions_cache[node.id_]
        except KeyError:
            transition = Transition(node.id_, (*parent_path, node.tag), node.action)
            transitions_cache[node.id_] = transition
            return transition

    factory = EDISegmentFactory(start_id=0)
    root = factory.create_from_raw(["", schema])
    stack: list[tuple[EDISegment, EDIPath, NodeTransitionsList]] = [(root, (), [])]

    while stack:
        node, node_path, parent_transitions = stack.pop()
        child_nodes = [factory.create_from_raw(raw) for raw in node.children_raw]
        transitions[node.id_] = node_trans = {}

        # We store the index of the next mandatory segment for each child.
        next_mandatory_indexes: list[int | None] = [None] * len(child_nodes)
        next_mandatory_index = None

        for i in range(len(child_nodes) - 1, 0, -1):
            child = child_nodes[i]
            if child.flag == "M":
                next_mandatory_index = i
            next_mandatory_indexes[i - 1] = next_mandatory_index

        # We store the index of the first mandatory child.
        for i, child in enumerate(child_nodes):
            if child.flag == "M":
                first_mandatory_index = i
                break
        else:  # no break
            first_mandatory_index = None

        # Now we iterate over the children to push their children in the stack
        for i, child in enumerate(child_nodes):
            child_path = (*node_path, child.tag)

            # In cases where you have several segments with the same name in a group
            # we only keep the transition to the first in the parent
            if child.tag not in node_trans:
                # We do not transition after the first mandatory child.
                if first_mandatory_index is None or i <= first_mandatory_index:
                    node_trans[child.tag] = get_transition(node_path, child)

            # repetition is the number of times you can pass on a node, today we only
            # consider 1 or more-than-one options, to put a transition to self or not
            if child.repetition > 1:
                i_start = i
            else:
                i_start = i + 1

            # Sibling transitions stop at the first mandatory sibling.
            next_mandatory_index = next_mandatory_indexes[i]

            if next_mandatory_index is None:
                i_end = None
            else:
                i_end = next_mandatory_index + 1

            sibling_transitions = [
                (sibling.tag, get_transition(node_path, sibling))
                for sibling in child_nodes[i_start:i_end]
            ]

            # Siblings are before parents because local transitions inside group
            # have priority over parents
            # Also note that siblings may contain the child if repetition > 1
            # in that case child transitions have priority over self if same tag name
            if i_end is None:
                child_parent_transitions = sibling_transitions + parent_transitions
            else:
                child_parent_transitions = sibling_transitions

            stack.append((child, child_path, child_parent_transitions))

        # We do not add links to parents if there is a mandatory child.
        if first_mandatory_index is None:
            for parent_tag, transition in parent_transitions:
                if parent_tag not in node_trans:
                    node_trans[parent_tag] = transition

    return transitions


def _has_blb_segment(transitions: dict[NodeId, NodeTransitions]) -> bool:
    """Scan transitions to find out if a BLB segment is there."""
    return any("BLB" in node_trans for node_trans in transitions.values())


# PYDOT GLOBAL OPTIONS
#
class NodeOptions(TypedDict):
    fontname: str
    shape: str
    style: str


class EdgeOptions(TypedDict):
    fontname: str


N_OPTIONS: NodeOptions = {
    "fontname": "Monospace",
    "shape": "box",
    "style": "filled",
}
E_OPTIONS: EdgeOptions = {
    "fontname": "Monospace",
}


# SHOW MISC.
#
COLORIZE = {
    "bold": "\033[1m{0}\033[0m",
    "grey": "\033[01;90m{0}\033[0m",
    "white": "\033[01;97m{0}\033[0m",
    "red": "\033[01;31m{0}\033[0m",
    "green": "\033[01;32m{0}\033[0m",
    "yellow": "\033[01;33m{0}\033[0m",
    "blue": "\033[01;34m{0}\033[0m",
    "magenta": "\033[01;35m{0}\033[0m",
    "cyan": "\033[01;36m{0}\033[0m",
}

STYLE = {
    "bold": "\033[1m{0}\033[0m",
    "dim": "\033[2m{0}\033[0m",
    "italic": "\033[3m{0}\033[0m",
    "underline": "\033[4m{0}\033[0m",
    "blink": "\033[5m{0}\033[0m",
    "reverse": "\033[7m{0}\033[0m",
    "hidden": "\033[8m{0}\033[0m",
    "strikethrough": "\033[9m{0}\033[0m",
}

blink = STYLE["blink"].format


def is_full_version(version: VersionTuple | None) -> TypeIs[tuple[int, int]]:
    if version is None:
        return False
    if version[0] is None or version[1] is None:
        log.warning("Message version %r contains None", version)
        return False
    return True


class BaseParser:
    """This is a generic parser that should be subclassed wih a schemas."""

    __slots__ = []

    # Those can/should be overriden when subclassing
    #
    header: list[RawEDISegment] = []
    footer: list[RawEDISegment] = []
    schemas: dict[SchemaVersion, list[RawEDISegment]] = {}

    # Assigned in compile() during class definition
    #
    _compiled_schemas: list[CompiledSchema] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.compile()

    @classmethod
    def compile(cls) -> None:
        """This is automatically called when a BaseParser subclass is defined."""
        cls._compiled_schemas = []
        for version in sorted(cls.schemas):
            schema = [*cls.header, *cls.schemas[version], *cls.footer]
            transitions = build_transitions(schema)
            tokenize: SegmentTokenizer
            if _has_blb_segment(transitions):
                tokenize = tokenize_segments_with_blb
            else:
                tokenize = tokenize_segments
            cls._compiled_schemas.append(CompiledSchema(version, tokenize, transitions))

    def set_up(self) -> None:
        """To be subclassed to trigger something at the beginning of parsing."""

    def tear_down(self) -> None:
        """To be subclassed to trigger something at the end of parsing."""

    @classmethod
    def find_transitions(
        cls,
        version: VersionTuple | None = None,
    ) -> CompiledSchema:
        # Each (min_version, tokenize, transitions) in cls._compiled_schemas is sorted
        # by min_version. We want to find the largest min_version that is less than
        # or equal to the given version. We can use bisect_right to find the insertion
        # point for the given version in the sorted list of min_versions.
        # We have a fast path before doing the bisect because in practice most input
        # version are higher than the latest defined schema version.
        if not cls._compiled_schemas:
            raise ValueError("No transitions found, did you forget to set a schema?")

        latest = cls._compiled_schemas[-1]
        if not is_full_version(version):
            return latest
        if version >= latest.version:  # fast path, common
            return latest

        index = bisect_right(cls._compiled_schemas, version, key=itemgetter(0))
        if index > 0:
            return cls._compiled_schemas[index - 1]

        raise ValueError(
            f"Schemas do not cover all versions for {cls.__name__}:"
            f" {[t.version for t in cls._compiled_schemas]}"
        )

    def parse(self, edi: str, version: VersionTuple | None = None) -> None:
        _, tokenize, transitions = self.find_transitions(version)
        id_ = 0  # starting at root
        self.set_up()
        for segment in tokenize(edi):
            tag = segment[:3]
            if (tr := transitions[id_].get(tag)) is not None:
                id_, _, action = tr
                if action is not None:
                    getattr(self, action)(segment)
        self.tear_down()

    @classmethod
    def validate(cls, edi: str, version: VersionTuple | None = None) -> bool:
        _, tokenize, transitions = cls.find_transitions(version)
        id_: NodeId = 0  # starting at root
        path: EDIPath = ()
        for segment in tokenize(edi):
            tag = segment[:3]
            if (tr := transitions[id_].get(tag)) is not None:
                id_, path, _ = tr
                continue
            # If we reach this point, it means the segment is not valid.
            if not transitions[id_]:
                log.warning(
                    "[%s] Cannot continue from %s, but still got %r",
                    cls.__name__,
                    format_path(path),
                    tag,
                )
            else:  # only other case is 'tag is not in transitions[id_]'
                log.warning(
                    "[%s] Cannot continue from %s with %r, should be one of:\n%s",
                    cls.__name__,
                    format_path(path),
                    tag,
                    "\n".join(
                        f"{k!r} -> {format_path(v.path)}"
                        for k, v in transitions[id_].items()
                    ),
                )
            return False
        return True

    # Color related stuff
    #
    _depth_colors = [
        "bold",
        "blue",
        "green",
        "yellow",
        "magenta",
        "blue",
        "green",
        "yellow",
        "magenta",
    ]
    _hidden: set[str] = set()

    @classmethod
    def show(
        cls,
        edi: str,
        version: VersionTuple | None = None,
        formatting: bool = True,
    ) -> str:
        _, tokenize, transitions = cls.find_transitions(version)
        res = []
        id_, depth = 0, 0  # starting at root

        for segment in tokenize(edi):
            tag = segment[:3]
            segment = f"{segment}'"

            if (tr := transitions[id_].get(tag)) is not None:
                id_, path, _ = tr
                depth = len(path)
                known = True
            else:
                known = False

            if not formatting:
                color = None
            elif not known:
                color = "red"
            elif tag in cls._hidden:
                color = "grey"
            else:
                color = cls._depth_colors[(depth - 1) % len(cls._depth_colors)]

            if not known:
                filler = "-" * 2 * (depth - 1)
            else:
                filler = " " * 2 * (depth - 1)

            if color is not None:
                # "blink" actually adds an almost-invisible property to the filler,
                # so we can filter on it in CSS and set the user-select to none.
                filler = COLORIZE[color].format(blink(filler))
                segment = COLORIZE[color].format(segment)

            res.append(filler + segment)

        return "\n".join(res)

    @classmethod
    def build_dot_object(
        cls,
        version: VersionTuple | None = None,
        *,
        include_up_links: bool = True,
    ) -> "pydot.Dot":
        import pydot

        _, _, transitions = cls.find_transitions(version)
        colors = cls._depth_colors
        dot = pydot.Dot(graph_type="digraph")

        nodes = {id_: pydot.Node(str(id_), **N_OPTIONS) for id_ in transitions}

        for source_id in transitions:
            for tag in transitions[source_id]:
                target_id, path, _ = transitions[source_id][tag]
                fillcolor = colors[(len(path) - 1) % len(colors)]
                node = nodes[target_id]
                node.set("label", "\\n".join(path))
                node.set("fillcolor", fillcolor)
                node.set(
                    "fontcolor",
                    "white" if fillcolor in {"bold", "blue"} else "black",
                )

        for source_id in transitions:
            source_label = nodes[source_id].get("label")
            if source_label in cls._hidden:
                continue
            dot.add_node(nodes[source_id])
            for tag in transitions[source_id]:
                target_id, path, _ = transitions[source_id][tag]
                target_label = nodes[target_id].get("label")
                if target_label in cls._hidden:
                    continue
                if (
                    not include_up_links
                    and source_label
                    and len(source_label) > len(target_label)
                ):
                    continue
                dot.add_edge(
                    pydot.Edge(nodes[source_id], nodes[target_id], **E_OPTIONS)
                )

        return dot
