"""Dataset generation from documents"""
from __future__ import annotations

import re
from typing import List, Optional
import asyncio
from llama_index.schema import BaseNode, NodeWithScore, MetadataMode

from llama_index import Document, ServiceContext, SummaryIndex, ListIndex, QuestionAnswerPrompt
from llama_index.indices.postprocessor.node import KeywordNodePostprocessor
from llama_index.llms.openai import OpenAI
from llama_index.prompts.base import BasePromptTemplate, PromptTemplate
from llama_index.schema import BaseNode, MetadataMode, NodeWithScore

DEFAULT_QUESTION_GENERATION_PROMPT = """\
Context information is below.
---------------------
{context_str}
---------------------
Given the context information and not prior knowledge.
generate only questions based on the below query.
{query_str}
"""


def _get_default_service_context() -> ServiceContext:
    """Get default service context."""
    llm = OpenAI(temperature=0, model="gpt-3.5-turbo")
    service_context = ServiceContext.from_defaults(llm=llm, chunk_size_limit=3000)
    return service_context


class DatasetGenerator:
    """Generate dataset (question/question-answer pairs) based on the given documents.

    NOTE: This is a beta feature, subject to change!

    Args:
        nodes (List[Node]): List of nodes. (Optional)
        service_context (ServiceContext): Service Context.
        num_questions_per_chunk: Number of questions to be generated per chunk. Each document is chunked of size 512 words.
        text_question_template: Question generation template.
        question_gen_query: Question generation query.

    """

    def __init__(
        self,
        nodes: List[BaseNode],
        service_context: Optional[ServiceContext] = None,
        num_questions_per_chunk: int = 10,
        text_question_template: Optional[BasePromptTemplate] = None,
        question_gen_query: Optional[str] = None,
        metadata_mode: MetadataMode = MetadataMode.NONE,
    ) -> None:
        """Initialize the parameters."""
        if service_context is None:
            service_context = _get_default_service_context()
        self.service_context = service_context
        self.text_question_template = text_question_template or PromptTemplate(
            DEFAULT_QUESTION_GENERATION_PROMPT
        )
        self.question_gen_query = (
            question_gen_query
            or f"You are a Teacher/ Professor. Your task is to setup "
            f"{num_questions_per_chunk} questions for an upcoming "
            "quiz/examination. The questions should be diverse in nature "
            "across the document. Restrict the questions to the "
            "context information provided."
        )
        self.nodes = nodes
        self.num_questions_per_chunk = num_questions_per_chunk
        self.required_keywords = required_keywords or []
        self.exclude_keywords = exclude_keywords or []
        self._metadata_mode = metadata_mode

    @classmethod
    def from_documents(
        cls,
        documents: List[Document],
        service_context: Optional[ServiceContext] = None,
        num_questions_per_chunk: int = 10,
        text_question_template: Optional[BasePromptTemplate] = None,
        question_gen_query: Optional[str] = None,
        required_keywords: Optional[List[str]] = None,
        exclude_keywords: Optional[List[str]] = None,
    ) -> "DatasetGenerator":
        """Generate a dataset from documents."""
        if service_context is None:
            service_context = _get_default_service_context()
        nodes = service_context.node_parser.get_nodes_from_documents(documents)

        # Use node postprocessor to filter nodes
        required_keywords = required_keywords or []
        exclude_keywords = exclude_keywords or []
        node_postprocessor = KeywordNodePostprocessor(
            service_context=service_context,
            required_keywords=required_keywords,
            exclude_keywords=exclude_keywords,
        )
        node_with_scores = [NodeWithScore(node=node) for node in nodes]
        node_with_scores = node_postprocessor.postprocess_nodes(node_with_scores)
        nodes = [node_with_score.node for node_with_score in node_with_scores]

        return cls(
            nodes=nodes,
            service_context=service_context,
            num_questions_per_chunk=num_questions_per_chunk,
            text_question_template=text_question_template,
            question_gen_query=question_gen_query,
            required_keywords=required_keywords,
            exclude_keywords=exclude_keywords,
        )

    async def _node_question_generator(self, node: BaseNode) -> List[str]:
        """Generate questions for a single node."""
        index = ListIndex.from_documents(
            [
                Document(
                    text=node.get_content(metadata_mode=MetadataMode.NONE),
                    metadata=node.metadata,
                )

                ]
            )
        query_engine = index.as_query_engine(
            service_context=self.service_context,
            text_qa_template=self.text_question_template,
            use_async=True,
          )
        response = await query_engine.query(self.question_gen_query)

        result = str(response).strip().split("\n")
        cleaned_questions = [
        re.sub(r"^\d+[\).\s]", "", question).strip() for question in result
          ]
        return [question for question in cleaned_questions if question]

    async def generate_questions_from_nodes(self) -> List[str]:
        """Generate questions for each document asynchronously."""
        tasks = []
        for node in self.nodes:
            tasks.append(self._node_question_generator(node))

        generated_questions = await asyncio.gather(*tasks)
        return [question for questions in generated_questions for question in questions]

    def generate_questions_from_nodes_sync(self) -> List[str]:
        """Generate questions for each document synchronously."""
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.generate_questions_from_nodes())

