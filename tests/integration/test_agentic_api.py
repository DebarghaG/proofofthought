"""Integration tests: agentic backend through the high-level API."""

import os
import tempfile
import unittest

from tests.mock_llm import UNSAT_PROGRAM, MockClient, response, tool_call
from z3adapter.agentic import ProofStatus
from z3adapter.backends.agentic_backend import AgenticBackend
from z3adapter.reasoning import EvaluationPipeline, ProofOfThought


def _verified_trajectory(answer: str) -> list[dict]:
    """One agentic trajectory: prove by contradiction, then finish."""
    return [
        response(tool_calls=[tool_call("z3_solve", {"smt_code": UNSAT_PROGRAM})]),
        response(tool_calls=[tool_call("finish", {"answer": answer, "explanation": "UNSAT."})]),
    ]


class TestAgenticProofOfThought(unittest.TestCase):
    """ProofOfThought with backend='agentic' (the new default)."""

    def test_agentic_is_default_backend(self) -> None:
        pot = ProofOfThought(llm_client=MockClient(_verified_trajectory("Yes")))
        self.assertEqual(pot.backend_type, "agentic")
        self.assertIsInstance(pot.backend, AgenticBackend)
        self.assertIsNotNone(pot.agentic_solver)
        self.assertIsNone(pot.generator)  # single-shot generator has no agentic role

    def test_query_returns_bool_and_text(self) -> None:
        pot = ProofOfThought(llm_client=MockClient(_verified_trajectory("No")), model="mock")
        result = pot.query("Is there an integer both greater than 5 and less than 3?")

        self.assertTrue(result.success)
        self.assertTrue(result.verified)
        self.assertEqual(result.proof_status, ProofStatus.PROOF_BY_CONTRADICTION.value)
        self.assertIs(result.answer, False)  # "No" -> False
        self.assertEqual(result.answer_text, "No")
        self.assertEqual(result.unsat_count, 1)
        self.assertEqual(len(result.smt_history), 1)

    def test_query_mcq_answer_keeps_text(self) -> None:
        pot = ProofOfThought(llm_client=MockClient(_verified_trajectory("B")), model="mock")
        result = pot.query("Which option is correct?")

        self.assertTrue(result.success)
        self.assertTrue(result.verified)
        self.assertIsNone(result.answer)  # "B" is not boolean-like
        self.assertEqual(result.answer_text, "B")

    def test_verify_timeout_reaches_agentic_z3(self) -> None:
        pot = ProofOfThought(
            llm_client=MockClient(_verified_trajectory("Yes")), model="mock", verify_timeout=1234
        )
        assert pot.agentic_solver is not None
        self.assertEqual(pot.agentic_solver.executor.timeout_ms, 1234)
        self.assertEqual(pot.backend.executor.timeout_ms, 1234)  # type: ignore[attr-defined]

    def test_postprocessors_with_agentic_raise_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            ProofOfThought(
                llm_client=MockClient([]),
                postprocessors=["self_refine"],
            )

    def test_save_program_writes_final_smt2_and_reverifies(self) -> None:
        pot = ProofOfThought(llm_client=MockClient(_verified_trajectory("Yes")), model="mock")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "program.smt2")
            result = pot.query("q", save_program=True, program_path=path)
            self.assertTrue(result.success)
            with open(path) as f:
                self.assertEqual(f.read(), UNSAT_PROGRAM)

            # The saved program is the proof artifact: reverify() checks that
            # it still yields the verdict that backed the answer, without the
            # caller having to reason about negation polarity.
            backend = pot.backend
            assert isinstance(backend, AgenticBackend)
            self.assertTrue(backend.reverify(path, result.proof_status))
            # An unverified answer has no proof to re-establish.
            self.assertFalse(backend.reverify(path, ProofStatus.UNVERIFIED))

    def test_previous_backends_still_constructible(self) -> None:
        # json backend must keep working untouched
        pot = ProofOfThought(llm_client=MockClient([]), backend="json")
        self.assertEqual(pot.backend_type, "json")
        self.assertEqual(pot.backend.get_file_extension(), ".json")
        self.assertIsNone(pot.agentic_solver)
        self.assertIsNotNone(pot.generator)


class TestAgenticEvaluationPipeline(unittest.TestCase):
    """EvaluationPipeline over the agentic backend."""

    def test_evaluate_boolean_dataset(self) -> None:
        pot = ProofOfThought(
            llm_client=MockClient(_verified_trajectory("Yes"), cycle=True), model="mock"
        )
        dataset = [
            {"question": "Is 7 > 3?", "answer": True, "qid": "q1"},
            {"question": "Is 2 > 9?", "answer": False, "qid": "q2"},
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
        # Mock always answers "Yes" -> q1 correct, q2 wrong; both in binary metrics
        self.assertEqual(result.metrics.total_samples, 2)
        self.assertEqual(result.metrics.correct_answers, 1)
        self.assertEqual(result.metrics.wrong_answers, 1)
        self.assertEqual(result.metrics.failed_answers, 0)
        self.assertEqual(result.y_true, [1, 0])
        self.assertEqual(result.y_pred, [1, 1])

    def test_evaluate_mcq_dataset_scores_answer_text(self) -> None:
        # Verified non-boolean answers are scored by normalized text compare,
        # not dumped into the failed bucket (and int(ground_truth) is never
        # attempted on a letter).
        pot = ProofOfThought(
            llm_client=MockClient(_verified_trajectory("A"), cycle=True), model="mock"
        )
        dataset = [
            {"question": "Pick one.", "answer": "A", "qid": "m1"},
            {"question": "Pick one.", "answer": "B", "qid": "m2"},
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
        self.assertEqual(result.metrics.correct_answers, 1)  # "A" == "A"
        self.assertEqual(result.metrics.wrong_answers, 1)  # "A" != "B"
        self.assertEqual(result.metrics.failed_answers, 0)
        # No binary metrics for non-boolean pairs - and no ValueError either.
        self.assertEqual(result.y_true, [])

    def test_evaluate_string_ground_truth_with_boolean_answer(self) -> None:
        # Regression: ground_truth "true"/"false" strings used to hit
        # int("true") and crash the run.
        pot = ProofOfThought(
            llm_client=MockClient(_verified_trajectory("Yes"), cycle=True), model="mock"
        )
        dataset = [{"question": "q", "answer": "true", "qid": "s1"}]
        with tempfile.TemporaryDirectory() as tmp:
            evaluator = EvaluationPipeline(proof_of_thought=pot, output_dir=tmp)
            result = evaluator.evaluate(
                dataset=dataset, answer_field="answer", id_field="qid", skip_existing=False
            )
        self.assertEqual(result.metrics.correct_answers, 1)
        self.assertEqual(result.y_true, [1])


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
            # Program-level satisfiability, NOT the question's answer - see
            # the module docstring; reverify() is the question-level API.
            self.assertIs(result.answer, True)
            self.assertEqual(result.sat_count, 1)
        finally:
            os.unlink(path)

    def test_reverify_proof_by_contradiction(self) -> None:
        backend = AgenticBackend()
        with tempfile.NamedTemporaryFile("w", suffix=".smt2", delete=False) as f:
            f.write(UNSAT_PROGRAM)
            path = f.name
        try:
            self.assertTrue(backend.reverify(path, ProofStatus.PROOF_BY_CONTRADICTION))
            self.assertTrue(backend.reverify(path, "proof_by_contradiction"))  # string form
            self.assertFalse(backend.reverify(path, ProofStatus.SAT_WITNESS))
            self.assertFalse(backend.reverify(path, ProofStatus.UNVERIFIED))
            self.assertFalse(backend.reverify(path, None))
        finally:
            os.unlink(path)

    def test_reverify_missing_file_raises(self) -> None:
        backend = AgenticBackend()
        with self.assertRaises(OSError):
            backend.reverify("/nonexistent/path.smt2", ProofStatus.PROOF_BY_CONTRADICTION)

    def test_missing_file(self) -> None:
        backend = AgenticBackend()
        result = backend.execute("/nonexistent/path.smt2")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)


if __name__ == "__main__":
    unittest.main()
