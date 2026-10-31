"""Common trajectory representation for agent guardrailing.

TauBench and tau2-bench record agent trajectories in different shapes:

- **tau-bench** saves a top-level JSON *list* of ``EnvRunResult`` dicts whose
  ``traj`` field is a raw OpenAI chat-message list - tool-call ``arguments``
  are JSON *strings* under ``message["tool_calls"][i]["function"]["arguments"]``
  (the OpenAI wire format).
- **tau2-bench** saves a ``Results`` dict whose ``simulations[].messages``
  carry flat tool calls ``{id, name, arguments, requestor}`` with ``arguments``
  already parsed to a *dict*, and tool results as ``{role: "tool", id, ...}``
  messages paired by id. The user simulator can also call tools (telecom),
  hence ``requestor``.

This module normalizes both - plus plain OpenAI message lists from a live
agent - into one :class:`Trajectory` IR that the guardrail verifies against a
domain policy. Loaders never mutate the source files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "ToolCallRecord",
    "Trajectory",
    "load_taubench_trajectories",
    "load_tau2_trajectories",
    "trajectory_from_messages",
    "render_trajectory",
    "render_tool_call",
]


@dataclass
class ToolCallRecord:
    """One tool call observed in a trajectory, with its recorded result."""

    name: str
    arguments: dict[str, Any]
    call_id: str = ""
    # "assistant" for agent-side calls; tau2's user simulator can also call
    # tools (telecom device actions), recorded as "user".
    requestor: str = "assistant"
    # Index of the emitting message within Trajectory.messages.
    message_index: int | None = None
    # Content of the paired tool-result message, when one was recorded.
    result: str | None = None


@dataclass
class Trajectory:
    """A normalized agent trajectory: the transcript plus its tool calls.

    ``messages`` keeps the OpenAI-ish shape ({role, content, tool_calls?}) so
    nothing is lost; ``tool_calls`` is the extracted, argument-parsed view the
    guardrail reasons over. ``reward`` preserves the benchmark's own score so
    guardrail verdicts can be compared against ground truth.
    """

    source: str  # "taubench" | "tau2" | "openai"
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    task_id: Any = None
    trial: int | None = None
    reward: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """Best-effort parse of tool-call arguments into a dict, never raising."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}
        return parsed if isinstance(parsed, dict) else {"_value": parsed}
    return {} if raw is None else {"_value": raw}


def _extract_openai_tool_calls(messages: list[dict[str, Any]]) -> list[ToolCallRecord]:
    """Pull ToolCallRecords out of an OpenAI-format message list.

    Tool results are paired by ``tool_call_id``; a result that never arrived
    (truncated trajectory) simply leaves ``result=None``.
    """
    records: list[ToolCallRecord] = []
    by_id: dict[str, ToolCallRecord] = {}
    for i, msg in enumerate(messages):
        role = msg.get("role")
        if role == "assistant":
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                record = ToolCallRecord(
                    name=fn.get("name") or "",
                    arguments=_parse_arguments(fn.get("arguments")),
                    call_id=tc.get("id") or "",
                    requestor="assistant",
                    message_index=i,
                )
                records.append(record)
                if record.call_id:
                    by_id[record.call_id] = record
        elif role == "tool":
            caller = by_id.get(msg.get("tool_call_id") or "")
            if caller is not None and caller.result is None:
                caller.result = str(msg.get("content") or "")
    return records


def _extract_tau2_tool_calls(messages: list[dict[str, Any]]) -> list[ToolCallRecord]:
    """Pull ToolCallRecords out of tau2's flat message format."""
    records: list[ToolCallRecord] = []
    by_id: dict[str, ToolCallRecord] = {}
    for i, msg in enumerate(messages):
        role = msg.get("role")
        if role in ("assistant", "user"):
            for tc in msg.get("tool_calls") or []:
                record = ToolCallRecord(
                    name=tc.get("name") or "",
                    arguments=_parse_arguments(tc.get("arguments")),
                    call_id=tc.get("id") or "",
                    requestor=tc.get("requestor") or role,
                    message_index=i,
                )
                records.append(record)
                if record.call_id:
                    by_id[record.call_id] = record
        elif role == "tool":
            # tau2 ToolMessage pairs with its ToolCall via the shared `id`.
            caller = by_id.get(msg.get("id") or "")
            if caller is not None and caller.result is None:
                caller.result = str(msg.get("content") or "")
    return records


def load_taubench_trajectories(path: str | Path) -> list[Trajectory]:
    """Load a tau-bench results file (a JSON list of EnvRunResult dicts).

    Works on ``historical_trajectories/*.json`` and on files produced by
    ``tau_bench/run.py``.
    """
    with open(path) as f:
        runs = json.load(f)
    if not isinstance(runs, list):
        raise ValueError(
            f"{path} is not a tau-bench results file (expected a top-level JSON list "
            "of EnvRunResult objects; got a dict - is this a tau2 file? "
            "Use load_tau2_trajectories)."
        )
    trajectories: list[Trajectory] = []
    for run in runs:
        messages = run.get("traj") or []
        trajectories.append(
            Trajectory(
                source="taubench",
                messages=messages,
                tool_calls=_extract_openai_tool_calls(messages),
                task_id=run.get("task_id"),
                trial=run.get("trial"),
                reward=run.get("reward"),
                metadata={"info": run.get("info", {})},
            )
        )
    return trajectories


def load_tau2_trajectories(path: str | Path) -> list[Trajectory]:
    """Load a tau2-bench Results file ({timestamp, info, tasks, simulations}).

    Works on the checked-in ``data/tau2/results/final/*.json`` files and any
    ``Results.save()`` output in monolithic JSON format.
    """
    with open(path) as f:
        results = json.load(f)
    simulations = results.get("simulations") if isinstance(results, dict) else None
    if simulations is None:
        raise ValueError(
            f"{path} is not a tau2 Results file (no 'simulations' key; got a list? "
            "Use load_taubench_trajectories)."
        )
    trajectories: list[Trajectory] = []
    for sim in simulations:
        messages = sim.get("messages") or []
        reward_info = sim.get("reward_info") or {}
        trajectories.append(
            Trajectory(
                source="tau2",
                messages=messages,
                tool_calls=_extract_tau2_tool_calls(messages),
                task_id=sim.get("task_id"),
                trial=sim.get("trial"),
                reward=reward_info.get("reward"),
                metadata={
                    "simulation_id": sim.get("id"),
                    "termination_reason": sim.get("termination_reason"),
                    "reward_info": reward_info,
                },
            )
        )
    return trajectories


def trajectory_from_messages(messages: list[dict[str, Any]], source: str = "openai") -> Trajectory:
    """Build a Trajectory from a live OpenAI-format message list.

    This is the entry point for *online* guardrailing: pass the conversation
    an agent has accumulated so far (the same list you send to
    ``chat.completions.create``).
    """
    return Trajectory(
        source=source,
        messages=messages,
        tool_calls=_extract_openai_tool_calls(messages),
    )


def render_tool_call(name: str, arguments: dict[str, Any]) -> str:
    """One-line canonical rendering of a tool call for verifier prompts."""
    return f"{name}({json.dumps(arguments, sort_keys=True, default=str)})"


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"... <clipped {len(text) - limit} chars>"


def render_trajectory(
    trajectory: Trajectory,
    *,
    max_chars_per_message: int = 500,
    include_system: bool = False,
) -> str:
    """Render a trajectory as a compact numbered transcript for verification.

    Tool calls are rendered with their FULL arguments (they are what the
    guardrail reasons about); free-text turns and tool results are clipped so
    long conversations do not blow the verifier's context. The system message
    is skipped by default - in tau-bench trajectories it *is* the policy,
    which the guardrail supplies separately.
    """
    lines: list[str] = []
    for i, msg in enumerate(trajectory.messages):
        role = msg.get("role") or "?"
        if role == "system" and not include_system:
            continue
        content = str(msg.get("content") or "").strip()
        if role == "tool":
            name = msg.get("name") or ""
            label = f"TOOL RESULT{f' ({name})' if name else ''}"
            lines.append(f"[{i}] {label}: {_clip(content, max_chars_per_message)}")
            continue
        if content:
            lines.append(f"[{i}] {role.upper()}: {_clip(content, max_chars_per_message)}")
        for tc in trajectory.tool_calls:
            if tc.message_index == i:
                prefix = "USER TOOL CALL" if tc.requestor == "user" else "TOOL CALL"
                lines.append(f"[{i}] {prefix}: {render_tool_call(tc.name, tc.arguments)}")
    return "\n".join(lines)
