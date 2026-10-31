"""Shared mock-LLM scaffolding for agentic tests.

One source of truth for the fake OpenAI-compatible transport contract, used
by both the unit and integration suites so the two cannot drift apart.
"""

import json
from typing import Any

UNSAT_PROGRAM = "(declare-const x Int)\n(assert (> x 5))\n(assert (< x 3))\n(check-sat)"
SAT_PROGRAM = "(declare-const x Int)\n(assert (> x 5))\n(check-sat)"
BROKEN_PROGRAM = "(assert (> y 5))\n(check-sat)"


def tool_call(name: str, args: dict[str, Any], call_id: str = "call_1") -> dict[str, Any]:
    """A well-formed tool call in the OpenAI response shape."""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def raw_tool_call(name: str, arguments: str, call_id: str = "call_1") -> dict[str, Any]:
    """A tool call with a raw (possibly malformed/truncated) arguments string."""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def response(
    content: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str = "stop",
) -> dict[str, Any]:
    """A chat-completions response dict in the shape the solver consumes."""
    msg: dict[str, Any] = {"content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
        finish_reason = "tool_calls"
    return {
        "choices": [{"message": msg, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


class MockClient:
    """OpenAI-compatible client returning a scripted sequence of responses.

    Records a deep copy of every request's kwargs (the solver mutates the
    messages list in place between calls, so each call's payload is
    snapshotted at call time). Raises when the script runs out unless
    ``cycle=True``, in which case the sequence repeats - useful for batch
    pipelines issuing one trajectory per sample.
    """

    def __init__(self, responses: list[dict[str, Any]], cycle: bool = False) -> None:
        self._responses = list(responses)
        self._cycle = cycle
        self._pos = 0
        self.calls: list[dict[str, Any]] = []

        outer = self

        class _Completions:
            def create(self, **kwargs: Any) -> dict[str, Any]:
                outer.calls.append(json.loads(json.dumps(kwargs, default=str)))
                if outer._cycle:
                    resp = outer._responses[outer._pos % len(outer._responses)]
                    outer._pos += 1
                    return resp
                if not outer._responses:
                    raise RuntimeError("MockClient ran out of scripted responses")
                return outer._responses.pop(0)

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()
