from enum import Enum
from typing import Optional, List, Any, Dict, Union

import vertexai
from llama_index.core.base.embeddings.base import Embedding, BaseEmbedding
from llama_index.core.callbacks import CallbackManager
from llama_index.core.embeddings import MultiModalEmbedding
from llama_index.core.schema import ImageType
from llama_index.core.base.embeddings.base import DEFAULT_EMBED_BATCH_SIZE
from vertexai.language_models import TextEmbeddingModel, TextEmbeddingInput
from vertexai.vision_models import MultiModalEmbeddingModel, Image

from llama_index.core.bridge.pydantic import PrivateAttr, Field


class VertexAIEmbeddingMode(str, Enum):
    """VertexAI embedding mode.

    Attributes:
        DEFAULT_MODE (str): The default embedding mode, for older models before August 2023,
                            that does not support task_type
        CLASSIFICATION_MODE (str): Optimizes embeddings for classification tasks.
        CLUSTERING_MODE (str): Optimizes embeddings for clustering tasks.
        SEMANTIC_SIMILARITY_MODE (str): Optimizes embeddings for tasks that require assessments of semantic similarity.
        RETRIEVAL_MODE (str): Optimizes embeddings for retrieval tasks, including search and document retrieval.
    """

    DEFAULT_MODE = "default"
    CLASSIFICATION_MODE = "classification"
    CLUSTERING_MODE = "clustering"
    SEMANTIC_SIMILARITY_MODE = "similarity"
    RETRIEVAL_MODE = "retrieval"


_TEXT_EMBED_TASK_TYPE_MAPPING: Dict[VertexAIEmbeddingMode, str] = {
    VertexAIEmbeddingMode.CLASSIFICATION_MODE: "CLASSIFICATION",
    VertexAIEmbeddingMode.CLUSTERING_MODE: "CLUSTERING",
    VertexAIEmbeddingMode.SEMANTIC_SIMILARITY_MODE: "SEMANTIC_SIMILARITY",
    VertexAIEmbeddingMode.RETRIEVAL_MODE: "RETRIEVAL_DOCUMENT",
}

_QUERY_EMBED_TASK_TYPE_MAPPING: Dict[VertexAIEmbeddingMode, str] = {
    VertexAIEmbeddingMode.CLASSIFICATION_MODE: "CLASSIFICATION",
    VertexAIEmbeddingMode.CLUSTERING_MODE: "CLUSTERING",
    VertexAIEmbeddingMode.SEMANTIC_SIMILARITY_MODE: "SEMANTIC_SIMILARITY",
    VertexAIEmbeddingMode.RETRIEVAL_MODE: "RETRIEVAL_QUERY",
}


def init_vertexai(
    project: Optional[str] = None,
    location: Optional[str] = None,
    credentials: Optional[Any] = None,
) -> None:
    """Init vertexai.

    Args:
        project: The default GCP project to use when making Vertex API calls.
        location: The default location to use when making API calls.
        credentials: The default custom
            credentials to use when making API calls. If not provided credentials
            will be ascertained from the environment.

    Raises:
        ImportError: If importing vertexai SDK did not succeed.
    """
    vertexai.init(
        project=project,
        location=location,
        credentials=credentials,
    )


def _get_embedding_request(
    texts: List[str], embed_mode: VertexAIEmbeddingMode, is_query: bool
) -> List[Union[str, TextEmbeddingInput]]:
    if embed_mode != VertexAIEmbeddingMode.DEFAULT_MODE:
        mapping = (
            _QUERY_EMBED_TASK_TYPE_MAPPING
            if is_query
            else _TEXT_EMBED_TASK_TYPE_MAPPING
        )
        texts = [
            TextEmbeddingInput(text=text, task_type=mapping[embed_mode])
            for text in texts
        ]
    return texts


class VertexTextEmbedding(BaseEmbedding):
    embed_mode: VertexAIEmbeddingMode = Field(description="The embedding mode to use.")
    additional_kwargs: Dict[str, Any] = Field(
        default_factory=dict, description="Additional kwargs for the Vertex."
    )

    _model: TextEmbeddingModel = PrivateAttr()

    def __init__(
        self,
        model_name: str = "textembedding-gecko@003",
        project: Optional[str] = None,
        location: Optional[str] = None,
        credentials: Optional[Any] = None,
        embed_mode: VertexAIEmbeddingMode = VertexAIEmbeddingMode.RETRIEVAL_MODE,
        embed_batch_size: int = DEFAULT_EMBED_BATCH_SIZE,
        callback_manager: Optional[CallbackManager] = None,
        additional_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        init_vertexai(project=project, location=location, credentials=credentials)
        callback_manager = callback_manager or CallbackManager([])
        additional_kwargs = additional_kwargs or {}

        super().__init__(
            embed_mode=embed_mode,
            additional_kwargs=additional_kwargs,
            model_name=model_name,
            embed_batch_size=embed_batch_size,
            callback_manager=callback_manager,
        )
        self._model = TextEmbeddingModel.from_pretrained(model_name)

    @classmethod
    def class_name(cls) -> str:
        return "VertexTextEmbedding"

    def _get_text_embeddings(self, texts: List[str]) -> List[Embedding]:
        texts = _get_embedding_request(
            texts=texts, embed_mode=self.embed_mode, is_query=False
        )
        embeddings = self._model.get_embeddings(texts, **self.additional_kwargs)
        return [embedding.values for embedding in embeddings]

    def _get_text_embedding(self, text: str) -> Embedding:
        return self._get_text_embeddings([text])[0]

    async def _aget_text_embeddings(self, texts: List[str]) -> List[Embedding]:
        texts = _get_embedding_request(
            texts=texts, embed_mode=self.embed_mode, is_query=False
        )
        embeddings = await self._model.get_embeddings_async(
            texts, **self.additional_kwargs
        )
        return [embedding.values for embedding in embeddings]

    def _get_query_embedding(self, query: str) -> Embedding:
        texts = _get_embedding_request(
            texts=[query], embed_mode=self.embed_mode, is_query=True
        )
        embeddings = self._model.get_embeddings(texts, **self.additional_kwargs)
        return embeddings[0].values

    async def _aget_query_embedding(self, query: str) -> Embedding:
        texts = _get_embedding_request(
            texts=[query], embed_mode=self.embed_mode, is_query=True
        )
        embeddings = await self._model.get_embeddings_async(
            texts, **self.additional_kwargs
        )
        return embeddings[0].values


class VertexMultiModalEmbedding(MultiModalEmbedding):
    embed_dimension: int = Field(description="The vertex output embedding dimension.")
    additional_kwargs: Dict[str, Any] = Field(
        default_factory=dict, description="Additional kwargs for the Vertex."
    )

    _model: MultiModalEmbeddingModel = PrivateAttr()
    _embed_dimension: int = PrivateAttr()

    def __init__(
        self,
        model_name: str = "multimodalembedding",
        project: Optional[str] = None,
        location: Optional[str] = None,
        credentials: Optional[Any] = None,
        embed_dimension: int = 1408,
        embed_batch_size: int = DEFAULT_EMBED_BATCH_SIZE,
        callback_manager: Optional[CallbackManager] = None,
        additional_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        init_vertexai(project=project, location=location, credentials=credentials)
        callback_manager = callback_manager or CallbackManager([])
        additional_kwargs = additional_kwargs or {}

        super().__init__(
            embed_dimension=embed_dimension,
            additional_kwargs=additional_kwargs,
            model_name=model_name,
            embed_batch_size=embed_batch_size,
            callback_manager=callback_manager,
        )
        self._model = MultiModalEmbeddingModel.from_pretrained(model_name)

    @classmethod
    def class_name(cls) -> str:
        return "VertexMultiModalEmbedding"

    def _get_text_embedding(self, text: str) -> Embedding:
        return self._model.get_embeddings(
            contextual_text=text, dimension=self._embed_dimension
        ).text_embedding

    def _get_image_embedding(self, img_file_path: ImageType) -> Embedding:
        if isinstance(img_file_path, str):
            image = Image.load_from_file(img_file_path)
        else:
            image = Image(image_bytes=img_file_path.getvalue())
        embeddings = self._model.get_embeddings(
            image=image, dimension=self._embed_dimension
        )
        return embeddings.image_embedding

    def _get_query_embedding(self, query: str) -> Embedding:
        return self._get_text_embedding(query)

    # Vertex AI SDK does not support async variants yet
    async def _aget_text_embedding(self, text: str) -> Embedding:
        return self._get_text_embedding(text)

    async def _aget_image_embedding(self, img_file_path: ImageType) -> Embedding:
        return self._get_image_embedding(img_file_path)

    async def _aget_query_embedding(self, query: str) -> Embedding:
        return self._get_query_embedding(query)
