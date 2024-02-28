"""Test query transform."""

from llama_index.legacy.indices.query.query_transform.base import (
    DecomposeQueryTransform,
)
from llama_index.legacy.service_context import ServiceContext

from tests.indices.query.query_transform.mock_utils import MOCK_DECOMPOSE_PROMPT


def test_decompose_query_transform(mock_service_context: ServiceContext) -> None:
    """Test decompose query transform."""
    query_transform = DecomposeQueryTransform(
        decompose_query_prompt=MOCK_DECOMPOSE_PROMPT,
        llm=mock_service_context.llm,
    )

    query_str = "What is?"
    new_query_bundle = query_transform.run(query_str, {"index_summary": "Foo bar"})
    assert new_query_bundle.query_str == "What is?:Foo bar"
    assert new_query_bundle.embedding_strs == ["What is?:Foo bar"]
