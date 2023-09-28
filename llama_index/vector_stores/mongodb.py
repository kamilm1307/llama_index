"""MongoDB Vector store index.

An index that that is built on top of an existing vector store.

"""

import logging
import os
from typing import Any, Dict, List, Optional, cast

from llama_index.schema import BaseNode, MetadataMode, TextNode
from llama_index.vector_stores.types import (
    MetadataFilters,
    VectorStore,
    VectorStoreQuery,
    VectorStoreQueryResult,
)
from llama_index.vector_stores.utils import (
    metadata_dict_to_node,
    node_to_metadata_dict,
    legacy_metadata_dict_to_node,
)

from pymongo.errors import OperationFailure

logger = logging.getLogger(__name__)


def _to_mongodb_filter(standard_filters: MetadataFilters) -> Dict:
    """Convert from standard dataclass to filter dict."""
    filters = {}
    for filter in standard_filters.filters:
        filters[filter.key] = filter.value
    return filters


class MongoDBAtlasVectorSearch(VectorStore):
    """MongoDB Atlas Vector Store.

    To use, you should have both:
    - the ``pymongo`` python package installed
    - a connection string associated with a MongoDB Atlas Cluster
    that has an Atlas Vector Search index

    """

    stores_text: bool = True
    flat_metadata: bool = True

    def __init__(
        self,
        mongodb_client: Optional[Any] = None,
        db_name: str = "default_db",
        collection_name: str = "default_collection",
        index_name: str = "default",
        id_key: str = "id",
        embedding_key: str = "embedding",
        text_key: str = "text",
        metadata_key: str = "metadata",
        insert_kwargs: Optional[Dict] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the vector store.

        Args:
            mongodb_client: A MongoDB client.
            db_name: A MongoDB database name.
            collection_name: A MongoDB collection name.
            index_name: A MongoDB Atlas Vector Search index name.
            id_key: The data field to use as the id.
            embedding_key: A MongoDB field that will contain the embedding for each document.
            text_key: A MongoDB field that will contain the text for each document.
            metadata_key: A MongoDB field that will contain the metadata for each document.
            insert_kwargs: The kwargs used during `insert`.
        """
        import_err_msg = "`pymongo` package not found, please run `pip install pymongo`"
        try:
            import pymongo  # noqa: F401
        except ImportError:
            raise ImportError(import_err_msg)

        if mongodb_client is not None:
            self._mongodb_client = cast(pymongo.MongoClient, mongodb_client)
        else:
            if "MONGO_URI" not in os.environ:
                raise ValueError(
                    "Must specify MONGO_URI via env variable "
                    "if not directly passing in client."
                )
            self._mongodb_client = pymongo.MongoClient(os.environ["MONGO_URI"])

        self._collection = self._mongodb_client[db_name][collection_name]
        self._index_name = index_name
        self._embedding_key = embedding_key
        self._id_key = id_key
        self._text_key = text_key
        self._metadata_key = metadata_key
        self._insert_kwargs = insert_kwargs or {}
        self._use_vectorsearch = True

    def add(
        self,
        nodes: List[BaseNode],
    ) -> List[str]:
        """Add nodes to index.

        Args:
            nodes: List[BaseNode]: list of nodes with embeddings

        Returns:
            A List of ids for successfully added nodes.

        """
        ids = []
        data_to_insert = []
        for node in nodes:
            metadata = node_to_metadata_dict(
                node, remove_text=True, flat_metadata=self.flat_metadata
            )

            entry = {
                self._id_key: node.node_id,
                self._embedding_key: node.get_embedding(),
                self._text_key: node.get_content(metadata_mode=MetadataMode.NONE) or "",
                self._metadata_key: metadata,
            }
            data_to_insert.append(entry)
            ids.append(node.node_id)
        logger.debug("Inserting data into MongoDB: %s", data_to_insert)
        insert_result = self._collection.insert_many(
            data_to_insert, **self._insert_kwargs
        )
        logger.debug("Result of insert: %s", insert_result)
        return ids

    def delete(self, ref_doc_id: str, **delete_kwargs: Any) -> None:
        """
        Delete nodes using with ref_doc_id.

        Args:
            ref_doc_id (str): The doc_id of the document to delete.

        """
        # delete by filtering on the doc_id metadata
        self._collection.delete_one(
            filter={self._metadata_key + ".ref_doc_id": ref_doc_id}, **delete_kwargs
        )

    @property
    def client(self) -> Any:
        """Return MongoDB client."""
        return self._mongodb_client

    def _query_vectorsearch(self, query: VectorStoreQuery) -> VectorStoreQueryResult:
        params: dict[str, Any] = {
            "queryVector": query.query_embedding,
            "path": self._embedding_key,
            "numCandidates": query.similarity_top_k * 10,
            "limit": query.similarity_top_k,
            "index": self._index_name,
        }
        if query.filters:
            params["filter"] = _to_mongodb_filter(query.filters)

        query_field = {"$vectorSearch": params}
        search_field = "vectorSearchScore"

        return self._query(query_field, search_field)

    def _query_search(self, query: VectorStoreQuery) -> VectorStoreQueryResult:
        knn_beta: dict[str, Any] = {
            "vector": query.query_embedding,
            "path": self._embedding_key,
            "k": query.similarity_top_k,
        }
        if query.filters:
            knn_beta["filter"] = _to_mongodb_filter(query.filters)

        query_field = {
            "$search": {
                "index": self._index_name,
                "knnBeta": knn_beta,
            }
        }
        search_field = "searchScore"

        return self._query(query_field, search_field)

    def _query(
        self, query: dict[str, Any], search_field: str
    ) -> VectorStoreQueryResult:
        pipeline = [
            query,
            {"$project": {"score": {"$meta": search_field}, self._embedding_key: 0}},
        ]
        logger.debug("Running query pipeline: %s", pipeline)
        cursor = self._collection.aggregate(pipeline)  # type: ignore
        top_k_nodes = []
        top_k_ids = []
        top_k_scores = []
        for res in cursor:
            text = res.pop(self._text_key)
            score = res.pop("score")
            id = res.pop(self._id_key)
            metadata_dict = res.pop(self._metadata_key)

            try:
                node = metadata_dict_to_node(metadata_dict)
                node.set_content(text)
            except Exception:
                # NOTE: deprecated legacy logic for backward compatibility
                metadata, node_info, relationships = legacy_metadata_dict_to_node(
                    metadata_dict
                )

                node = TextNode(
                    text=text,
                    id_=id,
                    metadata=metadata,
                    start_char_idx=node_info.get("start", None),
                    end_char_idx=node_info.get("end", None),
                    relationships=relationships,
                )

            top_k_ids.append(id)
            top_k_nodes.append(node)
            top_k_scores.append(score)
        result = VectorStoreQueryResult(
            nodes=top_k_nodes, similarities=top_k_scores, ids=top_k_ids
        )
        logger.debug("Result of query: %s", result)
        return result

    def query(self, query: VectorStoreQuery, **kwargs: Any) -> VectorStoreQueryResult:
        """Query index for top k most similar nodes.

        Args:
            query: a VectorStoreQuery object.

        Returns:
            A VectorStoreQueryResult containing the results of the query.
        """
        if self._use_vectorsearch:
            try:
                result = self._query_vectorsearch(query)
            except OperationFailure as e:
                # Check for unsupported operation errors
                if "$vectorSearch" in str(e):
                    logger.error(
                        f"$vectorSearch not supported for this Atlas version. "
                        f"Attempting to use $search. Original error:\n\t{e}"
                    )
                    self._use_vectorsearch = False
                    result = self._query_search(query)
                else:
                    raise
        else:
            result = self._query_search(query)
        return result
