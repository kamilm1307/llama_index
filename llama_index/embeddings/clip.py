import logging
from typing import Any, List

import torch
from PIL import Image

from llama_index.bridge.pydantic import Field, PrivateAttr
from llama_index.embeddings.base import (
    DEFAULT_EMBED_BATCH_SIZE,
    BaseEmbedding,
    Embedding,
)

logger = logging.getLogger(__name__)

DEFAULT_CLIP_MODEL = "ViT-B/32"


class ClipEmbedding(BaseEmbedding):
    """CLIP embedding models for text and image.

    This class provides an interface to generate embeddings using a model
    deployed in OpenAI CLIP. At the initialization it requires a model name
    of CLIP.

    Note:
        Requires `clip` package to be available in the PYTHONPATH. It can be installed with
        `pip install git+https://github.com/openai/CLIP.git`.
    """

    embed_batch_size: int = Field(default=DEFAULT_EMBED_BATCH_SIZE, gt=0)

    _clip: Any = PrivateAttr()
    _model: Any = PrivateAttr()
    _preprocess: Any = PrivateAttr()
    _device: Any = PrivateAttr()

    @classmethod
    def class_name(cls) -> str:
        return "ClipEmbedding"

    def __init__(
        self,
        *,
        embed_batch_size: int = DEFAULT_EMBED_BATCH_SIZE,
        model_name: str = DEFAULT_CLIP_MODEL,
        **kwargs: Any,
    ):
        """Initializes the ClipEmbedding class.

        During the initialization the `clip` package is imported.

        Args:
            embed_batch_size (int, optional): The batch size for embedding generation. Defaults to 10,
                must be > 0 and <= 100.
            model_name (str): The model name of Clip model.

        Raises:
            ImportError: If the `clip` package is not available in the PYTHONPATH.
            ValueError: If the model cannot be fetched from Open AI. or if the embed_batch_size
                is not in the range (0, 100].
        """
        if embed_batch_size <= 0:
            raise ValueError(f"Embed batch size {embed_batch_size}  must be > 0.")

        try:
            import clip
        except ImportError:
            raise ImportError(
                "ClipEmbedding requires `pip install git+https://github.com/openai/CLIP.git`."
            )

        super().__init__(
            embed_batch_size=embed_batch_size, model_name=model_name, **kwargs
        )

        try:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model, self._preprocess = clip.load(
                self.model_name, device=self._device
            )

        except Exception as e:
            logger.error(f"Error while loading clip model.")
            raise ValueError("Unable to fetch the requested embeddings model") from e

    async def _aget_query_embedding(self, query: str) -> Embedding:
        return self._get_query_embedding(query)

    def _get_text_embedding(self, text: str) -> Embedding:
        return self._get_text_embeddings([text])[0]

    def _get_text_embeddings(self, texts: List[str]) -> List[Embedding]:
        results = []
        for text in texts:
            try:
                import clip
            except ImportError:
                raise ImportError(
                    "ClipEmbedding requires `pip install git+https://github.com/openai/CLIP.git`."
                )
            text_embedding = self._model.encode_text(
                clip.tokenize(text).to(self._device)
            )
            results.append(text_embedding.tolist()[0])

        return results

    def _get_query_embedding(self, query: str) -> Embedding:
        return self._get_text_embedding(query)

    def _get_image_embeddings(self, img_file_paths: List[str]) -> List[Embedding]:
        results = []
        for img_file_path in img_file_paths:
            with torch.no_grad():
                image = (
                    self._preprocess(Image.open(img_file_path))
                    .unsqueeze(0)
                    .to(self._device)
                )
                results.append(self._model.encode_image(image).tolist()[0])
        return results

    def get_image_embeddings(self, img_file_paths: List[str]) -> Embedding:
        return self._get_image_embeddings(img_file_paths)

    def _get_image_embedding(self, img_file_path: str) -> list[Embedding]:
        return self._get_image_embeddings([img_file_path])[0]

    def get_image_embedding(self, img_file_path: str) -> Embedding:
        return self._get_image_embedding(img_file_path)
