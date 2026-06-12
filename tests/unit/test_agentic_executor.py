"""Unit tests for the agentic in-process Z3 executor."""

import unittest

from z3adapter.agentic.executor import (
    Z3Executor,
    last_smt_result_is_useful,
    run_smt,
    z3_result_is_useful,
)


class TestZ3Executor(unittest.TestCase):
    """Test in-process SMT-LIB execution via the Z3 Python API."""

    def setUp(self) -> None:
        self.executor = Z3Executor(timeout_ms=10000)

    def test_sat_program(self) -> None:
        result = self.executor.execute("(declare-const x Int)\n(assert (> x 5))\n(check-sat)")
        self.assertTrue(result["success"])
        self.assertEqual(result["sat_result"], "sat")

    def test_unsat_program(self) -> None:
        result = self.executor.execute(
            "(declare-const x Int)\n(assert (> x 5))\n(assert (< x 3))\n(check-sat)"
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["sat_result"], "unsat")

    def test_get_model_after_sat(self) -> None:
        result = self.executor.execute(
            "(declare-const x Int)\n(assert (= x 42))\n(check-sat)\n(get-model)"
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["sat_result"], "sat")
        self.assertIn("42", result["output"])

    def test_syntax_error(self) -> None:
        result = self.executor.execute("(this is not smt-lib")
        self.assertFalse(result["success"])
        self.assertIsNone(result["sat_result"])

    def test_undeclared_constant(self) -> None:
        result = self.executor.execute("(assert (> y 5))\n(check-sat)")
        # Error before the verdict line: the trailing default-context "sat"
        # must NOT be reported as a usable verdict.
        self.assertFalse(z3_result_is_useful(result))

    def test_post_verdict_error_is_still_useful(self) -> None:
        # get-model after unsat produces "unsat\n(error ...)" - the decisive
        # verdict came first so the result is still useful.
        result = self.executor.execute(
            "(declare-const x Int)\n(assert (> x 5))\n(assert (< x 3))\n" "(check-sat)\n(get-model)"
        )
        self.assertEqual(result["sat_result"], "unsat")
        self.assertTrue(z3_result_is_useful(result))

    def test_run_smt_convenience(self) -> None:
        result = run_smt("(check-sat)")
        self.assertTrue(result["success"])
        self.assertEqual(result["sat_result"], "sat")


class TestResultClassification(unittest.TestCase):
    """Test z3_result_is_useful / last_smt_result_is_useful edge cases."""

    def test_none_is_not_useful(self) -> None:
        self.assertFalse(z3_result_is_useful(None))

    def test_failed_result_is_not_useful(self) -> None:
        self.assertFalse(
            z3_result_is_useful(
                {"success": False, "output": "sat", "error": "boom", "sat_result": "sat"}
            )
        )

    def test_unknown_is_not_useful(self) -> None:
        self.assertFalse(
            z3_result_is_useful(
                {"success": True, "output": "unknown", "error": None, "sat_result": "unknown"}
            )
        )

    def test_error_before_verdict_is_not_useful(self) -> None:
        self.assertFalse(
            z3_result_is_useful(
                {
                    "success": True,
                    "output": '(error "line 1: unknown constant y")\nsat',
                    "error": None,
                    "sat_result": "sat",
                }
            )
        )

    def test_clean_unsat_is_useful(self) -> None:
        self.assertTrue(
            z3_result_is_useful(
                {"success": True, "output": "unsat", "error": None, "sat_result": "unsat"}
            )
        )

    def test_last_smt_result_empty_history(self) -> None:
        self.assertFalse(last_smt_result_is_useful([]))
        self.assertFalse(last_smt_result_is_useful(None))

    def test_last_smt_result_with_history(self) -> None:
        history = [
            {
                "smt_code": "(check-sat)",
                "z3_output": {
                    "success": True,
                    "output": "unsat",
                    "error": None,
                    "sat_result": "unsat",
                },
            }
        ]
        self.assertTrue(last_smt_result_is_useful(history))


if __name__ == "__main__":
    unittest.main()
