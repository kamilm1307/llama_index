import asyncio
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

from llama_index.core.agent.runner.base import AgentRunner, AgentState
from llama_index.core.agent.types import (
    BaseAgentWorker,
    TaskStepOutput,
)
from llama_index.core.bridge.pydantic import BaseModel, Field, ValidationError
from llama_index.core.callbacks import CallbackManager
from llama_index.core.chat_engine.types import (
    AGENT_CHAT_RESPONSE_TYPE,
    ChatResponseMode,
)
from llama_index.core.base.llms.types import ChatMessage
from llama_index.core.llms.llm import LLM
from llama_index.core.memory import BaseMemory, ChatMemoryBuffer
from llama_index.core.memory.types import BaseMemory
from llama_index.core.objects.base import ObjectRetriever
from llama_index.core.prompts import PromptTemplate
from llama_index.core.settings import Settings
from llama_index.core.tools.types import BaseTool
from llama_index.core.instrumentation.events.agent import (
    AgentChatWithStepStartEvent,
    AgentChatWithStepEndEvent,
)
import llama_index.core.instrumentation as instrument

dispatcher = instrument.get_dispatcher(__name__)


class SubTask(BaseModel):
    """A single sub-task in a plan."""

    name: str = Field(..., description="The name of the sub-task.")
    input: str = Field(..., description="The input prompt for the sub-task.")
    expected_output: str = Field(
        ..., description="The expected output of the sub-task."
    )
    dependencies: List[str] = Field(
        ...,
        description="The sub-task names that must be completed before this sub-task.",
    )


class Plan(BaseModel):
    """A series of sub-tasks to accomplish an overall task."""

    sub_tasks: List[SubTask] = Field(..., description="The sub-tasks in the plan.")


class PlannerAgentState(AgentState):
    """Agent state."""

    plan_dict: Dict[str, Plan] = Field(
        default_factory=dict, description="An id-plan lookup."
    )
    completed_sub_tasks: Dict[str, List[SubTask]] = Field(
        default_factory=dict, description="A list of completed sub-tasks for each plan."
    )

    def add_completed_sub_task(self, plan_id: str, sub_task: SubTask) -> None:
        if plan_id not in self.completed_sub_tasks:
            self.completed_sub_tasks[plan_id] = []

        self.completed_sub_tasks[plan_id].append(sub_task)

    def get_next_sub_tasks(self, plan_id: str) -> List[SubTask]:
        next_sub_tasks: List[SubTask] = []
        plan = self.plan_dict[plan_id]

        if plan_id not in self.completed_sub_tasks:
            self.completed_sub_tasks[plan_id] = []

        completed_sub_tasks = self.completed_sub_tasks[plan_id]
        completed_sub_task_names = [sub_task.name for sub_task in completed_sub_tasks]

        for sub_task in plan.sub_tasks:
            dependencies_met = all(
                dep in completed_sub_task_names for dep in sub_task.dependencies
            )

            if sub_task.name not in completed_sub_task_names and dependencies_met:
                next_sub_tasks.append(sub_task)
        return next_sub_tasks

    def get_remaining_subtasks(self, plan_id: str) -> List[SubTask]:
        remaining_subtasks = []
        plan = self.plan_dict[plan_id]

        if plan_id not in self.completed_sub_tasks:
            self.completed_sub_tasks[plan_id] = []

        completed_sub_tasks = self.completed_sub_tasks[plan_id]
        completed_sub_task_names = [sub_task.name for sub_task in completed_sub_tasks]

        for sub_task in plan.sub_tasks:
            if sub_task.name not in completed_sub_task_names:
                remaining_subtasks.append(sub_task)
        return remaining_subtasks

    def reset(self) -> None:
        """Reset."""
        self.task_dict = {}
        self.completed_sub_tasks = {}
        self.plan_dict = {}


DEFAULT_INITIAL_PLAN_PROMPT = """\
Think step-by-step. Given a task and a set of tools, create a comprehesive, end-to-end plan to accomplish the task.
Keep in mind not every task needs to be decomposed into multiple sub-tasks if it is simple enough.
The plan should end with a sub-task that satisfies the overall task.

The tools available are:
{tools_str}

Overall Task: {task}
"""

DEFAULT_PLAN_REFINE_PROMPT = """\
Think step-by-step. Given an overall task, a set of tools, and completed sub-tasks, update (if needed) the remaining sub-tasks so that the overall task can still be completed.
The plan should end with a sub-task that satisfies the overall task.
If the remaining sub-tasks are sufficient, you can skip this step.

The tools available are:
{tools_str}

Overall Task:
{task}

Completed Sub-Tasks + Outputs:
{completed_outputs}

Remaining Sub-Tasks:
{remaining_sub_tasks}
"""


class StructuredPlannerAgent(AgentRunner):
    """Structured Planner Agent runner.

    Top-level agent orchestrator that can create tasks, run each step in a task,
    or run a task e2e. Stores state and keeps track of tasks.

    Args:
        agent_worker (BaseAgentWorker): step executor
        chat_history (Optional[List[ChatMessage]], optional): chat history. Defaults to None.
        state (Optional[AgentState], optional): agent state. Defaults to None.
        memory (Optional[BaseMemory], optional): memory. Defaults to None.
        llm (Optional[LLM], optional): LLM. Defaults to None.
        callback_manager (Optional[CallbackManager], optional): callback manager. Defaults to None.
        init_task_state_kwargs (Optional[dict], optional): init task state kwargs. Defaults to None.

    """

    def __init__(
        self,
        agent_worker: BaseAgentWorker,
        tools: Optional[List[BaseTool]] = None,
        tool_retriever: Optional[ObjectRetriever[BaseTool]] = None,
        chat_history: Optional[List[ChatMessage]] = None,
        state: Optional[PlannerAgentState] = None,
        memory: Optional[BaseMemory] = None,
        llm: Optional[LLM] = None,
        initial_plan_prompt: str = DEFAULT_INITIAL_PLAN_PROMPT,
        plan_refine_prompt: str = DEFAULT_PLAN_REFINE_PROMPT,
        callback_manager: Optional[CallbackManager] = None,
        init_task_state_kwargs: Optional[dict] = None,
        delete_task_on_finish: bool = False,
        default_tool_choice: str = "auto",
        verbose: bool = False,
    ) -> None:
        """Initialize."""
        self.agent_worker = agent_worker
        self.state = state or PlannerAgentState()
        self.memory = memory or ChatMemoryBuffer.from_defaults(chat_history, llm=llm)
        self.tools = tools
        self.tool_retriever = tool_retriever
        self.llm = llm or Settings.llm
        self.initial_plan_prompt = initial_plan_prompt
        self.plan_refine_prompt = plan_refine_prompt

        # get and set callback manager
        if callback_manager is not None:
            self.agent_worker.set_callback_manager(callback_manager)
            self.callback_manager = callback_manager
        else:
            # TODO: This is *temporary*
            # Stopgap before having a callback on the BaseAgentWorker interface.
            # Doing that requires a bit more refactoring to make sure existing code
            # doesn't break.
            if hasattr(self.agent_worker, "callback_manager"):
                self.callback_manager = (
                    self.agent_worker.callback_manager or CallbackManager()
                )
            else:
                self.callback_manager = Settings.callback_manager
        self.init_task_state_kwargs = init_task_state_kwargs or {}
        self.delete_task_on_finish = delete_task_on_finish
        self.default_tool_choice = default_tool_choice
        self.verbose = verbose

    def get_tools(self, input: str) -> List[BaseTool]:
        """Get tools."""
        if self.tools is not None:
            return self.tools
        if self.tool_retriever is not None:
            return self.tool_retriever.retrieve(input)
        raise ValueError("No tools provided or retriever set.")

    def create_tasks(self, input: str, **kwargs: Any) -> str:
        """Create a plan to execute a set of tasks."""
        tools = self.get_tools(input)
        tools_str = ""
        for tool in tools:
            tools_str += tool.metadata.name + ": " + tool.metadata.description + "\n"

        prompt = self.initial_plan_prompt.format(tools_str=tools_str, task=input)

        try:
            plan = self.llm.structured_predict(
                Plan,
                PromptTemplate(prompt),
            )
        except (ValueError, ValidationError):
            # likely no complex plan predicted
            # default to a single task plan
            if self.verbose:
                print("No complex plan predicted. Defaulting to a single task plan.")
            plan = Plan(
                sub_tasks=[
                    SubTask(
                        name="default", input=input, expected_output="", dependencies=[]
                    )
                ]
            )

        if self.verbose:
            print(f"=== Initial plan ===")
            for sub_task in plan.sub_tasks:
                print(
                    f"{sub_task.name}:\n{sub_task.input} -> {sub_task.expected_output}\ndeps: {sub_task.dependencies}\n\n"
                )

        plan_id = str(uuid.uuid4())
        self.state.plan_dict[plan_id] = plan

        for sub_task in plan.sub_tasks:
            self.create_task(sub_task.input, task_id=sub_task.name)

        return plan_id

    async def acreate_tasks(self, input: str, **kwargs: Any) -> str:
        """Create a plan to execute a set of tasks."""
        tools = self.get_tools(input)
        tools_str = ""
        for tool in tools:
            tools_str += tool.metadata.name + ": " + tool.metadata.description + "\n"

        prompt = self.initial_plan_prompt.format(tools_str=tools_str, task=input)

        try:
            plan = await self.llm.astructured_predict(
                Plan,
                PromptTemplate(prompt),
            )
        except (ValueError, ValidationError):
            # likely no complex plan predicted
            # default to a single task plan
            if self.verbose:
                print("No complex plan predicted. Defaulting to a single task plan.")
            plan = Plan(
                sub_tasks=[
                    SubTask(
                        name="default", input=input, expected_output="", dependencies=[]
                    )
                ]
            )

        if self.verbose:
            print(f"=== Initial plan ===")
            for sub_task in plan.sub_tasks:
                print(
                    f"{sub_task.name}:\n{sub_task.input} -> {sub_task.expected_output}\ndeps: {sub_task.dependencies}\n\n"
                )

        plan_id = str(uuid.uuid4())
        self.state.plan_dict[plan_id] = plan

        for sub_task in plan.sub_tasks:
            self.create_task(sub_task.input, task_id=sub_task.name)

        return plan_id

    def get_refine_plan_prompt(
        self,
        plan_id: str,
        task: str,
        completed_sub_task_pairs: List[Tuple[SubTask, AGENT_CHAT_RESPONSE_TYPE]],
    ) -> str:
        """Get the refine plan prompt."""
        # gather completed sub-tasks and response pairs
        completed_pairs_str = []
        for sub_task, response in completed_sub_task_pairs:
            completed_pairs_str.append(f"{sub_task.name} -> {response!s}")
        completed_outputs_str = "\n".join(completed_pairs_str)

        # get a string for the remaining sub-tasks
        remaining_sub_tasks = self.state.get_remaining_subtasks(plan_id)
        remaining_sub_tasks_str = "\n".join(
            [str(sub_task) for sub_task in remaining_sub_tasks]
        )

        # get the tools string
        tools = self.get_tools(remaining_sub_tasks_str)
        tools_str = ""
        for tool in tools:
            tools_str += tool.metadata.name + ": " + tool.metadata.description + "\n"

        # predict a refined plan
        return self.plan_refine_prompt.format(
            tools_str=tools_str,
            task=task,
            completed_outputs=completed_outputs_str,
            remaining_sub_tasks=remaining_sub_tasks_str,
        )

    def refine_plan(
        self,
        plan_id: str,
        task: str,
        completed_sub_task_pairs: List[Tuple[SubTask, AGENT_CHAT_RESPONSE_TYPE]],
    ) -> None:
        """Refine a plan."""
        refine_str = self.get_refine_plan_prompt(
            plan_id, task, completed_sub_task_pairs
        )

        try:
            new_plan = self.llm.structured_predict(Plan, PromptTemplate(refine_str))

            # delete any tasks from the previous plan
            for sub_task in self.state.plan_dict[plan_id].sub_tasks:
                self.delete_task(sub_task.name)

            # update state with new plan
            self.state.plan_dict[plan_id] = new_plan
            for sub_task in new_plan.sub_tasks:
                self.create_task(sub_task.input, task_id=sub_task.name)

            if self.verbose:
                print(f"=== Refined plan ===")
                for sub_task in new_plan.sub_tasks:
                    print(
                        f"{sub_task.name}:\n{sub_task.input} -> {sub_task.expected_output}\ndeps: {sub_task.dependencies}\n\n"
                    )
        except (ValueError, ValidationError):
            # likely no new plan predicted
            return

    async def arefine_plan(
        self,
        plan_id: str,
        task: str,
        completed_sub_task_pairs: List[Tuple[SubTask, AGENT_CHAT_RESPONSE_TYPE]],
    ) -> None:
        """Refine a plan."""
        refine_str = self.get_refine_plan_prompt(
            plan_id, task, completed_sub_task_pairs
        )

        try:
            new_plan = await self.llm.astructured_predict(
                Plan, PromptTemplate(refine_str)
            )

            # delete any tasks from the previous plan
            for sub_task in self.state.plan_dict[plan_id].sub_tasks:
                self.delete_task(sub_task.name)

            # update state with new plan
            self.state.plan_dict[plan_id] = new_plan
            for sub_task in new_plan.sub_tasks:
                self.create_task(sub_task.input, task_id=sub_task.name)

            if self.verbose:
                print(f"=== Refined plan ===")
                for sub_task in new_plan.sub_tasks:
                    print(
                        f"{sub_task.name}:\n{sub_task.input} -> {sub_task.expected_output}\ndeps: {sub_task.dependencies}\n\n"
                    )

        except (ValueError, ValidationError):
            # likely no new plan predicted
            return

    def run_task(
        self,
        task_id: str,
        mode: ChatResponseMode = ChatResponseMode.WAIT,
        tool_choice: Union[str, dict] = "auto",
    ) -> TaskStepOutput:
        """Run a task."""
        while True:
            # pass step queue in as argument, assume step executor is stateless
            cur_step_output = self._run_step(
                task_id, mode=mode, tool_choice=tool_choice
            )

            if cur_step_output.is_last:
                result_output = cur_step_output
                break

            # ensure tool_choice does not cause endless loops
            tool_choice = "auto"

        return self.finalize_response(
            task_id,
            result_output,
        )

    async def arun_task(
        self,
        task_id: str,
        mode: ChatResponseMode = ChatResponseMode.WAIT,
        tool_choice: Union[str, dict] = "auto",
    ) -> TaskStepOutput:
        """Run a task."""
        while True:
            # pass step queue in as argument, assume step executor is stateless
            cur_step_output = await self._arun_step(
                task_id, mode=mode, tool_choice=tool_choice
            )

            if cur_step_output.is_last:
                result_output = cur_step_output
                break

            # ensure tool_choice does not cause endless loops
            tool_choice = "auto"

        return self.finalize_response(
            task_id,
            result_output,
        )

    @dispatcher.span
    def _chat(
        self,
        message: str,
        chat_history: Optional[List[ChatMessage]] = None,
        tool_choice: Union[str, dict] = "auto",
        mode: ChatResponseMode = ChatResponseMode.WAIT,
    ) -> AGENT_CHAT_RESPONSE_TYPE:
        """Chat with step executor."""
        dispatch_event = dispatcher.get_dispatch_event()

        if chat_history is not None:
            self.memory.set(chat_history)

        # create initial set of tasks
        plan_id = self.create_tasks(message)

        results = []
        completed_pairs = []
        dispatch_event(AgentChatWithStepStartEvent())
        while True:
            # EXIT CONDITION: check if all sub-tasks are completed
            next_sub_tasks = self.state.get_next_sub_tasks(plan_id)
            if len(next_sub_tasks) == 0:
                break

            jobs = [
                self.arun_task(sub_task.name, mode=mode, tool_choice=tool_choice)
                for sub_task in next_sub_tasks
            ]
            results = asyncio.run(asyncio.gather(*jobs))

            # gather completed sub-tasks and response pairs
            for sub_task, response in zip(next_sub_tasks, results):
                completed_pairs.append((sub_task, response))
                self.state.add_completed_sub_task(plan_id, sub_task)

            # EXIT CONDITION: check if all sub-tasks are completed now
            # LLMs have a tendency to add more tasks, so we end if there are no more tasks
            next_sub_tasks = self.state.get_next_sub_tasks(plan_id)
            if len(next_sub_tasks) == 0:
                break

            # refine the plan
            self.refine_plan(plan_id, message, completed_pairs)

        dispatch_event(AgentChatWithStepEndEvent())
        return results[-1]

    @dispatcher.span
    async def _achat(
        self,
        message: str,
        chat_history: Optional[List[ChatMessage]] = None,
        tool_choice: Union[str, dict] = "auto",
        mode: ChatResponseMode = ChatResponseMode.WAIT,
    ) -> AGENT_CHAT_RESPONSE_TYPE:
        """Chat with step executor."""
        dispatch_event = dispatcher.get_dispatch_event()

        if chat_history is not None:
            self.memory.set(chat_history)

        # create initial set of tasks
        plan_id = self.create_tasks(message)

        results = []
        completed_pairs = []
        dispatch_event(AgentChatWithStepStartEvent())
        while True:
            # EXIT CONDITION: check if all sub-tasks are completed
            next_sub_tasks = self.state.get_next_sub_tasks(plan_id)
            if len(next_sub_tasks) == 0:
                break

            jobs = [
                self.arun_task(sub_task.name, mode=mode, tool_choice=tool_choice)
                for sub_task in next_sub_tasks
            ]
            results = await asyncio.gather(*jobs)

            # gather completed sub-tasks and response pairs
            for sub_task, response in zip(next_sub_tasks, results):
                completed_pairs.append((sub_task, response))
                self.state.add_completed_sub_task(plan_id, sub_task)

            # EXIT CONDITION: check if all sub-tasks are completed now
            # LLMs have a tendency to add more tasks, so we end if there are no more tasks
            next_sub_tasks = self.state.get_next_sub_tasks(plan_id)
            if len(next_sub_tasks) == 0:
                break

            # refine the plan
            await self.arefine_plan(plan_id, message, completed_pairs)

        dispatch_event(AgentChatWithStepEndEvent())
        return results[-1]
