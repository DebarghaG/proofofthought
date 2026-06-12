"""Integration tests: agentic backend through the high-level API."""

import json
import os
import tempfile
import unittest
from typing import Any

from z3adapter.backends.agentic_backend import AgenticBackend
from z3adapter.reasoning import EvaluationPipeline, ProofOfThought

UNSAT_PROGRAM = "(declare-const x Int)\n(assert (> x 5))\n(assert (< x 3))\n(check-sat)"


def _tool_call(name: str, args: dict[str, Any], call_id: str = "call_1") -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _response(tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"content": "", "tool_calls": tool_calls}, "finish_reason": "tool_calls"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class MockClient:
    """OpenAI-compatible client cycling through one scripted trajectory per query."""

    def __init__(self, trajectory: list[dict[str, Any]]) -> None:
        self._trajectory = trajectory
        self._pos = 0

        outer = self

        class _Completions:
            def create(self, **kwargs: Any) -> dict[str, Any]:
                resp = outer._trajectory[outer._pos % len(outer._trajectory)]
                outer._pos += 1
                return resp

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def _yes_no_trajectory(answer: str) -> list[dict[str, Any]]:
    return [
        _response([_tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
        _response([_tool_call("finish", {"answer": answer, "explanation": "UNSAT."})]),
    ]


class TestAgenticProofOfThought(unittest.TestCase):
    """ProofOfThought with backend='agentic' (the new default)."""

    def test_agentic_is_default_backend(self) -> None:
        pot = ProofOfThought(llm_client=MockClient(_yes_no_trajectory("Yes")))
        self.assertEqual(pot.backend_type, "agentic")
        self.assertIsInstance(pot.backend, AgenticBackend)
        self.assertIsNotNone(pot.agentic_solver)

    def test_query_returns_bool_and_text(self) -> None:
        pot = ProofOfThought(llm_client=MockClient(_yes_no_trajectory("No")), model="mock")
        result = pot.query("Is there an integer both greater than 5 and less than 3?")

        self.assertTrue(result.success)
        self.assertTrue(result.verified)
        self.assertIs(result.answer, False)  # "No" -> False
        self.assertEqual(result.answer_text, "No")
        self.assertEqual(result.unsat_count, 1)
        self.assertEqual(len(result.smt_history), 1)

    def test_query_mcq_answer_keeps_text(self) -> None:
        pot = ProofOfThought(llm_client=MockClient(_yes_no_trajectory("B")), model="mock")
        result = pot.query("Which option is correct?")

        self.assertTrue(result.success)
        self.assertIsNone(result.answer)  # "B" is not boolean-like
        self.assertEqual(result.answer_text, "B")

    def test_save_program_writes_final_smt2(self) -> None:
        pot = ProofOfThought(llm_client=MockClient(_yes_no_trajectory("Yes")), model="mock")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "program.smt2")
            result = pot.query("q", save_program=True, program_path=path)
            self.assertTrue(result.success)
            with open(path) as f:
                saved = f.read()
            self.assertEqual(saved, UNSAT_PROGRAM)

            # The saved program can be independently re-verified by the backend
            verify = pot.backend.execute(path)
            self.assertTrue(verify.success)
            self.assertIs(verify.answer, False)  # unsat

    def test_previous_backends_still_constructible(self) -> None:
        # json backend must keep working untouched
        pot = ProofOfThought(llm_client=MockClient([]), backend="json")
        self.assertEqual(pot.backend_type, "json")
        self.assertEqual(pot.backend.get_file_extension(), ".json")
        self.assertIsNone(pot.agentic_solver)


class TestAgenticEvaluationPipeline(unittest.TestCase):
    """EvaluationPipeline over the agentic backend."""

    def test_evaluate_boolean_dataset(self) -> None:
        pot = ProofOfThought(llm_client=MockClient(_yes_no_trajectory("Yes")), model="mock")
        dataset = [
            {"question": "Is 7 > 3?", "answer": True, "qid": "q1"},
            {"question": "Is 2 > 9?", "answer": True, "qid": "q2"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            evaluator = EvaluationPipeline(proof_of_thought=pot, output_dir=tmp)
            result = evaluator.evaluate(
                dataset=dataset,
                question_field="question",
                answer_field="answer",
                id_field="qid",
                skip_existing=False,
            )
        # Mock always answers "Yes" -> both samples answered True
        self.assertEqual(result.metrics.total_samples, 2)
        self.assertEqual(result.metrics.correct_answers, 2)
        self.assertEqual(result.metrics.accuracy, 1.0)


class TestAgenticBackendDirect(unittest.TestCase):
    """AgenticBackend as a standalone Backend implementation."""

    def test_execute_smt2_file(self) -> None:
        backend = AgenticBackend()
        with tempfile.NamedTemporaryFile("w", suffix=".smt2", delete=False) as f:
            f.write("(declare-const x Int)\n(assert (= x 1))\n(check-sat)")
            path = f.name
        try:
            result = backend.execute(path)
            self.assertTrue(result.success)
            self.assertIs(result.answer, True)
            self.assertEqual(result.sat_count, 1)
        finally:
            os.unlink(path)

    def test_missing_file(self) -> None:
        backend = AgenticBackend()
        result = backend.execute("/nonexistent/path.smt2")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)


if __name__ == "__main__":
    unittest.main()
