"""Faiss reader."""

from typing import Any, List

from gpt_index.readers.base import BaseReader
from gpt_index.readers.schema.base import Document


class FaissReader(BaseReader):
    """Faiss reader.

    Retrieves documents through an existing in-memory Faiss index.
    These documents can then be used in a downstream GPT Index data structure.
    If you wish use Faiss itself as an index to to organize documents,
    insert documents, and perform queries on them, please use GPTFaissIndex.

    Args:
        faiss_index (faiss.Index): A Faiss Index object (required)

    """

    def __init__(self, index: Any):
        """Initialize with parameters."""
        import_err_msg = """
            `faiss` package not found. For instructions on
            how to install `faiss` please visit
            https://github.com/facebookresearch/faiss/wiki/Installing-Faiss
        """
        try:
            import faiss  # noqa: F401
        except ImportError:
            raise ValueError(import_err_msg)

        self._index = index

    def load_data(self, **load_kwargs: Any) -> List[Document]:
        """Load data from Faiss.

        Args:
            query (np.ndarray): A 2D numpy array of query vectors.
            id_to_text_map (Dict[str, str]): A map from ID's to text.
            k (int): Number of nearest neighbors to retrieve. Defaults to 4.
            separate_documents (Optional[bool]): Whether to return separate
                documents. Defaults to False.
        Returns:
            List[Document]: A list of documents.

        """
        id_to_text_map = load_kwargs.pop("id_to_text_map", None)
        if id_to_text_map is None:
            raise ValueError(
                "Please provide an id_to_text_map (a map from ID's to text)."
            )

        query_vectors = load_kwargs.pop("query", None)
        if query_vectors is None:
            raise ValueError("Please provide `query` as an argument.")

        separate_documents = load_kwargs.pop("separate_documents", False)
        k = load_kwargs.pop("k", 4)

        dists, indices = self._index.search(query_vectors, k)
        documents = []
        for qidx in range(indices.shape[0]):
            for didx in range(indices.shape[1]):
                doc_id = indices[qidx, didx]
                if doc_id not in id_to_text_map:
                    raise ValueError(
                        f"Document ID {doc_id} not found in id_to_text_map."
                    )
                text = id_to_text_map[doc_id]
                documents.append(Document(text=text))

        if not separate_documents:
            # join all documents into one
            text_list = [doc.get_text() for doc in documents]
            text = "\n\n".join(text_list)
            documents = [Document(text=text)]

        return documents
