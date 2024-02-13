from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.retrievers.you import YouRetriever


def test_class():
    names_of_base_classes = [b.__name__ for b in YouRetriever.__mro__]
    assert BaseRetriever.__name__ in names_of_base_classes
