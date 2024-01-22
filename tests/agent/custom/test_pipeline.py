"""Test query pipeline worker."""


from typing import Any, Dict, Set, Tuple

from llama_index.agent.custom.pipeline_worker import QueryPipelineAgentWorker
from llama_index.agent.runner.base import AgentRunner
from llama_index.agent.types import Task
from llama_index.bridge.pydantic import Field
from llama_index.chat_engine.types import AgentChatResponse
from llama_index.query_pipeline import FnComponent, QueryPipeline
from llama_index.query_pipeline.components.agent import (
    AgentFnComponent,
    AgentInputComponent,
    CustomAgentComponent,
)


def mock_fn(a: str) -> int:
    """Mock function."""
    return a + "3"


def mock_agent_input_fn(task: Task, state: dict) -> dict:
    """Mock agent input function."""
    if "count" not in state:
        state["count"] = 0
        state["max_count"] = 2
        state["input"] = task.input
    return {"a": state["input"]}


def mock_agent_output_fn(
    task: Task, state: dict, output: str
) -> Tuple[bool, AgentChatResponse]:
    state["count"] += 1
    state["input"] = output
    is_done = state["count"] >= state["max_count"]
    return AgentChatResponse(response=str(output)), is_done


def test_qp_agent_fn() -> None:
    """Test query pipeline agent.

    Implement via function components.

    """
    agent_input = AgentInputComponent(fn=mock_agent_input_fn)
    fn_component = FnComponent(fn=mock_fn)
    agent_output = AgentFnComponent(fn=mock_agent_output_fn)
    qp = QueryPipeline(chain=[agent_input, fn_component, agent_output])

    agent_worker = QueryPipelineAgentWorker(pipeline=qp)
    agent_runner = AgentRunner(agent_worker=agent_worker)

    # test create_task
    task = agent_runner.create_task("foo")
    assert task.input == "foo"

    step_output = agent_runner.run_step(task.task_id)
    assert str(step_output.output) == "foo3"
    assert step_output.is_last is False

    step_output = agent_runner.run_step(task.task_id)
    assert str(step_output.output) == "foo33"
    assert step_output.is_last is True


class MyCustomAgentComponent(CustomAgentComponent):
    """Custom agent component."""

    separator: str = Field(default=":", description="Separator")

    def _run_component(self, **kwargs: Any) -> Dict[str, Any]:
        """Run component."""
        return {"output": kwargs["a"] + self.separator + kwargs["a"]}

    @property
    def _input_keys(self) -> Set[str]:
        """Input keys."""
        return {"a"}

    @property
    def _output_keys(self) -> Set[str]:
        """Output keys."""
        return {"output"}


def test_qp_agent_custom() -> None:
    """Test query pipeline agent.

    Implement via `AgentCustomQueryComponent` subclass.

    """
    agent_input = AgentInputComponent(fn=mock_agent_input_fn)
    fn_component = MyCustomAgentComponent(separator="/")
    agent_output = AgentFnComponent(fn=mock_agent_output_fn)
    qp = QueryPipeline(chain=[agent_input, fn_component, agent_output])

    agent_worker = QueryPipelineAgentWorker(pipeline=qp)
    agent_runner = AgentRunner(agent_worker=agent_worker)

    # test create_task
    task = agent_runner.create_task("foo")
    assert task.input == "foo"

    step_output = agent_runner.run_step(task.task_id)
    assert str(step_output.output) == "foo/foo"
    assert step_output.is_last is False

    step_output = agent_runner.run_step(task.task_id)
    assert str(step_output.output) == "foo/foo/foo/foo"
    assert step_output.is_last is True
