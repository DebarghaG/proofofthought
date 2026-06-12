"""The agentic SMT-LIB scratchpad solver.

Instead of generating one whole program and hoping it runs, the model
iteratively interacts with an SMT-LIB scratchpad:

    1. think -> call ``z3_solve`` with a complete SMT-LIB 2.6 program
    2. read Z3's verdict (sat / unsat / unknown / error)
    3. repair or strengthen the encoding and call ``z3_solve`` again
    4. once Z3 confirms the answer (clean UNSAT of the negated candidate),
       call ``finish`` with the verified answer

The loop, nudge policy, tool-result truncation and result classification are
ported from the NL2SMTLIB-Benchmark evaluation harness where they were tuned
over tens of thousands of trajectories. The transport here is synchronous and
works with any OpenAI-compatible chat-completions client (OpenAI, AzureOpenAI,
vLLM, sglang, ...).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from z3adapter.agentic.executor import Z3Executor, z3_result_is_useful
from z3adapter.agentic.parsing import extract_answer_from_text, parse_tool_calls_from_content

logger = logging.getLogger(__name__)


# Tool definitions exposed to the model (OpenAI function-calling schema).
Z3_TOOL = {
    "type": "function",
    "function": {
        "name": "z3_solve",
        "description": (
            "Execute SMT-LIB 2.6 code using the Z3 theorem prover.\n\n"
            "The code should be a complete, self-contained SMT-LIB script including "
            "(check-sat). Returns the Z3 output (sat / unsat / unknown and any model)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "smt_code": {
                    "type": "string",
                    "description": (
                        "Complete SMT-LIB 2.6 code to execute. Must include (check-sat)."
                    ),
                }
            },
            "required": ["smt_code"],
        },
    },
}

FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": (
            "Terminate the solve loop with a final verified answer.\n\n"
            "Call this once the SMT-LIB verification via z3_solve has confirmed the answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": (
                        "The final verified answer value (e.g. 'Yes', 'No', 'True', "
                        "'False', 'A', 'B')."
                    ),
                },
                "explanation": {
                    "type": "string",
                    "description": "Brief explanation of how the answer was verified.",
                },
            },
            "required": ["answer"],
        },
    },
}

TOOLS = [Z3_TOOL, FINISH_TOOL]


DEFAULT_SYSTEM_PROMPT = """You are a formal verification expert. You MUST solve problems using SMT-LIB formal verification via the z3_solve tool, treating it as an iterative scratchpad.

WORKFLOW (follow exactly):
1. Briefly analyze the problem (keep reasoning concise).
2. Call z3_solve with complete SMT-LIB 2.6 code to formally verify your answer.
3. If Z3 returns an error, fix the SMT-LIB code and call z3_solve again.
4. Once Z3 confirms your answer, call the finish tool with ONLY the answer value.

SMT-LIB RULES:
- Generate COMPLETE, SELF-CONTAINED SMT-LIB code with all declarations.
- Always include (check-sat). Use (get-model) when you need assignments.
- For True/False questions: assert the negation of your expected answer; if UNSAT, the answer is proven.
- For multiple choice: encode constraints, assert the negation of the candidate answer, show UNSAT.
- For Yes/No questions: model the key logical relationships, verify formally.

CRITICAL: You MUST call z3_solve at least once with a non-trivial program that references the problem's entities. You MUST call finish when done.
The finish answer field must contain ONLY the answer value (e.g., "Yes", "No", "True", "False", "A", "B", etc.)."""


_TOOL_RESULT_HARD_CAP = 1500
_TOOL_RESULT_KEEP_HEAD = 600
_TOOL_RESULT_KEEP_TAIL = 600


def _truncate_tool_result(text: str) -> str:
    """HEAD+TAIL truncation of long Z3 output.

    (get-model) dumps accumulate across turns and can blow the context limit
    in later iterations; keeping the head and tail preserves the verdict line
    and any error tail while dropping the bulk in the middle.
    """
    if not text or len(text) <= _TOOL_RESULT_HARD_CAP:
        return text
    return (
        text[:_TOOL_RESULT_KEEP_HEAD]
        + f"\n... <truncated {len(text) - _TOOL_RESULT_KEEP_HEAD - _TOOL_RESULT_KEEP_TAIL} chars> ...\n"
        + text[-_TOOL_RESULT_KEEP_TAIL:]
    )


@dataclass
class AgenticConfig:
    """Configuration for the agentic solve loop."""

    model: str = "gpt-5"
    max_tokens: int = 16384
    # None means "do not send temperature" (required for models like GPT-5
    # that only accept the default). Set explicitly for diverse sampling.
    temperature: float | None = None
    max_iterations: int = 10
    # How many times to push the model after a turn with no tool call.
    # Counter resets on each successful tool emission.
    max_consecutive_nudges: int = 2
    z3_timeout_ms: int = 30000
    # When True, attempt to extract an answer from the model's last
    # natural-language output if the loop exits without a clean finish().
    # The strict path is unchanged; recovered rows are tagged via
    # extraction_method = "text_pattern_extracted".
    lenient_extraction: bool = False
    # Override the default system prompt entirely (advanced).
    system_prompt: str | None = None


@dataclass
class AgenticResult:
    """Full result of one agentic solve loop, including the trajectory."""

    question: str
    answer: str | None = None
    explanation: str | None = None
    verified: bool = False
    smt_history: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    iterations: int = 0
    token_usage: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    # How `answer` got populated:
    #   "tool_call_finish"       -> model called finish() cleanly
    #   "text_pattern_extracted" -> recovered from text after no_finish (lenient mode)
    #   "none"                   -> no answer extracted
    extraction_method: str = "none"


def _to_plain(obj: Any) -> Any:
    """Normalize OpenAI SDK pydantic objects / dicts to plain dicts."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return {k: _to_plain(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return obj


class AgenticSolver:
    """Run the iterative z3_solve / finish tool loop against an LLM client.

    Args:
        llm_client: Any OpenAI-compatible client exposing
            ``.chat.completions.create`` (OpenAI, AzureOpenAI, a vLLM
            endpoint wrapped in the OpenAI SDK, ...).
        config: AgenticConfig tuning the loop.
    """

    def __init__(self, llm_client: Any, config: AgenticConfig | None = None) -> None:
        self.llm_client = llm_client
        self.config = config or AgenticConfig()
        self.executor = Z3Executor(timeout_ms=self.config.z3_timeout_ms)

    # -- LLM transport ------------------------------------------------------

    def _call_llm(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """One chat-completions call with tools; returns a plain-dict response.

        Tries ``max_completion_tokens`` first (current OpenAI parameter) and
        falls back to ``max_tokens`` for older OpenAI-compatible servers.
        """
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "tools": TOOLS,
        }
        if self.config.temperature is not None:
            kwargs["temperature"] = self.config.temperature
        try:
            response = self.llm_client.chat.completions.create(
                max_completion_tokens=self.config.max_tokens, **kwargs
            )
        except TypeError:
            # Client stub without max_completion_tokens support
            response = self.llm_client.chat.completions.create(
                max_tokens=self.config.max_tokens, **kwargs
            )
        except Exception as e:
            if "max_completion_tokens" in str(e):
                response = self.llm_client.chat.completions.create(
                    max_tokens=self.config.max_tokens, **kwargs
                )
            else:
                raise
        return _to_plain(response)

    @staticmethod
    def _extract_turn(response: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], str]:
        """Pull (content, reasoning, tool_calls, finish_reason) out of a response."""
        choice = (response.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        # Reasoning-channel field name varies across servers.
        reasoning = msg.get("reasoning") or msg.get("reasoning_content") or ""
        tool_calls = _to_plain(msg.get("tool_calls")) or []
        finish_reason = choice.get("finish_reason") or ""

        # Fallback: the server's tool-call parser missed a textual tool call
        # in the content (or reasoning) channel. Recover it ourselves.
        if not tool_calls and content:
            parsed = parse_tool_calls_from_content(content)
            if parsed:
                tool_calls = parsed
        if (
            not tool_calls
            and reasoning
            and ("<tool_call>" in reasoning or "</tool_call>" in reasoning)
        ):
            parsed = parse_tool_calls_from_content(reasoning)
            if parsed:
                tool_calls = parsed
        return content, reasoning, tool_calls, finish_reason

    def _record_usage(
        self, result: AgenticResult, response: dict[str, Any], iteration: int, phase: str
    ) -> None:
        usage = response.get("usage") or {}
        if not isinstance(usage, dict):
            return
        if not any(k in usage for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
            return
        entry: dict[str, Any] = {"iteration": iteration + 1, "phase": phase}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if usage.get(key) is not None:
                entry[key] = usage[key]
        result.token_usage.append(entry)

    # -- Nudge policy -------------------------------------------------------

    @staticmethod
    def _next_nudge(smt_history: list[dict[str, Any]]) -> str:
        """Choose the next nudge based on the last Z3 result, not just its existence."""
        if not smt_history:
            return (
                "You finished your turn but did not emit a tool call. "
                "Now call the z3_solve tool with complete SMT-LIB code to "
                "verify your answer."
            )

        z3_out = smt_history[-1]["z3_output"]
        sat_result = z3_out.get("sat_result")

        if _z3_result_has_error(z3_out):
            return (
                "Z3 reported syntax/type errors for the previous SMT-LIB program. "
                "Do not call finish yet. Fix the SMT-LIB code and call z3_solve "
                "again. Use simple Boolean predicates for each entity/property "
                "when possible."
            )

        if sat_result == "unsat":
            return (
                "You finished your turn but did not emit a tool call. "
                "Z3 returned a clean UNSAT result, so now call the finish "
                "tool with your final answer."
            )

        if sat_result == "sat":
            return (
                "Z3 returned SAT, which does not prove the answer under this "
                "protocol. Do not call finish yet. Revise the encoding: "
                "assert the negation of your candidate answer and call z3_solve "
                "again; a clean UNSAT result should precede finish."
            )

        return (
            "Z3 did not return a clean SAT/UNSAT proof. Do not call finish yet. "
            "Revise the SMT-LIB encoding and call z3_solve again."
        )

    # -- Main loop ----------------------------------------------------------

    def solve(self, question: str, answer_format: str | None = None) -> AgenticResult:
        """Run the full iterative solve loop for a single question.

        Args:
            question: Natural language question/problem statement.
            answer_format: Optional hint appended to the user message, e.g.
                "Answer with one of: True, False, Unknown" or the rendered
                multiple-choice options.

        Returns:
            AgenticResult with the verified answer (or None) and trajectory.
        """
        config = self.config
        result = AgenticResult(question=question)

        system_prompt = config.system_prompt or DEFAULT_SYSTEM_PROMPT
        user_content = question
        if answer_format:
            user_content += f"\n\n{answer_format}"

        # `messages` is what we send to the API (standard fields only);
        # `result.messages` is the full transcript including reasoning.
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        result.messages = [dict(m) for m in messages]

        def _append_assistant(
            content: str, reasoning: str, tool_calls: list[dict[str, Any]]
        ) -> None:
            api_msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
            if tool_calls:
                api_msg["tool_calls"] = tool_calls
            messages.append(api_msg)
            transcript_msg = dict(api_msg)
            if reasoning:
                transcript_msg["reasoning"] = reasoning
            result.messages.append(transcript_msg)

        def _append(msg: dict[str, Any]) -> None:
            messages.append(msg)
            result.messages.append(dict(msg))

        def _handle_finish(tc: dict[str, Any]) -> bool:
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                return False
            result.answer = args.get("answer", "")
            result.explanation = args.get("explanation", "")
            result.verified = True
            result.extraction_method = "tool_call_finish"
            _append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps({"status": "finished", **args}),
                }
            )
            return True

        def _handle_z3(tc: dict[str, Any]) -> None:
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                _append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": "ERROR: failed to parse z3_solve arguments as JSON.",
                    }
                )
                return
            smt_code = args.get("smt_code", "")
            z3_out = self.executor.execute(smt_code)
            result.smt_history.append({"smt_code": smt_code, "z3_output": z3_out})
            content = z3_out["output"] if z3_out["success"] else f"ERROR: {z3_out['error']}"
            _append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": _truncate_tool_result(content),
                }
            )

        consecutive_nudges = 0
        finished = False
        for iteration in range(config.max_iterations):
            result.iterations = iteration + 1
            try:
                response = self._call_llm(messages)
                self._record_usage(result, response, iteration, "normal")
            except Exception as e:
                result.error = f"LLM call failed at iteration {iteration}: {e}"
                break

            content, reasoning, tool_calls, finish_reason = self._extract_turn(response)
            _append_assistant(content, reasoning, tool_calls)

            if not tool_calls:
                # No parseable tool call this turn. Push the model to emit
                # one. We never set the answer from raw content/reasoning -
                # that produced false-positive correctness via
                # string-contains matches in earlier harness versions.
                if finish_reason == "length":
                    _append({"role": "user", "content": self._next_nudge(result.smt_history)})
                    continue
                elif (
                    iteration < config.max_iterations - 1
                    and consecutive_nudges < config.max_consecutive_nudges
                ):
                    _append({"role": "user", "content": self._next_nudge(result.smt_history)})
                    consecutive_nudges += 1
                    continue
                else:
                    result.answer = None
                    result.explanation = "no_finish_call_within_max_iterations"
                    break

            consecutive_nudges = 0

            for tc in tool_calls:
                name = tc.get("function", {}).get("name")
                if name == "finish":
                    finished = _handle_finish(tc) or finished
                elif name == "z3_solve":
                    _handle_z3(tc)
                else:
                    _append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": f"Unknown tool: {name}",
                        }
                    )

            if finished:
                break

            # If the last allowed iteration ended with a clean proof, give
            # the model one bounded finish-only follow-up. Otherwise a
            # repaired SMT program can prove the answer on the final turn but
            # still be scored as no_finish because there is no next turn left
            # for finish().
            if iteration == config.max_iterations - 1 and result.smt_history:
                z3_out = result.smt_history[-1]["z3_output"]
                if z3_out.get("sat_result") == "unsat" and not _z3_result_has_error(z3_out):
                    _append({"role": "user", "content": self._next_nudge(result.smt_history)})
                    try:
                        response = self._call_llm(messages)
                        self._record_usage(result, response, iteration, "final_finish")
                        content, reasoning, tool_calls, _ = self._extract_turn(response)
                        _append_assistant(content, reasoning, tool_calls)
                        for tc in tool_calls:
                            if tc.get("function", {}).get("name") == "finish":
                                finished = _handle_finish(tc) or finished
                            else:
                                _append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tc.get("id", ""),
                                        "content": (
                                            "IGNORED: final follow-up only accepts finish; "
                                            "max tool-call rounds reached."
                                        ),
                                    }
                                )
                    except Exception as e:
                        result.error = f"LLM final finish call failed: {e}"
                if finished:
                    break

        # Lenient fallback: recover an answer from the last natural-language
        # output. The strict path is always preserved; recovered rows are
        # tagged via extraction_method.
        if config.lenient_extraction and not result.verified and not (result.answer or "").strip():
            candidate_text = ""
            for m in reversed(result.messages):
                if m.get("role") == "assistant":
                    candidate_text = (m.get("content") or "") + "\n" + (m.get("reasoning") or "")
                    if candidate_text.strip():
                        break
            recovered = extract_answer_from_text(candidate_text)
            if recovered:
                result.answer = recovered
                result.explanation = (result.explanation or "") + " [recovered from text]"
                result.extraction_method = "text_pattern_extracted"

        return result


def _z3_result_has_error(z3_out: dict[str, Any]) -> bool:
    """Return True when Z3 produced syntactic/tool errors, even with sat output."""
    if z3_result_is_useful(z3_out):
        return False
    output = str(z3_out.get("output") or "")
    error = str(z3_out.get("error") or "")
    combined = f"{output}\n{error}".lower()
    return (
        not z3_out.get("success")
        or bool(z3_out.get("error"))
        or "(error" in combined
        or "unsupported" in combined
    )
