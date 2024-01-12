from typing import Any, Optional, Sequence

from tonic_validate.classes.benchmark import BenchmarkItem
from tonic_validate.classes.llm_response import LLMResponse
from tonic_validate.metrics.augmentation_accuracy_metric import (
    AugmentationAccuracyMetric,
)
from tonic_validate.services.openai_service import OpenAIService

from llama_index.evaluation.base import BaseEvaluator, EvaluationResult
from llama_index.prompts.mixin import PromptDictType, PromptMixinType


class AugmentationAccuracyEvaluator(BaseEvaluator):
    """Tonic Validate's augmentation accuracy metric.

    See https://docs.tonic.ai/validate/ for more details.

    Args:
        openai_service(OpenAIService): The OpenAI service to use. Specifies the chat
            completion model to use as the LLM evaluator. Defaults to "gpt-4".
    """

    def __init__(self, openai_service: OpenAIService = OpenAIService("gpt-4")):
        self.openai_service = openai_service
        self.metric = AugmentationAccuracyMetric()

    async def aevaluate(
        self,
        query: Optional[str] = None,
        response: Optional[str] = None,
        contexts: Optional[Sequence[str]] = None,
        **kwargs: Any
    ) -> EvaluationResult:
        benchmark_item = BenchmarkItem(question=query)

        llm_response = LLMResponse(
            llm_answer=response,
            llm_context_list=contexts,
            benchmark_item=benchmark_item,
        )

        score = self.metric.score(llm_response, self.openai_service)

        return EvaluationResult(
            query=query, contexts=contexts, response=response, score=score
        )

    def _get_prompts(self) -> PromptDictType:
        return {}

    def _get_prompt_modules(self) -> PromptMixinType:
        return {}

    def _update_prompts(self, prompts_dict: PromptDictType) -> None:
        return
