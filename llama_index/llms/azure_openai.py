from typing import Any, Dict, Optional

from openai import AsyncAzureOpenAI
from openai import AzureOpenAI as SyncAzureOpenAI

from llama_index.bridge.pydantic import Field, PrivateAttr, root_validator
from llama_index.callbacks import CallbackManager
from llama_index.llms.generic_utils import get_from_param_or_env
from llama_index.llms.openai import OpenAI
from llama_index.llms.openai_utils import (
    refresh_openai_azuread_token,
    resolve_from_aliases,
)


class AzureOpenAI(OpenAI):
    """
    Azure OpenAI.

    To use this, you must first deploy a model on Azure OpenAI.
    Unlike OpenAI, you need to specify a `engine` parameter to identify
    your deployment (called "model deployment name" in Azure portal).

    - model: Name of the model (e.g. `text-davinci-003`)
        This in only used to decide completion vs. chat endpoint.
    - engine: This will correspond to the custom name you chose
        for your deployment when you deployed a model.

    You must have the following environment variables set:
    - `OPENAI_API_VERSION`: set this to `2023-05-15`
        This may change in the future.
    - `AZURE_OPENAI_ENDPOINT`: your endpoint should look like the following
        https://YOUR_RESOURCE_NAME.openai.azure.com/
    - `AZURE_OPENAI_API_KEY`: your API key if the api type is `azure`

    More information can be found here:
        https://learn.microsoft.com/en-us/azure/cognitive-services/openai/quickstart?tabs=command-line&pivots=programming-language-python
    """

    engine: str = Field(description="The name of the deployed azure engine.")
    azure_endpoint: Optional[str] = Field(description="The Azure endpoint to use.")
    azure_deployment: Optional[str] = Field(description="The Azure deployment to use.")
    use_azure_ad: bool = Field(
        description="Indicates if Microsoft Entra ID (former Azure AD) is used for token authentication"
    )

    _azure_ad_token: Any = PrivateAttr()
    _client: SyncAzureOpenAI = PrivateAttr()
    _aclient: AsyncAzureOpenAI = PrivateAttr()

    def __init__(
        self,
        model: str = "gpt-35-turbo",
        engine: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        additional_kwargs: Optional[Dict[str, Any]] = None,
        max_retries: int = 10,
        api_key: Optional[str] = None,
        api_version: Optional[str] = None,
        # azure specific
        azure_endpoint: Optional[str] = None,
        azure_deployment: Optional[str] = None,
        use_azure_ad: bool = False,
        callback_manager: Optional[CallbackManager] = None,
        # aliases for engine
        deployment_name: Optional[str] = None,
        deployment_id: Optional[str] = None,
        deployment: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        engine = resolve_from_aliases(
            engine,
            deployment_name,
            deployment_id,
            deployment,
        )

        if engine is None:
            raise ValueError("You must specify an `engine` parameter.")

        azure_endpoint = get_from_param_or_env(
            "azure_endpoint", azure_endpoint, "AZURE_OPENAI_ENDPOINT", ""
        )

        super().__init__(
            engine=engine,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            additional_kwargs=additional_kwargs,
            max_retries=max_retries,
            api_key=api_key,
            azure_endpoint=azure_endpoint,
            azure_deployment=azure_deployment,
            use_azure_ad=use_azure_ad,
            api_version=api_version,
            callback_manager=callback_manager,
            **kwargs,
        )

    @root_validator
    def validate_env(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Validate necessary credentials are set."""
        if (
            values["api_base"] == "https://api.openai.com/v1"
            and values["azure_endpoint"] is None
        ):
            raise ValueError(
                "You must set OPENAI_API_BASE to your Azure endpoint. "
                "It should look like https://YOUR_RESOURCE_NAME.openai.azure.com/"
            )
        if values["api_version"] is None:
            raise ValueError("You must set OPENAI_API_VERSION for Azure OpenAI.")

        return values

    def _get_clients(self, **kwargs: Any) -> tuple[SyncAzureOpenAI, AsyncAzureOpenAI]:
        client = SyncAzureOpenAI(
            **self._get_credential_kwargs(),
        )
        aclient = AsyncAzureOpenAI(
            **self._get_credential_kwargs(),
        )
        return client, aclient

    def _get_credential_kwargs(self, **kwargs: Any) -> Dict[str, Any]:
        if self.use_azure_ad:
            self._azure_ad_token = refresh_openai_azuread_token(self._azure_ad_token)
            self.api_key = self._azure_ad_token.token

        return {
            "api_key": self.api_key,
            "azure_endpoint": self.azure_endpoint,
            "azure_deployment": self.azure_deployment,
            "api_version": self.api_version,
        }

    def _get_model_kwargs(self, **kwargs: Any) -> Dict[str, Any]:
        model_kwargs = super()._get_model_kwargs(**kwargs)
        model_kwargs["model"] = self.engine
        return model_kwargs

    @classmethod
    def class_name(cls) -> str:
        return "azure_openai_llm"
