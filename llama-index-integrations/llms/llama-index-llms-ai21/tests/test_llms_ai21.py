from llama_index.core.base.llms.base import BaseLLM
from llama_index.llms.ai21 import AI21


def test_text_inference_embedding_class():
    names_of_base_classes = [b.__name__ for b in AI21.__mro__]
    assert BaseLLM.__name__ in names_of_base_classes
