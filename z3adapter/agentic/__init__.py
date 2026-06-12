"""Agentic SMT-LIB scratchpad reasoning.

This package implements the agentic paradigm for ProofOfThought: instead of
generating one whole program and executing it, the LLM iteratively interacts
with an SMT-LIB scratchpad through tool calls (``z3_solve``), inspects Z3's
verdict, repairs or strengthens its encoding, and terminates the loop with an
explicit ``finish`` call once the answer is formally verified.

This is the direction the library is moving in going forward; the classic
single-shot ``smt2`` and ``json`` backends remain fully supported.
"""

from z3adapter.agentic.agent import (
    FINISH_TOOL,
    Z3_TOOL,
    AgenticConfig,
    AgenticResult,
    AgenticSolver,
)
from z3adapter.agentic.executor import Z3Executor, run_smt, z3_result_is_useful
from z3adapter.agentic.parsing import extract_answer_from_text, parse_tool_calls_from_content

__all__ = [
    "AgenticConfig",
    "AgenticResult",
    "AgenticSolver",
    "Z3_TOOL",
    "FINISH_TOOL",
    "Z3Executor",
    "run_smt",
    "z3_result_is_useful",
    "parse_tool_calls_from_content",
    "extract_answer_from_text",
]
