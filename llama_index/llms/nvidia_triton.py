import abc
import json
import queue
import random
import time
from functools import partial
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Type,
    Union,
)

if TYPE_CHECKING:
    import tritonclient.grpc as grpcclient
    import tritonclient.http as httpclient

import numpy as np

from llama_index.bridge.pydantic import Field, PrivateAttr
from llama_index.callbacks import CallbackManager
from llama_index.llms.base import (
    LLM,
    ChatMessage,
    ChatResponse,
    ChatResponseAsyncGen,
    ChatResponseGen,
    CompletionResponse,
    CompletionResponseAsyncGen,
    CompletionResponseGen,
    LLMMetadata,
    llm_chat_callback,
)
from llama_index.llms.generic_utils import (
    completion_to_chat_decorator,
)

STOP_WORDS = ["</s>"]
RANDOM_SEED = 0

DEFAULT_SERVER_URL = "localhost:8001"
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 60.0
DEFAULT_MODEL = "ensemble"
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 0
DEFAULT_TOP_K = 1.0
DEFAULT_MAX_TOKENS = 100
DEFAULT_BEAM_WIDTH = 1
DEFAULT_REPTITION_PENALTY = 1.0
DEFAULT_LENGTH_PENALTY = 1.0
DEFAULT_REUSE_CLIENT = True
DEFAULT_TRITON_LOAD_MODEL = True


class NvidiaTriton(LLM):
    server_url: str = Field(
        default=DEFAULT_SERVER_URL,
        description="The URL of the Triton inference server to use.",
    )
    model_name: str = Field(
        default=DEFAULT_MODEL,
        description="The name of the Triton hosted model this client should use",
    )
    temperature: Optional[float] = Field(
        default=DEFAULT_TEMPERATURE, description="Temperature to use for sampling"
    )
    top_p: Optional[float] = Field(
        default=DEFAULT_TOP_P, description="The top-p value to use for sampling"
    )
    top_k: Optional[float] = Field(
        default=DEFAULT_TOP_K, description="The top k value to use for sampling"
    )
    tokens: Optional[int] = Field(
        default=DEFAULT_MAX_TOKENS,
        description="The maximum number of tokens to generate.",
    )
    beam_width: Optional[int] = Field(
        default=DEFAULT_BEAM_WIDTH, description="Last n number of tokens to penalize"
    )
    repetition_penalty: Optional[float] = Field(
        default=DEFAULT_REPTITION_PENALTY,
        description="Last n number of tokens to penalize",
    )
    length_penalty: Optional[float] = Field(
        default=DEFAULT_LENGTH_PENALTY,
        description="The penalty to apply repeated tokens",
    )
    max_retries: Optional[int] = Field(
        default=DEFAULT_MAX_RETRIES,
        description="Maximum number of attempts to retry Triton client invocation before erroring",
    )
    timeout: Optional[float] = Field(
        default=DEFAULT_TIMEOUT,
        description="Maximum time (seconds) allowed for a Triton client call before erroring",
    )
    reuse_client: Optional[bool] = Field(
        default=DEFAULT_REUSE_CLIENT,
        description="True for reusing the same client instance between invocations",
    )
    triton_load_model_call: Optional[bool] = Field(
        default=DEFAULT_TRITON_LOAD_MODEL,
        description="True if a Triton load model API call should be made before using the client",
    )

    _client: Optional[Any] = PrivateAttr()

    def __init__(
        self,
        server_url: str = DEFAULT_SERVER_URL,
        model: str = DEFAULT_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        top_p: float = DEFAULT_TOP_P,
        top_k: float = DEFAULT_TOP_K,
        tokens: Optional[int] = DEFAULT_MAX_TOKENS,
        beam_width: int = DEFAULT_BEAM_WIDTH,
        repetition_penalty: float = DEFAULT_REPTITION_PENALTY,
        length_penalty: float = DEFAULT_LENGTH_PENALTY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
        reuse_client: bool = DEFAULT_REUSE_CLIENT,
        triton_load_model_call: bool = DEFAULT_TRITON_LOAD_MODEL,
        callback_manager: Optional[CallbackManager] = None,
        additional_kwargs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        additional_kwargs = additional_kwargs or {}

        super().__init__(
            server_url=server_url,
            model=model,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            tokens=tokens,
            beam_width=beam_width,
            repetition_penalty=repetition_penalty,
            length_penalty=length_penalty,
            max_retries=max_retries,
            timeout=timeout,
            reuse_client=reuse_client,
            triton_load_model_call=triton_load_model_call,
            callback_manager=callback_manager,
            additional_kwargs=additional_kwargs,
            **kwargs,
        )

        try:
            self._client = GrpcTritonClient(server_url)
        except ImportError as err:
            raise ImportError(
                "Could not import triton client python package. "
                "Please install it with `pip install tritonclient`."
            ) from err

    @property
    def _get_model_default_parameters(self) -> Dict[str, Any]:
        return {
            "tokens": self.tokens,
            "top_k": self.top_k,
            "top_p": self.top_p,
            "temperature": self.temperature,
            "repetition_penalty": self.repetition_penalty,
            "length_penalty": self.length_penalty,
            "beam_width": self.beam_width,
        }

    @property
    def _invocation_params(self, **kwargs: Any) -> Dict[str, Any]:
        return {**self._get_model_default_parameters, **kwargs}

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        """Get all the identifying parameters."""
        return {
            "server_url": self.server_url,
            "model_name": self.model_name,
        }

    def _get_client(self) -> Any:
        """Create or reuse a Triton client connection."""
        if not self.reuse_client:
            return GrpcTritonClient(self.server_url)

        if self._client is None:
            self._client = GrpcTritonClient(self.server_url)
        return self._client

    @property
    def metadata(self) -> LLMMetadata:
        """Gather and return metadata about the user Triton configured LLM model."""
        return LLMMetadata(
            model_name=self.model_name,
        )

    def _complete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
        from tritonclient.utils import InferenceServerException

        client = self._get_client()

        invocation_params = self._get_model_default_parameters
        invocation_params.update(kwargs)
        invocation_params["prompt"] = [[prompt]]
        model_params = self._identifying_params
        model_params.update(kwargs)
        request_id = str(random.randint(1, 9999999))  # nosec

        if self.triton_load_model_call:
            client.load_model(model_params["model_name"])

        result_queue = self._client.request_streaming(
            model_params["model_name"], request_id, **invocation_params
        )

        response = ""
        for token in result_queue:
            if isinstance(token, InferenceServerException):
                self._client.stop_stream(model_params["model_name"], request_id)
                raise token
            response = response + token

        return CompletionResponse(
            text=response,
        )

    def _stream_complete(self, prompt: str, **kwargs: Any) -> CompletionResponseGen:
        """Request a streaming inference session."""
        client = self._get_client()

        def gen() -> CompletionResponseGen:
            invocation_params = self._get_model_default_parameters
            invocation_params.update(kwargs)
            invocation_params["prompt"] = [[prompt]]
            model_params = self._identifying_params
            model_params.update(kwargs)
            request_id = str(random.randint(1, 9999999))  # nosec

            result_queue = client.request_streaming(
                model_params["model_name"], request_id, **invocation_params
            )

            text = ""
            for token in result_queue:
                text = text + token
                yield CompletionResponse(
                    text=text,
                )

        return gen()

    @llm_chat_callback()
    def chat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> ChatResponse:
        chat_fn = completion_to_chat_decorator(self._complete)
        return chat_fn(messages, **kwargs)

    def stream_chat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResponseGen:
        raise NotImplementedError

    def complete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
        return self._complete(prompt, **kwargs)

    def stream_complete(self, prompt: str, **kwargs: Any) -> CompletionResponseGen:
        raise NotImplementedError

    async def achat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResponse:
        raise NotImplementedError

    async def acomplete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
        raise NotImplementedError

    async def astream_chat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResponseAsyncGen:
        raise NotImplementedError

    async def astream_complete(
        self, prompt: str, **kwargs: Any
    ) -> CompletionResponseAsyncGen:
        raise NotImplementedError


class StreamingResponseGenerator(queue.Queue[Optional[str]]):
    """A Generator that provides the inference results from an LLM."""

    def __init__(
        self, client: "GrpcTritonClient", request_id: str, force_batch: bool
    ) -> None:
        """Instantiate the generator class."""
        super().__init__()
        self._client = client
        self.request_id = request_id
        self._batch = force_batch

    def __iter__(self) -> "StreamingResponseGenerator":
        """Return self as a generator."""
        return self

    def __next__(self) -> str:
        """Return the next retrieved token."""
        val = self.get()
        if val is None or val in STOP_WORDS:
            self._stop_stream()
            raise StopIteration
        return val

    def _stop_stream(self) -> None:
        """Drain and shutdown the Triton stream."""
        self._client.stop_stream(
            "tensorrt_llm", self.request_id, signal=not self._batch
        )


class _BaseTritonClient(abc.ABC):
    """An abstraction of the connection to a triton inference server."""

    def __init__(self, server_url: str) -> None:
        """Initialize the client."""
        self._server_url = server_url
        self._client = self._inference_server_client(server_url)

    @property
    @abc.abstractmethod
    def _inference_server_client(
        self,
    ) -> Union[
        Type["grpcclient.InferenceServerClient"],
        Type["httpclient.InferenceServerClient"],
    ]:
        """Return the preferred InferenceServerClient class."""

    @property
    @abc.abstractmethod
    def _infer_input(
        self,
    ) -> Union[Type["grpcclient.InferInput"], Type["httpclient.InferInput"]]:
        """Return the preferred InferInput."""

    @property
    @abc.abstractmethod
    def _infer_output(
        self,
    ) -> Union[
        Type["grpcclient.InferRequestedOutput"], Type["httpclient.InferRequestedOutput"]
    ]:
        """Return the preferred InferRequestedOutput."""

    def load_model(self, model_name: str, timeout: int = 1000) -> None:
        """Load a model into the server."""
        if self._client.is_model_ready(model_name):
            return

        self._client.load_model(model_name)
        t0 = time.perf_counter()
        t1 = t0
        while not self._client.is_model_ready(model_name) and t1 - t0 < timeout:
            t1 = time.perf_counter()

        if not self._client.is_model_ready(model_name):
            raise RuntimeError(f"Failed to load {model_name} on Triton in {timeout}s")

    def get_model_list(self) -> List[str]:
        """Get a list of models loaded in the triton server."""
        res = self._client.get_model_repository_index(as_json=True)
        return [model["name"] for model in res["models"]]

    def get_model_concurrency(self, model_name: str, timeout: int = 1000) -> int:
        """Get the model concurrency."""
        self.load_model(model_name, timeout)
        instances = self._client.get_model_config(model_name, as_json=True)["config"][
            "instance_group"
        ]
        return sum(instance["count"] * len(instance["gpus"]) for instance in instances)

    def _generate_stop_signals(
        self,
    ) -> List[Union["grpcclient.InferInput", "httpclient.InferInput"]]:
        """Generate the signal to stop the stream."""
        inputs = [
            self._infer_input("input_ids", [1, 1], "INT32"),
            self._infer_input("input_lengths", [1, 1], "INT32"),
            self._infer_input("request_output_len", [1, 1], "UINT32"),
            self._infer_input("stop", [1, 1], "BOOL"),
        ]
        inputs[0].set_data_from_numpy(np.empty([1, 1], dtype=np.int32))
        inputs[1].set_data_from_numpy(np.zeros([1, 1], dtype=np.int32))
        inputs[2].set_data_from_numpy(np.array([[0]], dtype=np.uint32))
        inputs[3].set_data_from_numpy(np.array([[True]], dtype="bool"))
        return inputs

    def _generate_outputs(
        self,
    ) -> List[
        Union["grpcclient.InferRequestedOutput", "httpclient.InferRequestedOutput"]
    ]:
        """Generate the expected output structure."""
        return [self._infer_output("text_output")]

    def _prepare_tensor(
        self, name: str, input_data: Any
    ) -> Union["grpcclient.InferInput", "httpclient.InferInput"]:
        """Prepare an input data structure."""
        from tritonclient.utils import np_to_triton_dtype

        t = self._infer_input(
            name, input_data.shape, np_to_triton_dtype(input_data.dtype)
        )
        t.set_data_from_numpy(input_data)
        return t

    def _generate_inputs(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        prompt: str,
        tokens: int = 300,
        temperature: float = 1.0,
        top_k: float = 1,
        top_p: float = 0,
        beam_width: int = 1,
        repetition_penalty: float = 1,
        length_penalty: float = 1.0,
        stream: bool = True,
    ) -> List[Union["grpcclient.InferInput", "httpclient.InferInput"]]:
        """Create the input for the triton inference server."""
        query = np.array(prompt).astype(object)
        request_output_len = np.array([tokens]).astype(np.uint32).reshape((1, -1))
        runtime_top_k = np.array([top_k]).astype(np.uint32).reshape((1, -1))
        runtime_top_p = np.array([top_p]).astype(np.float32).reshape((1, -1))
        temperature_array = np.array([temperature]).astype(np.float32).reshape((1, -1))
        len_penalty = np.array([length_penalty]).astype(np.float32).reshape((1, -1))
        repetition_penalty_array = (
            np.array([repetition_penalty]).astype(np.float32).reshape((1, -1))
        )
        random_seed = np.array([RANDOM_SEED]).astype(np.uint64).reshape((1, -1))
        beam_width_array = np.array([beam_width]).astype(np.uint32).reshape((1, -1))
        streaming_data = np.array([[stream]], dtype=bool)

        return [
            self._prepare_tensor("text_input", query),
            self._prepare_tensor("max_tokens", request_output_len),
            self._prepare_tensor("top_k", runtime_top_k),
            self._prepare_tensor("top_p", runtime_top_p),
            self._prepare_tensor("temperature", temperature_array),
            self._prepare_tensor("length_penalty", len_penalty),
            self._prepare_tensor("repetition_penalty", repetition_penalty_array),
            self._prepare_tensor("random_seed", random_seed),
            self._prepare_tensor("beam_width", beam_width_array),
            self._prepare_tensor("stream", streaming_data),
        ]

    def _trim_batch_response(self, result_str: str) -> str:
        """Trim the resulting response from a batch request by removing provided prompt and extra generated text."""
        # extract the generated part of the prompt
        split = result_str.split("[/INST]", 1)
        generated = split[-1]
        end_token = generated.find("</s>")
        if end_token == -1:
            return generated
        return generated[:end_token].strip()


class GrpcTritonClient(_BaseTritonClient):
    """GRPC connection to a triton inference server."""

    @property
    def _inference_server_client(
        self,
    ) -> Type["grpcclient.InferenceServerClient"]:
        """Return the preferred InferenceServerClient class."""
        import tritonclient.grpc as grpcclient

        return grpcclient.InferenceServerClient  # type: ignore

    @property
    def _infer_input(self) -> Type["grpcclient.InferInput"]:
        """Return the preferred InferInput."""
        import tritonclient.grpc as grpcclient

        return grpcclient.InferInput  # type: ignore

    @property
    def _infer_output(
        self,
    ) -> Type["grpcclient.InferRequestedOutput"]:
        """Return the preferred InferRequestedOutput."""
        import tritonclient.grpc as grpcclient

        return grpcclient.InferRequestedOutput  # type: ignore

    def _send_stop_signals(self, model_name: str, request_id: str) -> None:
        """Send the stop signal to the Triton Inference server."""
        stop_inputs = self._generate_stop_signals()
        self._client.async_stream_infer(
            model_name,
            stop_inputs,
            request_id=request_id,
            parameters={"Streaming": True},
        )

    @staticmethod
    def _process_result(result: Dict[str, str]) -> str:
        """Post-process the result from the server."""
        import google.protobuf.json_format
        import tritonclient.grpc as grpcclient
        from tritonclient.grpc.service_pb2 import ModelInferResponse

        message = ModelInferResponse()
        generated_text: str = ""
        google.protobuf.json_format.Parse(json.dumps(result), message)
        infer_result = grpcclient.InferResult(message)
        np_res = infer_result.as_numpy("text_output")

        generated_text = ""
        if np_res is not None:
            generated_text = "".join([token.decode() for token in np_res])

        return generated_text

    def _stream_callback(
        self,
        result_queue: queue.Queue[Union[Optional[Dict[str, str]], str]],
        force_batch: bool,
        result: Any,
        error: str,
    ) -> None:
        """Add streamed result to queue."""
        if error:
            result_queue.put(error)
        else:
            response_raw = result.get_response(as_json=True)
            if "outputs" in response_raw:
                # the very last response might have no output, just the final flag
                response = self._process_result(response_raw)
                if force_batch:
                    response = self._trim_batch_response(response)

                if response in STOP_WORDS:
                    result_queue.put(None)
                else:
                    result_queue.put(response)

            if response_raw["parameters"]["triton_final_response"]["bool_param"]:
                # end of the generation
                result_queue.put(None)

    # pylint: disable-next=too-many-arguments
    def _send_prompt_streaming(
        self,
        model_name: str,
        request_inputs: Any,
        request_outputs: Optional[Any],
        request_id: str,
        result_queue: StreamingResponseGenerator,
        force_batch: bool = False,
    ) -> None:
        """Send the prompt and start streaming the result."""
        self._client.start_stream(
            callback=partial(self._stream_callback, result_queue, force_batch)
        )
        self._client.async_stream_infer(
            model_name=model_name,
            inputs=request_inputs,
            outputs=request_outputs,
            request_id=request_id,
        )

    def request_streaming(
        self,
        model_name: str,
        request_id: Optional[str] = None,
        force_batch: bool = False,
        **params: Any,
    ) -> StreamingResponseGenerator:
        """Request a streaming connection."""
        if not self._client.is_model_ready(model_name):
            raise RuntimeError("Cannot request streaming, model is not loaded")

        if not request_id:
            request_id = str(random.randint(1, 9999999))  # nosec

        result_queue = StreamingResponseGenerator(self, request_id, force_batch)
        inputs = self._generate_inputs(stream=not force_batch, **params)
        outputs = self._generate_outputs()
        self._send_prompt_streaming(
            model_name,
            inputs,
            outputs,
            request_id,
            result_queue,
            force_batch,
        )
        return result_queue

    def stop_stream(
        self, model_name: str, request_id: str, signal: bool = True
    ) -> None:
        """Close the streaming connection."""
        if signal:
            self._send_stop_signals(model_name, request_id)
        self._client.stop_stream()
