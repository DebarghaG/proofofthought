"""Agentic SMT-LIB scratchpad reasoning.

This package implements the agentic paradigm for ProofOfThought: instead of
generating one whole program and executing it, the LLM iteratively interacts
with an SMT-LIB scratchpad through tool calls (``z3_solve``), inspects Z3's
verdict, repairs or strengthens its encoding, and terminates the loop with an
explicit ``finish`` call once the answer is formally verified.

Every accepted answer carries a :class:`ProofStatus` describing how the
trajectory backs it — ``PROOF_BY_CONTRADICTION`` (a clean UNSAT of the
negated candidate), ``SAT_WITNESS`` (a satisfying model), or ``UNVERIFIED``
(an answer recorded without a decisive verdict). This makes the verification
strength of each answer machine-checkable, which is the point of the
paradigm: the trajectory is an interpretability artifact, not just a chat
log.

This is the direction the library is moving in going forward; the classic
single-shot ``smt2`` and ``json`` backends remain fully supported.
"""

from z3adapter.agentic.agent import (
    FINISH_TOOL,
    Z3_TOOL,
    AgenticConfig,
    AgenticResult,
    AgenticSolver,
    ProofStatus,
)
from z3adapter.agentic.executor import (
    Z3Executor,
    last_smt_result_is_useful,
    run_smt,
    verdict_counts,
    z3_result_has_error,
    z3_result_is_useful,
)
from z3adapter.agentic.parsing import extract_answer_from_text, parse_tool_calls_from_content

__all__ = [
    "AgenticConfig",
    "AgenticResult",
    "AgenticSolver",
    "ProofStatus",
    "Z3_TOOL",
    "FINISH_TOOL",
    "Z3Executor",
    "run_smt",
    "verdict_counts",
    "z3_result_is_useful",
    "z3_result_has_error",
    "last_smt_result_is_useful",
    "parse_tool_calls_from_content",
    "extract_answer_from_text",
]
