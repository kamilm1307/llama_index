"""`Node` data structure.

`Node` is a generic data container that contains
a piece of data (e.g. chunk of text, an image, a table, etc).

In comparison to a raw `Document`, it contains additional metadata
about its relationship to other `Node`s (and `Document`s).

It is often used as an atomic unit of data in various indices.
"""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, Optional
import warnings

from dataclasses_json import DataClassJsonMixin

from gpt_index.schema import BaseDocument

import logging

_logger = logging.getLogger(__name__)


class DocumentRelationship(str, Enum):
    """Document relationships used in `Node` class."""

    SOURCE = auto()
    PREVIOUS = auto()
    NEXT = auto()


class NodeType(str, Enum):
    TEXT = auto()
    IMAGE = auto()
    INDEX = auto()


@dataclass
class Node(BaseDocument):
    """A generic node of data."""

    def __post_init__(self) -> None:
        """Post init."""
        super().__post_init__()
        # NOTE: for Node objects, the text field is required
        if self.text is None:
            raise ValueError("text field not set.")

    # extra node info
    node_info: Optional[Dict[str, Any]] = None

    # document relationships
    relationships: Dict[DocumentRelationship, str] = field(default_factory=dict)

    @property
    def ref_doc_id(self) -> Optional[str]:
        """Source document id."""
        return self.relationships.get(DocumentRelationship.SOURCE, None)

    @property
    def prev_node_id(self) -> str:
        """Prev node id."""
        if DocumentRelationship.PREVIOUS not in self.relationships:
            raise ValueError("Node does not have previous node")
        return self.relationships[DocumentRelationship.PREVIOUS]

    @property
    def next_node_id(self) -> str:
        """Next node id."""
        if DocumentRelationship.NEXT not in self.relationships:
            raise ValueError("Node does not have next node")
        return self.relationships[DocumentRelationship.NEXT]

    def get_text(self) -> str:
        """Get text."""
        text = super().get_text()
        result_text = (
            text if self.extra_info_str is None else f"{self.extra_info_str}\n\n{text}"
        )
        return result_text

    @classmethod
    def get_type(cls) -> str:
        """Get type."""
        return NodeType.TEXT


@dataclass
class ImageNode(Node):
    """Node with image."""

    # TODO: store reference instead of actual image
    # base64 encoded image str
    image: Optional[str] = None

    @classmethod
    def get_type(cls) -> str:
        return NodeType.IMAGE


@dataclass
class IndexNode(Node):
    """Node with reference to an index."""

    index_id: Optional[str] = None

    @classmethod
    def get_type(cls) -> str:
        return NodeType.INDEX


@dataclass
class NodeWithScore(DataClassJsonMixin):
    node: Node
    score: Optional[float] = None

    @property
    def doc_id(self) -> Optional[str]:
        warnings.warn(".doc_id is deprecated, use .node.ref_doc_id instead")
        return self.node.ref_doc_id

    @property
    def source_text(self) -> str:
        warnings.warn(".source_text is deprecated, use .node.get_text() instead")
        return self.node.get_text()

    @property
    def extra_info(self) -> Optional[Dict[str, Any]]:
        warnings.warn(".extra_info is deprecated, use .node.extra_info instead")
        return self.node.extra_info

    @property
    def node_info(self) -> Optional[Dict[str, Any]]:
        warnings.warn(".node_info is deprecated, use .node.node_info instead")
        return self.node.node_info

    @property
    def similarity(self) -> Optional[float]:
        warnings.warn(".similarity is deprecated, use .score instead instead")
        return self.score

    @property
    def image(self) -> Optional[str]:
        warnings.warn(
            ".image is deprecated, check if Node is an ImageNode \
            and use .node.image instead"
        )
        if isinstance(self.node, ImageNode):
            return self.node.image
        else:
            return None
