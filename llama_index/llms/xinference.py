from typing import Any, Dict, Sequence

from llama_index.constants import DEFAULT_NUM_OUTPUTS
from llama_index.llms.base import (
    ChatMessage,
    ChatResponse,
    ChatResponseGen,
    CompletionResponse,
    CompletionResponseGen,
    LLMMetadata,
    MessageRole,
)
from llama_index.llms.custom import CustomLLM
from llama_index.llms.xinference_utils import (
    xinference_message_to_history,
    xinference_modelname_to_contextsize,
)

# an approximation of the ratio between llama and GPT2 tokens
TOKEN_RATIO = 2.5


class Xinference(CustomLLM):
    def __init__(
            self,
            model_uid: str,
            endpoint: str,
            temperature: float = 1.0,
    ) -> None:

        self.temperature = temperature
        self.model_uid = model_uid
        self.endpoint = endpoint

        self._model_description = None
        self._context_window = None
        self._generator = None
        self._client = None
        self._model = None
        self.load()

    def load(self) -> None:

        try:
            from xinference.client import RESTfulClient
        except ImportError:
            raise ImportError(
                'Could not import Xinference library.'
                'Please install Xinference with `pip install "xinference[all]"`'
            )

        self._client = RESTfulClient(self.endpoint)
        self._generator = self._client.get_model(self.model_uid)
        self._model_description = self._client.list_models()[self.model_uid]

        self._model = self._model_description["model_name"]
        self._context_window = xinference_modelname_to_contextsize(self._model)

    @property
    def metadata(self) -> LLMMetadata:
        """LLM metadata."""
        return LLMMetadata(
            context_window=int(self._context_window // TOKEN_RATIO),
            num_output=DEFAULT_NUM_OUTPUTS,
            model_name=self._model,
        )

    @property
    def _model_kwargs(self) -> Dict[str, Any]:
        base_kwargs = {
            "temperature": self.temperature,
            "max_length": self._context_window,
        }
        model_kwargs = {
            **base_kwargs,
            **self._model_description,
        }
        return model_kwargs

    def _get_input_dict(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        return {"prompt": prompt, **self._model_kwargs, **kwargs}

    def chat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> ChatResponse:
        prompt = messages[-1].content if len(messages) > 0 else ""
        history = [xinference_message_to_history(message) for message in messages[:-1]]
        response_text = self._generator.chat(
            prompt=prompt,
            chat_history=history,
            generate_config={
                "stream": False,
                "temperature": self.temperature
            }
        )['choices'][0]['message']['content']
        response = ChatResponse(
            message=ChatMessage(
                role=MessageRole.ASSISTANT,
                content=response_text,
            ),
            delta=None,
        )
        return response

    def stream_chat(
            self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResponseGen:
        prompt = messages[-1].content if len(messages) > 0 else ""
        history = [xinference_message_to_history(message) for message in messages[:-1]]
        response_iter = self._generator.chat(
            prompt=prompt,
            chat_history=history,
            generate_config={
                "stream": True,
                "temperature": self.temperature
            }
        )

        def gen() -> ChatResponseGen:
            text = ""
            for c in response_iter:
                delta = c['choices'][0]['delta'].get('content', '')
                text += delta
                yield ChatResponse(
                    message=ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content=text,
                    ),
                    delta=delta,
                )

        return gen()

    def complete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
        response_text = self._generator.chat(
            prompt=prompt,
            chat_history=None,
            generate_config={
                "stream": False,
                "temperature": self.temperature
            }
        )['choices'][0]['message']['content']
        response = CompletionResponse(
            delta=None,
            text=response_text,
        )
        return response

    def stream_complete(self, prompt: str, **kwargs: Any) -> CompletionResponseGen:
        response_iter = self._generator.chat(
            prompt=prompt,
            chat_history=None,
            generate_config={
                "stream": True,
                "temperature": self.temperature
            }
        )

        def gen() -> CompletionResponseGen:
            text = ""
            for c in response_iter:
                delta = c['choices'][0]['delta'].get('content', '')
                text += delta
                yield CompletionResponse(
                    delta=delta,
                    text=text,
                )

        return gen()
