"""Unit tests for the agentic solve loop, using a scripted mock LLM client."""

import json
import unittest

from tests.mock_llm import (
    BROKEN_PROGRAM,
    SAT_PROGRAM,
    UNSAT_PROGRAM,
    MockClient,
    raw_tool_call,
    response,
    tool_call,
)
from z3adapter.agentic.agent import AgenticConfig, AgenticSolver, ProofStatus


class TestAgenticSolver(unittest.TestCase):
    """Drive the loop end-to-end against scripted responses (real Z3 calls)."""

    def test_happy_path_unsat_then_finish(self) -> None:
        client = MockClient(
            [
                response(tool_calls=[tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
                response(
                    tool_calls=[
                        tool_call("finish", {"answer": "No", "explanation": "UNSAT proved it."})
                    ]
                ),
            ]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock"))
        result = solver.solve("Is there an integer both greater than 5 and less than 3?")

        self.assertTrue(result.verified)
        self.assertEqual(result.answer, "No")
        self.assertIs(result.proof_status, ProofStatus.PROOF_BY_CONTRADICTION)
        self.assertEqual(result.extraction_method, "tool_call_finish")
        self.assertEqual(result.iterations, 2)
        self.assertEqual(len(result.smt_history), 1)
        self.assertEqual(result.smt_history[0]["z3_output"]["sat_result"], "unsat")
        self.assertEqual(len(result.token_usage), 2)

    def test_error_repair_loop(self) -> None:
        client = MockClient(
            [
                response(tool_calls=[tool_call("z3_solve", {"smt_code": BROKEN_PROGRAM})]),
                response(tool_calls=[tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
                response(tool_calls=[tool_call("finish", {"answer": "No"})]),
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
                response(content="Let me think about this..."),  # no tool call -> nudge
                response(tool_calls=[tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
                response(tool_calls=[tool_call("finish", {"answer": "No"})]),
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
        client = MockClient([response(content="hmm")] * 3)
        solver = AgenticSolver(client, config)
        result = solver.solve("q")

        self.assertFalse(result.verified)
        self.assertIsNone(result.answer)
        self.assertIsNone(result.proof_status)
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
                response(content=textual),
                response(tool_calls=[tool_call("finish", {"answer": "No"})]),
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
                response(tool_calls=[tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
                response(tool_calls=[tool_call("finish", {"answer": "No"})]),
            ]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock", max_iterations=1))
        result = solver.solve("q")

        self.assertTrue(result.verified)
        self.assertEqual(result.answer, "No")
        self.assertIs(result.proof_status, ProofStatus.PROOF_BY_CONTRADICTION)

    def test_sat_does_not_get_finish_followup(self) -> None:
        # A SAT result on the last iteration is not a proof -> no follow-up.
        client = MockClient(
            [response(tool_calls=[tool_call("z3_solve", {"smt_code": SAT_PROGRAM})])]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock", max_iterations=1))
        result = solver.solve("q")

        self.assertFalse(result.verified)
        self.assertEqual(len(client.calls), 1)

    def test_lenient_extraction(self) -> None:
        config = AgenticConfig(
            model="mock", max_iterations=2, max_consecutive_nudges=0, lenient_extraction=True
        )
        client = MockClient([response(content="Therefore the answer is Yes.")])
        solver = AgenticSolver(client, config)
        result = solver.solve("q")

        self.assertFalse(result.verified)
        self.assertEqual(result.answer, "Yes")
        self.assertIs(result.proof_status, ProofStatus.UNVERIFIED)
        self.assertEqual(result.extraction_method, "text_pattern_extracted")

    def test_transcript_has_reasoning_but_api_messages_do_not(self) -> None:
        resp = response(
            tool_calls=[
                tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM}, call_id="c1"),
                tool_call("finish", {"answer": "Yes"}, call_id="c2"),
            ]
        )
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
        client = MockClient(
            [
                response(tool_calls=[tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
                response(tool_calls=[tool_call("finish", {"answer": "A"})]),
            ]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock"))
        solver.solve("q", answer_format="Answer choices:\n  A) foo\n  B) bar")

        user_msg = client.calls[0]["messages"][1]
        self.assertIn("Answer choices", user_msg["content"])


class TestFinishDiscipline(unittest.TestCase):
    """finish() is only `verified` when backed by a decisive Z3 verdict."""

    def test_premature_finish_rejected_then_model_complies(self) -> None:
        client = MockClient(
            [
                response(tool_calls=[tool_call("finish", {"answer": "Yes"})]),  # no proof yet
                response(tool_calls=[tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
                response(tool_calls=[tool_call("finish", {"answer": "Yes"})]),
            ]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock"))
        result = solver.solve("q")

        self.assertTrue(result.verified)
        self.assertIs(result.proof_status, ProofStatus.PROOF_BY_CONTRADICTION)
        # The rejection landed as a tool message instructing the model
        rejection = client.calls[1]["messages"][-1]
        self.assertEqual(rejection["role"], "tool")
        self.assertIn("REJECTED", rejection["content"])

    def test_persistent_premature_finish_accepted_unverified(self) -> None:
        config = AgenticConfig(model="mock", max_finish_rejections=1)
        client = MockClient(
            [
                response(tool_calls=[tool_call("finish", {"answer": "Yes"})]),  # rejected
                response(tool_calls=[tool_call("finish", {"answer": "Yes"})]),  # accepted
            ]
        )
        solver = AgenticSolver(client, config)
        result = solver.solve("q")

        self.assertEqual(result.answer, "Yes")  # the answer is preserved...
        self.assertFalse(result.verified)  # ...but never claims verification
        self.assertIs(result.proof_status, ProofStatus.UNVERIFIED)
        self.assertEqual(result.extraction_method, "tool_call_finish_unverified")
        self.assertEqual(len(result.smt_history), 0)

    def test_same_turn_z3_and_finish_is_verified(self) -> None:
        # z3_solve runs before finish within a turn, so the proof backs it.
        client = MockClient(
            [
                response(
                    tool_calls=[
                        tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM}, call_id="c1"),
                        tool_call("finish", {"answer": "No"}, call_id="c2"),
                    ]
                )
            ]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock"))
        result = solver.solve("q")

        self.assertTrue(result.verified)
        self.assertIs(result.proof_status, ProofStatus.PROOF_BY_CONTRADICTION)
        self.assertEqual(result.iterations, 1)

    def test_sat_backed_finish_is_sat_witness(self) -> None:
        client = MockClient(
            [
                response(tool_calls=[tool_call("z3_solve", {"smt_code": SAT_PROGRAM})]),
                response(tool_calls=[tool_call("finish", {"answer": "Yes"})]),
            ]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock"))
        result = solver.solve("q")

        self.assertTrue(result.verified)
        self.assertIs(result.proof_status, ProofStatus.SAT_WITNESS)

    def test_error_backed_finish_is_rejected(self) -> None:
        # An errored Z3 run is not a decisive verdict.
        client = MockClient(
            [
                response(tool_calls=[tool_call("z3_solve", {"smt_code": BROKEN_PROGRAM})]),
                response(tool_calls=[tool_call("finish", {"answer": "Yes"})]),  # rejected
                response(tool_calls=[tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
                response(tool_calls=[tool_call("finish", {"answer": "Yes"})]),
            ]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock"))
        result = solver.solve("q")

        self.assertTrue(result.verified)
        self.assertIs(result.proof_status, ProofStatus.PROOF_BY_CONTRADICTION)
        self.assertEqual(len(client.calls), 4)

    def test_malformed_finish_args_get_tool_response(self) -> None:
        # A truncated finish arguments string must still receive a tool
        # message - a dangling tool_call_id would 400 the next API call.
        client = MockClient(
            [
                response(tool_calls=[raw_tool_call("finish", '{"answer": "Yes", "explan')]),
                response(tool_calls=[tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
                response(tool_calls=[tool_call("finish", {"answer": "Yes"})]),
            ]
        )
        solver = AgenticSolver(client, AgenticConfig(model="mock"))
        result = solver.solve("q")

        self.assertTrue(result.verified)
        # The second call's payload must answer the malformed tool_call_id
        second_call_messages = client.calls[1]["messages"]
        assistant_idx = max(
            i for i, m in enumerate(second_call_messages) if m["role"] == "assistant"
        )
        follow_up = second_call_messages[assistant_idx + 1]
        self.assertEqual(follow_up["role"], "tool")
        self.assertIn("ERROR", follow_up["content"])


class TestPerCallOverrides(unittest.TestCase):
    """solve() honors per-call temperature/max_tokens overrides."""

    def _one_shot_client(self) -> MockClient:
        return MockClient(
            [
                response(tool_calls=[tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
                response(tool_calls=[tool_call("finish", {"answer": "No"})]),
            ]
        )

    def test_defaults_send_no_temperature(self) -> None:
        client = self._one_shot_client()
        AgenticSolver(client, AgenticConfig(model="mock")).solve("q")
        self.assertNotIn("temperature", client.calls[0])
        self.assertEqual(client.calls[0]["max_completion_tokens"], 16384)

    def test_explicit_overrides_are_sent(self) -> None:
        client = self._one_shot_client()
        AgenticSolver(client, AgenticConfig(model="mock")).solve(
            "q", temperature=0.7, max_tokens=2048
        )
        for call in client.calls:
            self.assertEqual(call["temperature"], 0.7)
            self.assertEqual(call["max_completion_tokens"], 2048)


if __name__ == "__main__":
    unittest.main()
