"""The agentic SMT-LIB scratchpad solver.

Instead of generating one whole program and hoping it runs, the model
iteratively interacts with an SMT-LIB scratchpad:

    1. think -> call ``z3_solve`` with a complete SMT-LIB 2.6 program
    2. read Z3's verdict (sat / unsat / unknown / error)
    3. repair or strengthen the encoding and call ``z3_solve`` again
    4. once Z3 confirms the answer (canonically, a clean UNSAT of the negated
       candidate - a proof by contradiction), call ``finish`` with the
       verified answer

Every accepted answer carries an explicit :class:`ProofStatus` describing how
the trajectory backs it. ``finish`` is *not* taken at face value: a finish
call without a decisive Z3 verdict on record is pushed back (up to
``max_finish_rejections`` times) before being accepted as ``UNVERIFIED``, so
``verified=True`` always means "the answer was backed by a usable sat/unsat
verdict" - never "the model said so".

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
from enum import StrEnum
from typing import Any

from z3adapter.agentic.executor import (
    Z3Executor,
    last_smt_result_is_useful,
    z3_result_has_error,
)
from z3adapter.agentic.parsing import extract_answer_from_text, parse_tool_calls_from_content

logger = logging.getLogger(__name__)


class ProofStatus(StrEnum):
    """How an accepted answer is backed by the SMT trajectory.

    This is the first-class handle on the library's verification semantics:

    - ``PROOF_BY_CONTRADICTION`` - the strongest status. The last decisive
      Z3 verdict was a clean ``unsat``: under the solve protocol the model
      asserted the *negation* of its candidate answer, so unsatisfiability
      is a proof of the answer.
    - ``SAT_WITNESS`` - the last decisive verdict was a clean ``sat``: Z3
      produced a model consistent with the answer. A witness shows the
      encoding is satisfiable but does not rule out alternatives; it is
      appropriate for existence questions and weaker than a contradiction
      proof everywhere else.
    - ``UNVERIFIED`` - an answer was recorded without a usable verdict
      (a finish accepted after the rejection budget ran out, or a lenient
      text extraction). Treat it as an ordinary LLM guess.

    Values are plain strings ("proof_by_contradiction", "sat_witness",
    "unverified") so they serialize cleanly to JSON and survive round-trips
    through result files.
    """

    PROOF_BY_CONTRADICTION = "proof_by_contradiction"
    SAT_WITNESS = "sat_witness"
    UNVERIFIED = "unverified"


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
- For True/False questions: assert the negation of your expected answer; if UNSAT, the answer is proven by contradiction.
- For multiple choice: encode constraints, assert the negation of the candidate answer, show UNSAT.
- For Yes/No questions: model the key logical relationships, verify formally.

CRITICAL: You MUST call z3_solve at least once with a non-trivial program that references the problem's entities. A finish call without a decisive Z3 result will be rejected. You MUST call finish when done.
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
    # How many premature finish calls (no decisive Z3 verdict on record) to
    # reject per solve before accepting the answer as UNVERIFIED. Rejecting
    # forever would lose the answer entirely; accepting immediately would
    # make `verified` meaningless.
    max_finish_rejections: int = 2
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
    # True iff the finish call was backed by a decisive Z3 verdict
    # (proof_status is PROOF_BY_CONTRADICTION or SAT_WITNESS).
    verified: bool = False
    # How the answer is backed by the trajectory; None when no answer was
    # produced at all. See ProofStatus.
    proof_status: ProofStatus | None = None
    smt_history: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    iterations: int = 0
    token_usage: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    # How `answer` got populated:
    #   "tool_call_finish"            -> finish() backed by a decisive verdict
    #   "tool_call_finish_unverified" -> finish() accepted after the rejection
    #                                    budget ran out, with no usable verdict
    #   "text_pattern_extracted"      -> recovered from text after no_finish
    #                                    (lenient mode)
    #   "none"                        -> no answer extracted
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


@dataclass
class _Conversation:
    """Twin views of one conversation.

    ``api`` holds standard chat fields only and is what gets sent to the
    server; ``transcript`` additionally carries the reasoning channel and is
    what lands in AgenticResult.messages. Keeping them in lockstep here means
    no caller can forget to strip non-standard fields before an API call.
    """

    api: list[dict[str, Any]] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)

    def append(self, msg: dict[str, Any]) -> None:
        self.api.append(msg)
        self.transcript.append(dict(msg))

    def append_assistant(
        self, content: str, reasoning: str, tool_calls: list[dict[str, Any]]
    ) -> None:
        api_msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        if tool_calls:
            api_msg["tool_calls"] = tool_calls
        self.api.append(api_msg)
        transcript_msg = dict(api_msg)
        if reasoning:
            transcript_msg["reasoning"] = reasoning
        self.transcript.append(transcript_msg)

    def append_tool(self, tool_call_id: str, content: str) -> None:
        # Every tool_call the assistant emitted MUST receive a tool response,
        # even on parse failures - a dangling tool_call_id makes strict
        # servers reject the whole conversation on the next call.
        self.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})


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
        # Which token-limit parameter the server accepts. Probed on the first
        # call and cached, so legacy servers pay at most one failed
        # round-trip per solver instance rather than one per turn.
        self._max_tokens_param: str | None = None

    # -- LLM transport ------------------------------------------------------

    def _create(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None,
        max_tokens: int,
        tokens_param: str,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "tools": TOOLS,
            tokens_param: max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        return self.llm_client.chat.completions.create(**kwargs)

    def _call_llm(
        self, messages: list[dict[str, Any]], temperature: float | None, max_tokens: int
    ) -> dict[str, Any]:
        """One chat-completions call with tools; returns a plain-dict response.

        Tries ``max_completion_tokens`` first (current OpenAI parameter) and
        falls back to ``max_tokens`` for older OpenAI-compatible servers; the
        working parameter name is cached on the instance.
        """
        if self._max_tokens_param is not None:
            return _to_plain(
                self._create(messages, temperature, max_tokens, self._max_tokens_param)
            )
        try:
            response = self._create(messages, temperature, max_tokens, "max_completion_tokens")
            self._max_tokens_param = "max_completion_tokens"
        except TypeError:
            # Client stub without max_completion_tokens support
            response = self._create(messages, temperature, max_tokens, "max_tokens")
            self._max_tokens_param = "max_tokens"
        except Exception as e:
            if "max_completion_tokens" not in str(e):
                raise
            response = self._create(messages, temperature, max_tokens, "max_tokens")
            self._max_tokens_param = "max_tokens"
        return _to_plain(response)

    @staticmethod
    def _extract_turn(response: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], str]:
        """Pull (content, reasoning, tool_calls, finish_reason) out of a response."""
        choice = (response.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
        # Reasoning-channel field name varies across servers.
        reasoning = msg.get("reasoning") or msg.get("reasoning_content") or ""
        tool_calls = msg.get("tool_calls") or []
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

    def _take_turn(
        self,
        conv: _Conversation,
        result: AgenticResult,
        iteration: int,
        phase: str,
        temperature: float | None,
        max_tokens: int,
    ) -> tuple[list[dict[str, Any]], str] | None:
        """One full model turn: call, record usage, recover tool calls,
        append the assistant message. Returns (tool_calls, finish_reason),
        or None when the call failed (result.error is set).

        This is the single implementation of turn handling - the main loop
        and the final-finish follow-up both go through it, so a change here
        applies to every turn.
        """
        try:
            response = self._call_llm(conv.api, temperature, max_tokens)
        except Exception as e:
            result.error = f"LLM call failed at iteration {iteration}: {e}"
            return None
        self._record_usage(result, response, iteration, phase)
        content, reasoning, tool_calls, finish_reason = self._extract_turn(response)
        conv.append_assistant(content, reasoning, tool_calls)
        return tool_calls, finish_reason

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

        if z3_result_has_error(z3_out):
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

    # -- Tool dispatch ------------------------------------------------------

    @staticmethod
    def _proof_status(smt_history: list[dict[str, Any]]) -> ProofStatus:
        """Classify how the current trajectory would back an answer."""
        if last_smt_result_is_useful(smt_history):
            verdict = smt_history[-1]["z3_output"].get("sat_result")
            if verdict == "unsat":
                return ProofStatus.PROOF_BY_CONTRADICTION
            return ProofStatus.SAT_WITNESS
        return ProofStatus.UNVERIFIED

    def _handle_z3(self, tc: dict[str, Any], conv: _Conversation, result: AgenticResult) -> None:
        try:
            args = json.loads(tc["function"]["arguments"])
        except json.JSONDecodeError:
            conv.append_tool(tc.get("id", ""), "ERROR: failed to parse z3_solve arguments as JSON.")
            return
        smt_code = args.get("smt_code", "")
        z3_out = self.executor.execute(smt_code)
        result.smt_history.append({"smt_code": smt_code, "z3_output": z3_out})
        content = z3_out["output"] if z3_out["success"] else f"ERROR: {z3_out['error']}"
        conv.append_tool(tc.get("id", ""), _truncate_tool_result(content))

    def _try_finish(
        self,
        tc: dict[str, Any],
        conv: _Conversation,
        result: AgenticResult,
        allow_unverified: bool,
    ) -> bool:
        """Process one finish call. Returns True when the answer is accepted.

        A finish without a decisive Z3 verdict on record is rejected (with a
        tool message telling the model what to do) unless ``allow_unverified``
        - in which case the answer is kept but honestly tagged UNVERIFIED.
        """
        try:
            args = json.loads(tc["function"]["arguments"])
        except json.JSONDecodeError:
            conv.append_tool(
                tc.get("id", ""),
                "ERROR: failed to parse finish arguments as JSON. "
                "Emit the finish call again with valid JSON.",
            )
            return False

        status = self._proof_status(result.smt_history)
        if status is ProofStatus.UNVERIFIED and not allow_unverified:
            conv.append_tool(
                tc.get("id", ""),
                "REJECTED: finish requires a decisive Z3 verdict and none is on "
                "record. Call z3_solve with a program that verifies your answer "
                "(assert the negation of your candidate; a clean UNSAT proves it "
                "by contradiction), then call finish.",
            )
            return False

        result.answer = args.get("answer", "")
        result.explanation = args.get("explanation", "")
        result.proof_status = status
        result.verified = status is not ProofStatus.UNVERIFIED
        result.extraction_method = (
            "tool_call_finish" if result.verified else "tool_call_finish_unverified"
        )
        conv.append_tool(tc.get("id", ""), json.dumps({"status": "finished", **args}))
        return True

    def _dispatch(
        self,
        tool_calls: list[dict[str, Any]],
        conv: _Conversation,
        result: AgenticResult,
        allow_unverified: bool,
        finish_only: bool = False,
    ) -> bool:
        """Execute one turn's tool calls; returns True when finished.

        z3_solve calls run before finish calls so that a same-turn proof
        backs the finish. Every tool_call gets a tool response (see
        _Conversation.append_tool).
        """

        def _name(tc: dict[str, Any]) -> str:
            return tc.get("function", {}).get("name") or ""

        z3_calls = [tc for tc in tool_calls if _name(tc) == "z3_solve"]
        finish_calls = [tc for tc in tool_calls if _name(tc) == "finish"]
        other_calls = [tc for tc in tool_calls if _name(tc) not in ("z3_solve", "finish")]

        if finish_only:
            for tc in z3_calls:
                conv.append_tool(
                    tc.get("id", ""),
                    "IGNORED: final follow-up only accepts finish; "
                    "max tool-call rounds reached.",
                )
        else:
            for tc in z3_calls:
                self._handle_z3(tc, conv, result)
        for tc in other_calls:
            conv.append_tool(tc.get("id", ""), f"Unknown tool: {_name(tc)}")

        finished = False
        for tc in finish_calls:
            if self._try_finish(tc, conv, result, allow_unverified):
                finished = True
        return finished

    # -- Main loop ----------------------------------------------------------

    def solve(
        self,
        question: str,
        answer_format: str | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AgenticResult:
        """Run the full iterative solve loop for a single question.

        Args:
            question: Natural language question/problem statement.
            answer_format: Optional hint appended to the user message, e.g.
                "Answer with one of: True, False, Unknown" or the rendered
                multiple-choice options.
            temperature: Per-call override of AgenticConfig.temperature.
                None falls back to the config (whose None means "don't send").
            max_tokens: Per-call override of AgenticConfig.max_tokens.

        Returns:
            AgenticResult with the answer (or None), its ProofStatus, and the
            full trajectory.
        """
        config = self.config
        if temperature is None:
            temperature = config.temperature
        if max_tokens is None:
            max_tokens = config.max_tokens
        result = AgenticResult(question=question)

        user_content = question
        if answer_format:
            user_content += f"\n\n{answer_format}"

        conv = _Conversation()
        conv.append({"role": "system", "content": config.system_prompt or DEFAULT_SYSTEM_PROMPT})
        conv.append({"role": "user", "content": user_content})

        consecutive_nudges = 0
        finish_rejections = 0
        finished = False
        for iteration in range(config.max_iterations):
            result.iterations = iteration + 1
            turn = self._take_turn(conv, result, iteration, "normal", temperature, max_tokens)
            if turn is None:
                break
            tool_calls, finish_reason = turn

            if not tool_calls:
                # No parseable tool call this turn. Push the model to emit
                # one. We never set the answer from raw content/reasoning -
                # that produced false-positive correctness via
                # string-contains matches in earlier harness versions.
                if finish_reason == "length":
                    conv.append({"role": "user", "content": self._next_nudge(result.smt_history)})
                    continue
                elif (
                    iteration < config.max_iterations - 1
                    and consecutive_nudges < config.max_consecutive_nudges
                ):
                    conv.append({"role": "user", "content": self._next_nudge(result.smt_history)})
                    consecutive_nudges += 1
                    continue
                else:
                    result.answer = None
                    result.explanation = "no_finish_call_within_max_iterations"
                    break

            consecutive_nudges = 0

            # A premature finish (no decisive verdict) is rejected up to
            # max_finish_rejections times; after that - or when there is no
            # next turn - it is accepted but tagged UNVERIFIED, so the
            # answer is preserved without inflating `verified`.
            allow_unverified = (
                finish_rejections >= config.max_finish_rejections
                or iteration == config.max_iterations - 1
            )
            had_finish = any(tc.get("function", {}).get("name") == "finish" for tc in tool_calls)
            finished = self._dispatch(tool_calls, conv, result, allow_unverified)
            if finished:
                break
            if had_finish:
                finish_rejections += 1

            # If the last allowed iteration ended with a clean proof, give
            # the model one bounded finish-only follow-up. Otherwise a
            # repaired SMT program can prove the answer on the final turn but
            # still be scored as no_finish because there is no next turn left
            # for finish().
            if iteration == config.max_iterations - 1 and result.smt_history:
                z3_out = result.smt_history[-1]["z3_output"]
                if z3_out.get("sat_result") == "unsat" and not z3_result_has_error(z3_out):
                    conv.append({"role": "user", "content": self._next_nudge(result.smt_history)})
                    turn = self._take_turn(
                        conv, result, iteration, "final_finish", temperature, max_tokens
                    )
                    if turn is not None:
                        tool_calls, _ = turn
                        # History holds a clean unsat, so an accepted finish
                        # here is PROOF_BY_CONTRADICTION by construction.
                        finished = self._dispatch(
                            tool_calls, conv, result, allow_unverified=False, finish_only=True
                        )
                    if finished:
                        break

        # Lenient fallback: recover an answer from the last natural-language
        # output. The strict path is always preserved; recovered rows are
        # tagged via extraction_method and are UNVERIFIED by definition.
        if config.lenient_extraction and not result.verified and not (result.answer or "").strip():
            candidate_text = ""
            for m in reversed(conv.transcript):
                if m.get("role") == "assistant":
                    candidate_text = (m.get("content") or "") + "\n" + (m.get("reasoning") or "")
                    if candidate_text.strip():
                        break
            recovered = extract_answer_from_text(candidate_text)
            if recovered:
                result.answer = recovered
                result.explanation = (result.explanation or "") + " [recovered from text]"
                result.extraction_method = "text_pattern_extracted"
                result.proof_status = ProofStatus.UNVERIFIED

        result.messages = conv.transcript
        return result
