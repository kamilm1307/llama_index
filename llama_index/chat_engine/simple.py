from typing import List, Optional, Tuple

from llama_index.chat_engine.base import BaseChatEngine
from llama_index.chat_engine.utils import get_chat_history
from llama_index.indices.service_context import ServiceContext
from llama_index.llm_predictor.base import LLMPredictor
from llama_index.prompts.base import Prompt
from llama_index.response.schema import RESPONSE_TYPE

DEFAULT_TMPL = """Assistant is a large language model trained by OpenAI.

Assistant is designed to be able to assist with a wide range of tasks, from answering simple questions to providing in-depth explanations and discussions on a wide range of topics. As a language model, Assistant is able to generate human-like text based on the input it receives, allowing it to engage in natural-sounding conversations and provide responses that are coherent and relevant to the topic at hand.

Assistant is constantly learning and improving, and its capabilities are constantly evolving. It is able to process and understand large amounts of text, and can use this knowledge to provide accurate and informative responses to a wide range of questions. Additionally, Assistant is able to generate its own text based on the input it receives, allowing it to engage in discussions and provide explanations and descriptions on a wide range of topics.

Overall, Assistant is a powerful tool that can help with a wide range of tasks and provide valuable insights and information on a wide range of topics. Whether you need help with a specific question or just want to have a conversation about a particular topic, Assistant is here to assist.

{history}
Human: {message}
Assistant:"""

DEFAULT_PROMPT = Prompt(DEFAULT_TMPL)


def is_chat_model(llm_predictor: LLMPredictor):
    return False


class SimpleChatEngine(BaseChatEngine):
    def __init__(
        self,
        llm_predictor: LLMPredictor,
        prompt: Prompt,
    ) -> None:
        self._llm_predictor = llm_predictor
        self._prompt = prompt
        self._chat_history = []

    @classmethod
    def from_defaults(
        cls,
        service_context: Optional[ServiceContext] = None,
        prompt: Optional[Prompt] = None,
    ):
        service_context = service_context or ServiceContext.from_defaults()
        prompt = prompt or DEFAULT_PROMPT
        return cls(service_context.llm_predictor, prompt=prompt)

    def chat(self, message: str) -> RESPONSE_TYPE:
        if is_chat_model(self._llm_predictor):
            pass
        else:
            history = get_chat_history(self._chat_history)
            response, _ = self._llm_predictor.predict(
                self._prompt,
                history=history,
                message=message,
            )
            return response

    async def achat(self, message: str) -> RESPONSE_TYPE:
        return self.chat(message)
