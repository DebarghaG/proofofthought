"""In-process Z3 SMT-LIB executor for the agentic scratchpad.

Takes SMT-LIB 2.6 code strings, evaluates them through the Z3 Python API
(``Z3_eval_smtlib2_string``) and returns structured results. Unlike the
``smt2`` backend this needs no Z3 CLI binary on PATH — only the
``z3-solver`` package — and supports the full command surface
(``check-sat``, ``get-model``, ``push``/``pop``, ...).

Each execution runs in a fresh ``z3.Context`` with the timeout set via a
per-script ``(set-option :timeout ...)`` — never via the process-global
``z3.set_param`` — so concurrent executions (e.g. EvaluationPipeline with
``num_workers > 1``) cannot race on each other's timeouts, and nothing leaks
into the user's own Z3 solvers.

Ported from the NL2SMTLIB-Benchmark evaluation harness, where the result
classification logic (``z3_result_is_useful``) was hardened against the
failure modes long agentic loops actually hit: errors *before* the verdict
line poisoning a default ``sat``, post-verdict ``(error "model is not
available")`` noise after a perfectly good ``unsat``, and "unknown constant"
being mistaken for an ``unknown`` solver verdict.
"""

from __future__ import annotations

import ast
import traceback
from typing import Any

import z3

_DECISIVE_RESULTS = {"sat", "unsat"}
_SMT_RESULTS = _DECISIVE_RESULTS | {"unknown"}


def _first_smt_result(output: str) -> str | None:
    """Return the first exact SMT result line from Z3 output, if any."""
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if line in _SMT_RESULTS:
            return line
    return None


def _has_error_before_result(output: str) -> bool:
    """Detect errors that occur before the first sat/unsat/unknown line."""
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in _SMT_RESULTS:
            return False
        if (
            line.startswith("(error")
            or line.startswith("unsupported")
            or line.startswith("ERROR:")
            or line.startswith("SMT-LIB error")
        ):
            return True
    return False


def z3_result_is_useful(z3_result: dict[str, Any] | None) -> bool:
    """True when a Z3 result gives a usable SAT/UNSAT verdict.

    Z3's full SMT-LIB evaluator can return output like
    ``(error ...)\\nsat`` after declarations failed. That final "sat" is the
    empty/default context, not a useful result for the model to finish from.
    A post-verdict error, such as ``unsat\\n(error ... model is not
    available)``, is still useful because the decisive solver result came
    first.
    """
    if not isinstance(z3_result, dict) or not z3_result.get("success"):
        return False

    sat_result = z3_result.get("sat_result")
    if sat_result not in _DECISIVE_RESULTS:
        return False

    output = z3_result.get("output") or ""
    if _first_smt_result(output) != sat_result:
        return False
    return not _has_error_before_result(output)


def z3_result_has_error(z3_result: dict[str, Any]) -> bool:
    """True when Z3 produced syntactic/tool errors, even alongside sat output.

    The complement of :func:`z3_result_is_useful` restricted to error-shaped
    failures; used by the agent's nudge policy to decide between "fix your
    SMT code" and "your encoding ran but didn't prove anything".
    """
    if z3_result_is_useful(z3_result):
        return False
    output = str(z3_result.get("output") or "")
    error = str(z3_result.get("error") or "")
    combined = f"{output}\n{error}".lower()
    return (
        not z3_result.get("success")
        or bool(z3_result.get("error"))
        or "(error" in combined
        or "unsupported" in combined
    )


def last_smt_result_is_useful(smt_history: list[dict[str, Any]] | None) -> bool:
    """Return whether the last recorded SMT history entry is useful.

    Entries are ``{"smt_code": ..., "z3_output": ...}`` dicts everywhere.
    This is the guard the agent uses to decide whether a finish() call is
    backed by a decisive verdict.
    """
    if not smt_history:
        return False
    return z3_result_is_useful(smt_history[-1].get("z3_output"))


def verdict_counts(sat_result: str | None) -> tuple[int, int]:
    """Map a single sat_result to ``(sat_count, unsat_count)``.

    Single source of the verdict→counts presentation used by both the
    high-level QueryResult and AgenticBackend's VerificationResult.
    """
    return (1 if sat_result == "sat" else 0, 1 if sat_result == "unsat" else 0)


class Z3Executor:
    """Execute SMT-LIB code via the Z3 Python API and return structured results."""

    def __init__(self, timeout_ms: int = 30000) -> None:
        self.timeout_ms = timeout_ms

    def execute(self, smt_code: str) -> dict[str, Any]:
        """Execute SMT-LIB code that may contain (check-sat), (get-model), etc.

        Uses Z3's low-level SMT-LIB command evaluation for full compatibility.
        The timeout is injected as a leading ``(set-option :timeout ...)`` so
        it is scoped to this execution's context; a ``set-option`` inside the
        user's script comes later and therefore overrides ours.

        Returns:
            {
                "success": bool,
                "output": str,             # stdout from Z3
                "error": str | None,       # error message if any
                "sat_result": str | None,  # "sat", "unsat", "unknown", or None
            }
        """
        try:
            ctx = z3.Context()
            script = f"(set-option :timeout {int(self.timeout_ms)})\n{smt_code}"

            try:
                output = z3.Z3_eval_smtlib2_string(ctx.ref(), script)
            except z3.Z3Exception as e:
                # Z3 throws on errors but the message may contain useful output
                # e.g., "unsat\n(error ...)" when get-model is called after unsat
                err_str = str(e)
                clean = err_str
                if clean.startswith("b'") or clean.startswith('b"'):
                    try:
                        decoded = ast.literal_eval(clean)
                        clean = decoded.decode() if isinstance(decoded, bytes) else decoded
                    except (ValueError, SyntaxError):
                        pass

                # Try to extract an exact sat/unsat/unknown result line from
                # the exception text. Do not treat "unknown constant" as an
                # "unknown" solver verdict.
                sat_result = _first_smt_result(clean)
                if sat_result:
                    is_useful = z3_result_is_useful(
                        {
                            "success": True,
                            "output": clean,
                            "error": None,
                            "sat_result": sat_result,
                        }
                    )
                    return {
                        "success": is_useful,
                        "output": clean.strip(),
                        "error": None if is_useful else clean.strip(),
                        "sat_result": sat_result,
                    }
                return {
                    "success": False,
                    "output": err_str,
                    "error": f"SMT-LIB error: {err_str}",
                    "sat_result": None,
                }
            except Exception as e:
                return {
                    "success": False,
                    "output": "",
                    "error": f"SMT-LIB error: {str(e)}",
                    "sat_result": None,
                }

            output = output.strip() if output else ""

            # Check for Z3 error in output - but first extract sat/unsat if
            # present (e.g., "unsat\n(error ...)" is common when get-model is
            # called after unsat).
            has_error = "(error" in output or _has_error_before_result(output)
            sat_result = _first_smt_result(output)

            # If we found a useful sat/unsat result, treat as success even if
            # there was a non-fatal post-verdict error (e.g., get-model after
            # unsat). Errors before the first result make the verdict unusable.
            if has_error and not z3_result_is_useful(
                {
                    "success": True,
                    "output": output,
                    "error": None,
                    "sat_result": sat_result,
                }
            ):
                return {
                    "success": False,
                    "output": output,
                    "error": output,
                    "sat_result": None,
                }

            return {
                "success": True,
                "output": output,
                "error": None,
                "sat_result": sat_result,
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": f"Z3 execution error: {str(e)}\n{traceback.format_exc()}",
                "sat_result": None,
            }


def run_smt(smt_code: str, timeout_ms: int = 30000) -> dict[str, Any]:
    """Run SMT-LIB code and return a result dict.

    Convenience wrapper constructing a fresh :class:`Z3Executor` per call;
    executor construction is trivially cheap and this keeps the timeout
    explicit instead of frozen in a module-level singleton.
    """
    return Z3Executor(timeout_ms=timeout_ms).execute(smt_code)
