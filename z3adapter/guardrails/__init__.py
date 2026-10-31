"""Formal guardrailing of agent trajectories via the agentic SMT-LIB backend.

This package turns ProofOfThought's agentic scratchpad into a trajectory
guardrail for tool-calling agents, targeting the TauBench and tau2-bench
(τ²) formats out of the box:

1. **Autoformalize** a domain policy (retail/airline/telecom rulebook) into a
   step-indexed SMT-LIB theory with per-rule violation predicates -
   :func:`formalize_policy`, one ``AgenticSolver`` run, done once and saved.
2. **Audit** trajectories against it - :class:`TrajectoryGuardrail` asserts
   the theory, the concrete tool-call facts, and ``any_violation``; a clean
   UNSAT is a proof by contradiction that no rule is violated at any step
   (individually or in composition), a clean SAT is a concrete violation
   witness. The verdict inherits the library's ``ProofStatus`` semantics and
   its audit program can be independently re-checked via
   ``AgenticBackend.reverify``.
3. **Gate** live tool calls - :meth:`TrajectoryGuardrail.check_tool_call`
   audits a proposed call as the next step on top of the conversation so
   far, before it executes.

See ``docs/guardrails.md`` and ``examples/guardrail_taubench.py``.
"""

from z3adapter.guardrails.guardrail import (
    GuardrailStatus,
    GuardrailVerdict,
    TrajectoryGuardrail,
)
from z3adapter.guardrails.policy import (
    Policy,
    formalize_policy,
    tau2_policy,
    taubench_policy,
    verify_theory,
)
from z3adapter.guardrails.trajectory import (
    ToolCallRecord,
    Trajectory,
    load_tau2_trajectories,
    load_taubench_trajectories,
    render_trajectory,
    trajectory_from_messages,
)

__all__ = [
    "GuardrailStatus",
    "GuardrailVerdict",
    "TrajectoryGuardrail",
    "Policy",
    "formalize_policy",
    "verify_theory",
    "taubench_policy",
    "tau2_policy",
    "Trajectory",
    "ToolCallRecord",
    "load_taubench_trajectories",
    "load_tau2_trajectories",
    "trajectory_from_messages",
    "render_trajectory",
]
