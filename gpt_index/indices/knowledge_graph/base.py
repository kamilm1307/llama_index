"""Keyword-table based index.

Similar to a "hash table" in concept. GPT Index first tries
to extract keywords from the source text, and stores the
keywords as keys per item. It similarly extracts keywords
from the query text. Then, it tries to match those keywords to
existing keywords in the table.

"""

import re
from abc import abstractmethod
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Type

from gpt_index.data_structs.data_structs import KG
from gpt_index.indices.base import DOCUMENTS_INPUT, BaseGPTIndex
from gpt_index.indices.keyword_table.utils import extract_keywords_given_response
from gpt_index.indices.query.base import BaseGPTIndexQuery
from gpt_index.indices.query.keyword_table.query import (
    GPTKeywordTableGPTQuery,
    GPTKeywordTableRAKEQuery,
    GPTKeywordTableSimpleQuery,
)
from gpt_index.indices.query.knowledge_graph.query import GPTKGTableQuery
from gpt_index.indices.query.schema import QueryMode
from gpt_index.langchain_helpers.chain_wrapper import LLMPredictor
from gpt_index.prompts.default_prompts import (
    DEFAULT_KEYWORD_EXTRACT_TEMPLATE,
    DEFAULT_KG_TRIPLET_EXTRACT_PROMPT,
    DEFAULT_KG_TRIPLET_EXTRACT_TMPL,
    DEFAULT_QUERY_KEYWORD_EXTRACT_TEMPLATE,
)
from gpt_index.prompts.prompts import KeywordExtractPrompt, KnowledgeGraphPrompt
from gpt_index.schema import BaseDocument
from gpt_index.utils import get_new_id

DQKET = DEFAULT_QUERY_KEYWORD_EXTRACT_TEMPLATE


class GPTKnowledgeGraphIndex(BaseGPTIndex[KG]):
    """GPT KG Index."""

    index_struct_cls = KG

    def __init__(
        self,
        documents: Optional[Sequence[DOCUMENTS_INPUT]] = None,
        index_struct: Optional[KG] = None,
        kg_triple_extract_template: Optional[KnowledgeGraphPrompt] = None,
        max_triplets_per_chunk: int = 10,
        llm_predictor: Optional[LLMPredictor] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize params."""
        # need to set parameters before building index in base class.
        self.max_triplets_per_chunk = max_triplets_per_chunk
        self.kg_triple_extract_template = (
            kg_triple_extract_template or DEFAULT_KG_TRIPLET_EXTRACT_PROMPT
        )
        # NOTE: Partially format keyword extract template here.
        self.kg_triple_extract_template = (
            self.kg_triple_extract_template.partial_format(
                max_knowledge_triplets=self.max_triplets_per_chunk
            )
        )
        super().__init__(
            documents=documents,
            index_struct=index_struct,
            llm_predictor=llm_predictor,
            **kwargs,
        )
        self._text_splitter = self._prompt_helper.get_text_splitter_given_prompt(
            self.kg_triple_extract_template, 1
        )

    @classmethod
    def get_query_map(self) -> Dict[str, Type[BaseGPTIndexQuery]]:
        """Get query map."""
        return {
            QueryMode.DEFAULT: GPTKGTableQuery,
        }

    def _extract_triplets(self, text: str) -> List[Tuple[str, str, str]]:
        """Extract keywords from text."""
        response, _ = self._llm_predictor.predict(
            self.kg_triple_extract_template,
            text=text,
        )
        print(response)
        return self._parse_triplet_response(response)

    @staticmethod
    def _parse_triplet_response(response: str) -> List[Tuple[str, str, str]]:
        knowledge_strs = response.strip().split("\n")
        results = []
        for text in knowledge_strs:
            subj, pred, obj = text[1:-1].split(",")
            results.append((subj, pred, obj))
        return results

    def _build_index_from_documents(
        self, documents: Sequence[BaseDocument], verbose: bool = False
    ) -> KG:
        """Build the index from documents."""
        text_splitter = self._prompt_helper.get_text_splitter_given_prompt(
            self.kg_triple_extract_template, 1
        )
        # do simple concatenation
        index_struct = KG(table={})
        for d in documents:
            nodes = self._get_nodes_from_document(d, text_splitter)
            for n in nodes:
                # set doc id
                node_id = get_new_id(set())
                n.doc_id = node_id

                triplets = self._extract_triplets(n.get_text())
                for triplet in triplets:
                    index_struct.upsert_triplet(triplet, n)
        return index_struct

    # def _insert(self, document: BaseDocument, **insert_kwargs: Any) -> None:
    #     """Insert a document."""
    #     nodes = self._get_nodes_from_document(document, self._text_splitter)
    #     for n in nodes:
    #         keywords = self._extract_keywords(n.get_text())
    #         self._index_struct.add_node(list(keywords), n)

    # def _delete(self, doc_id: str, **delete_kwargs: Any) -> None:
    #     """Delete a document."""
    #     # get set of ids that correspond to node
    #     node_idxs_to_delete = set()
    #     for node_idx, node in self._index_struct.text_chunks.items():
    #         if node.ref_doc_id != doc_id:
    #             continue
    #         node_idxs_to_delete.add(node_idx)
    #     for node_idx in node_idxs_to_delete:
    #         del self._index_struct.text_chunks[node_idx]

    #     # delete node_idxs from keyword to node idxs mapping
    #     keywords_to_delete = set()
    #     for keyword, node_idxs in self._index_struct.table.items():
    #         if node_idxs_to_delete.intersection(node_idxs):
    #             self._index_struct.table[keyword] = node_idxs.difference(
    #                 node_idxs_to_delete
    #             )
    #             if not self._index_struct.table[keyword]:
    #                 keywords_to_delete.add(keyword)

    #     for keyword in keywords_to_delete:
    #         del self._index_struct.table[keyword]
