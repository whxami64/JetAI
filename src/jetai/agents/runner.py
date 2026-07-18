"""Shared plumbing to run one specialist agent with tracing and a structured answer."""

from __future__ import annotations

from typing import TypeVar

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr

from jetai.agents.config import AgentSettings
from jetai.agents.tracing import JsonlTracer

ResponseT = TypeVar("ResponseT", bound=BaseModel)

DEFAULT_RECURSION_LIMIT = 40


def chat_model(settings: AgentSettings) -> ChatOpenAI:
    """The suite's chat model; one place to change provider parameters.

    ``use_responses_api``: gpt-5.x models only support function tools together
    with reasoning through the Responses API, not /v1/chat/completions.
    """
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=SecretStr(settings.openai_api_key),
        use_responses_api=True,
    )


def run_structured_agent(
    *,
    settings: AgentSettings,
    name: str,
    brief: str,
    tools: list[BaseTool],
    response_format: type[ResponseT],
    tracer: JsonlTracer,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
) -> ResponseT:
    """Run one ``create_agent`` specialist on a fresh, self-contained brief.

    No shared message history: the brief must carry everything the agent needs
    (context isolation between specialists). The enforced ``response_format``
    guarantees the final answer parses into the given pydantic model.
    """
    agent = create_agent(
        chat_model(settings),
        tools=tools,
        response_format=response_format,
        name=name,
    )
    state = agent.invoke(
        {"messages": [HumanMessage(brief)]},
        config={
            "callbacks": [tracer],
            "run_name": name,
            "recursion_limit": recursion_limit,
        },
    )
    structured = state.get("structured_response")
    if not isinstance(structured, response_format):
        raise RuntimeError(f"Agent {name!r} returned no structured response.")
    return structured
