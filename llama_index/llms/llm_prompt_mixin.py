from collections import ChainMap
from typing import (
    Any,
    Callable,
    List,
    Optional,
)

from llama_index.bridge.pydantic import BaseModel, Field
from llama_index.callbacks import CBEventType, EventPayload
from llama_index.llms.base import LLM
from llama_index.llms.types import (
    ChatMessage,
    ChatResponseAsyncGen,
    ChatResponseGen,
    CompletionResponseAsyncGen,
    CompletionResponseGen,
    MessageRole,
)
from llama_index.prompts import BasePromptTemplate, PromptTemplate
from llama_index.types import PydanticProgramMode, TokenAsyncGen, TokenGen


def stream_completion_response_to_tokens(
    completion_response_gen: CompletionResponseGen,
) -> TokenGen:
    """Convert a stream completion response to a stream of tokens."""

    def gen() -> TokenGen:
        for response in completion_response_gen:
            yield response.delta or ""

    return gen()


def stream_chat_response_to_tokens(
    chat_response_gen: ChatResponseGen,
) -> TokenGen:
    """Convert a stream completion response to a stream of tokens."""

    def gen() -> TokenGen:
        for response in chat_response_gen:
            yield response.delta or ""

    return gen()


async def astream_completion_response_to_tokens(
    completion_response_gen: CompletionResponseAsyncGen,
) -> TokenAsyncGen:
    """Convert a stream completion response to a stream of tokens."""

    async def gen() -> TokenAsyncGen:
        async for response in completion_response_gen:
            yield response.delta or ""

    return gen()


async def astream_chat_response_to_tokens(
    chat_response_gen: ChatResponseAsyncGen,
) -> TokenAsyncGen:
    """Convert a stream completion response to a stream of tokens."""

    async def gen() -> TokenAsyncGen:
        async for response in chat_response_gen:
            yield response.delta or ""

    return gen()


class LLMPromptMixin(LLM):
    system_prompt: Optional[str] = Field(description="System prompt for LLM calls.")
    messages_to_prompt: Optional[Callable[[List[ChatMessage]], str]] = Field(
        description="Function to convert a list of messages to an LLM prompt.",
        exclude=True,
    )
    completion_to_prompt: Optional[Callable[[str], str]] = Field(
        description="Function to convert a completion to an LLM prompt.", exclude=True
    )
    pydantic_program_mode: PydanticProgramMode = PydanticProgramMode.DEFAULT

    # deprecated
    query_wrapper_prompt: Optional[str] = Field(
        description="DEPRECATED: Query wrapper prompt."
    )

    def _log_template_data(
        self, prompt: BasePromptTemplate, **prompt_args: Any
    ) -> None:
        template_vars = {
            k: v
            for k, v in ChainMap(prompt.kwargs, prompt_args).items()
            if k in prompt.template_vars
        }
        with self.callback_manager.event(
            CBEventType.TEMPLATING,
            payload={
                EventPayload.TEMPLATE: prompt.get_template(llm=self),
                EventPayload.TEMPLATE_VARS: template_vars,
                EventPayload.SYSTEM_PROMPT: self.system_prompt,
                EventPayload.QUERY_WRAPPER_PROMPT: self.query_wrapper_prompt,
            },
        ):
            pass

    def _get_prompt(self, prompt: BasePromptTemplate, **prompt_args: Any) -> str:
        formatted_prompt = prompt.format(
            llm=self,
            messages_to_prompt=self.messages_to_prompt,
            completion_to_prompt=self.completion_to_prompt,
            **prompt_args,
        )
        return self._extend_prompt(formatted_prompt)

    def _get_messages(
        self, prompt: BasePromptTemplate, **prompt_args: Any
    ) -> List[ChatMessage]:
        messages = prompt.format_messages(llm=self, **prompt_args)
        return self._extend_messages(messages)

    def structured_predict(
        self,
        output_cls: BaseModel,
        prompt: PromptTemplate,
        **prompt_args: Any,
    ) -> BaseModel:
        from llama_index.program.utils import get_program_for_llm

        program = get_program_for_llm(
            output_cls,
            prompt,
            self,
            pydantic_program_mode=self.pydantic_program_mode,
        )

        return program(**prompt_args)

    async def astructured_predict(
        self,
        output_cls: BaseModel,
        prompt: PromptTemplate,
        **prompt_args: Any,
    ) -> BaseModel:
        from llama_index.program.utils import get_program_for_llm

        program = get_program_for_llm(
            output_cls,
            prompt,
            self,
            pydantic_program_mode=self.pydantic_program_mode,
        )

        return await program.acall(**prompt_args)

    def predict(
        self,
        prompt: BasePromptTemplate,
        **prompt_args: Any,
    ) -> str:
        """Predict."""
        self._log_template_data(prompt, **prompt_args)

        if self.metadata.is_chat_model:
            messages = self._get_messages(prompt, **prompt_args)
            chat_response = self.chat(messages)
            output = chat_response.message.content or ""
        else:
            formatted_prompt = self._get_prompt(prompt, **prompt_args)
            response = self.complete(formatted_prompt)
            output = response.text

        return output

    def stream(
        self,
        prompt: BasePromptTemplate,
        **prompt_args: Any,
    ) -> TokenGen:
        """Stream."""
        self._log_template_data(prompt, **prompt_args)

        if self.metadata.is_chat_model:
            messages = self._get_messages(prompt, **prompt_args)
            chat_response = self.stream_chat(messages)
            stream_tokens = stream_chat_response_to_tokens(chat_response)
        else:
            formatted_prompt = self._get_prompt(prompt, **prompt_args)
            stream_response = self.stream_complete(formatted_prompt)
            stream_tokens = stream_completion_response_to_tokens(stream_response)
        return stream_tokens

    async def apredict(
        self,
        prompt: BasePromptTemplate,
        **prompt_args: Any,
    ) -> str:
        """Async predict."""
        self._log_template_data(prompt, **prompt_args)

        if self.metadata.is_chat_model:
            messages = self._get_messages(prompt, **prompt_args)
            chat_response = await self.achat(messages)
            output = chat_response.message.content or ""
        else:
            formatted_prompt = self._get_prompt(prompt, **prompt_args)
            response = await self.acomplete(formatted_prompt)
            output = response.text

        return output

    async def astream(
        self,
        prompt: BasePromptTemplate,
        **prompt_args: Any,
    ) -> TokenAsyncGen:
        """Async stream."""
        self._log_template_data(prompt, **prompt_args)

        if self.metadata.is_chat_model:
            messages = self._get_messages(prompt, **prompt_args)
            chat_response = await self.astream_chat(messages)
            stream_tokens = await astream_chat_response_to_tokens(chat_response)
        else:
            formatted_prompt = self._get_prompt(prompt, **prompt_args)
            stream_response = await self.astream_complete(formatted_prompt)
            stream_tokens = await astream_completion_response_to_tokens(stream_response)
        return stream_tokens

    def _extend_prompt(
        self,
        formatted_prompt: str,
    ) -> str:
        """Add system and query wrapper prompts to base prompt."""
        extended_prompt = formatted_prompt

        if self.system_prompt:
            extended_prompt = self.system_prompt + "\n\n" + extended_prompt

        if self.query_wrapper_prompt:
            extended_prompt = self.query_wrapper_prompt.format(
                query_str=extended_prompt
            )

        return extended_prompt

    def _extend_messages(self, messages: List[ChatMessage]) -> List[ChatMessage]:
        """Add system prompt to chat message list."""
        if self.system_prompt:
            messages = [
                ChatMessage(role=MessageRole.SYSTEM, content=self.system_prompt),
                *messages,
            ]
        return messages
