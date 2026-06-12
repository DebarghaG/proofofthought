"""Unit tests for the agentic in-process Z3 executor."""

import time
import unittest

from z3adapter.agentic.executor import (
    Z3Executor,
    last_smt_result_is_useful,
    run_smt,
    verdict_counts,
    z3_result_has_error,
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

    def test_run_smt_accepts_timeout(self) -> None:
        result = run_smt("(check-sat)", timeout_ms=5000)
        self.assertEqual(result["sat_result"], "sat")

    def test_timeout_is_per_execution_not_global(self) -> None:
        # A hard nonlinear problem under a tiny timeout must return promptly
        # (no decisive verdict) - and, because the timeout is injected as a
        # per-script (set-option :timeout), nothing leaks into other solvers.
        hard = (
            "(declare-const x Int)(declare-const y Int)(declare-const z Int)\n"
            "(assert (and (> x 0) (> y 0) (> z 0)))\n"
            "(assert (= (+ (* x x x) (* y y y)) (* z z z)))\n"
            "(check-sat)"
        )
        start = time.time()
        result = Z3Executor(timeout_ms=300).execute(hard)
        elapsed = time.time() - start
        self.assertLess(elapsed, 10.0)
        self.assertNotIn(result["sat_result"], ("sat", "unsat"))
        # An easy problem right after is unaffected by the tiny timeout.
        after = Z3Executor(timeout_ms=30000).execute(
            "(declare-const a Int)(assert (> a 5))(check-sat)"
        )
        self.assertEqual(after["sat_result"], "sat")

    def test_user_set_option_overrides_injected_timeout(self) -> None:
        # A script-level (set-option :timeout) comes after the injected one
        # and therefore wins - documented escape hatch.
        result = Z3Executor(timeout_ms=30000).execute("(set-option :timeout 9999)\n(check-sat)")
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

    def test_verdict_counts(self) -> None:
        self.assertEqual(verdict_counts("sat"), (1, 0))
        self.assertEqual(verdict_counts("unsat"), (0, 1))
        self.assertEqual(verdict_counts("unknown"), (0, 0))
        self.assertEqual(verdict_counts(None), (0, 0))

    def test_z3_result_has_error(self) -> None:
        clean_unsat = {"success": True, "output": "unsat", "error": None, "sat_result": "unsat"}
        self.assertFalse(z3_result_has_error(clean_unsat))
        failed = {"success": False, "output": "", "error": "boom", "sat_result": None}
        self.assertTrue(z3_result_has_error(failed))
        poisoned = {
            "success": True,
            "output": '(error "unknown constant y")\nsat',
            "error": None,
            "sat_result": "sat",
        }
        self.assertTrue(z3_result_has_error(poisoned))
        # unknown without errors: not useful, but also not an error
        unknown = {"success": True, "output": "unknown", "error": None, "sat_result": "unknown"}
        self.assertFalse(z3_result_has_error(unknown))


if __name__ == "__main__":
    unittest.main()
