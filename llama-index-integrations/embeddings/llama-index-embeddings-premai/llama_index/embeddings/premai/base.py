"""PremAI embeddings file."""

from typing import Any, List, Optional

from llama_index.core.base.embeddings.base import (
    BaseEmbedding,
)
from llama_index.core.bridge.pydantic import PrivateAttr
from llama_index.core.callbacks.base import CallbackManager
from llama_index.core.base.llms.generic_utils import get_from_param_or_env
from llama_index.core.bridge.pydantic import Field

from premai import Prem


class PremAIEmbeddings(BaseEmbedding):
    """Class for PremAI embeddings."""

    project_id: int = Field(
        description=(
            "The project ID in which the experiments or deployements are carried out. can find all your projects here: https://app.premai.io/projects/"
        )
    )

    model_name: str = Field(
        description=("The Embedding model to choose from"),
    )

    # Instance variables initialized via Pydantic's mechanism
    _premai_client: "Prem" = PrivateAttr()

    def __init__(
        self,
        project_id: int,
        model_name: str,
        api_key: Optional[str] = None,
        callback_manager: Optional[CallbackManager] = None,
        **kwargs: Any,
    ):
        api_key = get_from_param_or_env("api_key", api_key, "PREMAI_API_KEY", "")

        if not api_key:
            raise ValueError(
                "You must provide an API key to use PremAI. "
                "You can either pass it in as an argument or set it `PREMAI_API_KEY`."
            )
        self._premai_client = Prem(api_key=api_key)
        super().__init__(
            project_id=project_id,
            model_name=model_name,
            callback_manager=callback_manager,
            **kwargs,
        )

    @classmethod
    def class_name(cls) -> str:
        return "PremAIEmbedding"

    def _get_query_embedding(self, query: str) -> List[float]:
        """Get query embedding."""
        embedding_response = self._premai_client.embeddings.create(
            project_id=self.project_id, model=self.model_name, input=query
        )
        return embedding_response.data[0].embedding

    async def _aget_query_embedding(self, query: str) -> List[float]:
        raise NotImplementedError("Async calls are not available in this version.")

    def _get_text_embedding(self, text: str) -> List[float]:
        """Get text embedding."""
        embedding_response = self._premai_client.embeddings.create(
            project_id=self.project_id, model=self.model_name, input=[text]
        )
        return embedding_response.data[0].embedding

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Get text embeddings."""
        embeddings = self._premai_client.embeddings.create(
            self, model=self.model_name, project_id=self.project_id, input=texts
        ).data
        return [embedding.embedding for embedding in embeddings]
