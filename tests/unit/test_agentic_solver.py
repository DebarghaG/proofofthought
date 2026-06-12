"""Unit tests for the agentic solve loop, using a scripted mock LLM client."""

import json
import unittest
from typing import Any

from z3adapter.agentic.agent import AgenticConfig, AgenticSolver

UNSAT_PROGRAM = "(declare-const x Int)\n(assert (> x 5))\n(assert (< x 3))\n(check-sat)"
SAT_PROGRAM = "(declare-const x Int)\n(assert (> x 5))\n(check-sat)"
BROKEN_PROGRAM = "(assert (> y 5))\n(check-sat)"


def _tool_call(name: str, args: dict[str, Any], call_id: str = "call_1") -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _response(
    content: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str = "stop",
) -> dict[str, Any]:
    msg: dict[str, Any] = {"content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
        finish_reason = "tool_calls"
    return {
        "choices": [{"message": msg, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


class MockClient:
    """OpenAI-compatible client returning a scripted sequence of responses."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

        outer = self

        class _Completions:
            def create(self, **kwargs: Any) -> dict[str, Any]:
                # Deep-copy: the solver mutates the messages list in place
                # between calls, so snapshot what was sent at call time.
                outer.calls.append(json.loads(json.dumps(kwargs, default=str)))
                if not outer._responses:
                    raise RuntimeError("MockClient ran out of scripted responses")
                return outer._responses.pop(0)

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


class TestAgenticSolver(unittest.TestCase):
    """Drive the loop end-to-end against scripted responses (real Z3 calls)."""

    def test_happy_path_unsat_then_finish(self) -> None:
        client = MockClient(
            [
                _response(tool_calls=[_tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
                _response(
                    tool_calls=[
                        _tool_call("finish", {"answer": "No", "explanation": "UNSAT proved it."})
                    ]
                ),
            ]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock"))
        result = solver.solve("Is there an integer both greater than 5 and less than 3?")

        self.assertTrue(result.verified)
        self.assertEqual(result.answer, "No")
        self.assertEqual(result.extraction_method, "tool_call_finish")
        self.assertEqual(result.iterations, 2)
        self.assertEqual(len(result.smt_history), 1)
        self.assertEqual(result.smt_history[0]["z3_output"]["sat_result"], "unsat")
        self.assertEqual(len(result.token_usage), 2)

    def test_error_repair_loop(self) -> None:
        client = MockClient(
            [
                _response(tool_calls=[_tool_call("z3_solve", {"smt_code": BROKEN_PROGRAM})]),
                _response(tool_calls=[_tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
                _response(tool_calls=[_tool_call("finish", {"answer": "No"})]),
            ]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock"))
        result = solver.solve("q")

        self.assertTrue(result.verified)
        self.assertEqual(len(result.smt_history), 2)
        # First call errored, second was clean unsat
        self.assertEqual(result.smt_history[1]["z3_output"]["sat_result"], "unsat")

    def test_nudge_on_missing_tool_call(self) -> None:
        client = MockClient(
            [
                _response(content="Let me think about this..."),  # no tool call -> nudge
                _response(tool_calls=[_tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
                _response(tool_calls=[_tool_call("finish", {"answer": "No"})]),
            ]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock"))
        result = solver.solve("q")

        self.assertTrue(result.verified)
        # The second API call must contain the nudge user message at the end
        nudged_messages = client.calls[1]["messages"]
        self.assertEqual(nudged_messages[-1]["role"], "user")
        self.assertIn("z3_solve", nudged_messages[-1]["content"])

    def test_nudge_budget_exhausted(self) -> None:
        config = AgenticConfig(model="mock", max_iterations=5, max_consecutive_nudges=2)
        client = MockClient([_response(content="hmm")] * 3)
        solver = AgenticSolver(client, config)
        result = solver.solve("q")

        self.assertFalse(result.verified)
        self.assertIsNone(result.answer)
        self.assertEqual(result.explanation, "no_finish_call_within_max_iterations")
        self.assertEqual(len(client.calls), 3)  # initial + 2 nudges

    def test_textual_tool_call_recovered(self) -> None:
        # Model emits a textual <tool_call> the "server" failed to parse.
        textual = (
            '<tool_call>{"name": "z3_solve", "arguments": '
            + json.dumps({"smt_code": UNSAT_PROGRAM})
            + "}</tool_call>"
        )
        client = MockClient(
            [
                _response(content=textual),
                _response(tool_calls=[_tool_call("finish", {"answer": "No"})]),
            ]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock"))
        result = solver.solve("q")

        self.assertTrue(result.verified)
        self.assertEqual(len(result.smt_history), 1)
        self.assertEqual(result.smt_history[0]["z3_output"]["sat_result"], "unsat")

    def test_final_finish_followup(self) -> None:
        # max_iterations=1: the single turn produces a clean UNSAT, so the
        # loop grants one bounded finish-only follow-up.
        client = MockClient(
            [
                _response(tool_calls=[_tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
                _response(tool_calls=[_tool_call("finish", {"answer": "No"})]),
            ]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock", max_iterations=1))
        result = solver.solve("q")

        self.assertTrue(result.verified)
        self.assertEqual(result.answer, "No")

    def test_sat_does_not_get_finish_followup(self) -> None:
        # A SAT result on the last iteration is not a proof -> no follow-up.
        client = MockClient(
            [_response(tool_calls=[_tool_call("z3_solve", {"smt_code": SAT_PROGRAM})])]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock", max_iterations=1))
        result = solver.solve("q")

        self.assertFalse(result.verified)
        self.assertEqual(len(client.calls), 1)

    def test_lenient_extraction(self) -> None:
        config = AgenticConfig(
            model="mock", max_iterations=2, max_consecutive_nudges=0, lenient_extraction=True
        )
        client = MockClient([_response(content="Therefore the answer is Yes.")])
        solver = AgenticSolver(client, config)
        result = solver.solve("q")

        self.assertFalse(result.verified)
        self.assertEqual(result.answer, "Yes")
        self.assertEqual(result.extraction_method, "text_pattern_extracted")

    def test_transcript_has_reasoning_but_api_messages_do_not(self) -> None:
        resp = _response(tool_calls=[_tool_call("finish", {"answer": "Yes"})])
        resp["choices"][0]["message"]["reasoning"] = "chain of thought here"
        client = MockClient([resp])
        solver = AgenticSolver(client, AgenticConfig(model="mock"))
        result = solver.solve("q")

        transcript_assistant = [m for m in result.messages if m.get("role") == "assistant"]
        self.assertTrue(any("reasoning" in m for m in transcript_assistant))
        # messages actually sent to the API never carry a reasoning field
        for call in client.calls:
            for m in call["messages"]:
                self.assertNotIn("reasoning", m)

    def test_answer_format_hint_appended(self) -> None:
        client = MockClient([_response(tool_calls=[_tool_call("finish", {"answer": "A"})])])
        solver = AgenticSolver(client, AgenticConfig(model="mock"))
        solver.solve("q", answer_format="Answer choices:\n  A) foo\n  B) bar")

        user_msg = client.calls[0]["messages"][1]
        self.assertIn("Answer choices", user_msg["content"])


if __name__ == "__main__":
    unittest.main()
