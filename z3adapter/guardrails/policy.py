"""Domain policies and their autoformalization into SMT-LIB theories.

A :class:`Policy` is the natural-language rulebook an agent must follow (a
TauBench ``wiki.md`` or tau2-bench ``policy.md``). :func:`formalize_policy`
autoformalizes it by *reusing the agentic backend as-is*: the same
``AgenticSolver`` loop that answers reasoning questions is pointed at the
policy with a formalization system prompt, iterates ``z3_solve`` until Z3
accepts a **consistent** (``sat``) step-indexed theory of the rules, and the
last Z3-validated program of the trajectory becomes the formal artifact.

The theory is deliberately trajectory-free - it declares the vocabulary
(which tool ran at step i, was the user's explicit confirmation on record,
what state a tool result revealed, per-rule violation predicates) and the
policy axioms over it. The guardrail later combines it with concrete
per-trajectory facts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from z3adapter.agentic.agent import AgenticConfig, AgenticResult, AgenticSolver
from z3adapter.agentic.executor import Z3Executor, z3_result_is_useful

logger = logging.getLogger(__name__)

__all__ = [
    "Policy",
    "formalize_policy",
    "verify_theory",
    "taubench_policy",
    "tau2_policy",
]


FORMALIZE_SYSTEM_PROMPT = """You are a formal-methods engineer. Autoformalize the DOMAIN POLICY you are given into one reusable SMT-LIB 2.6 theory for auditing agent tool-call trajectories, using the z3_solve tool as an iterative scratchpad.

THEORY REQUIREMENTS:
1. Step-indexed vocabulary: model a trajectory as steps 0..N. Declare uninterpreted functions/predicates over step indices for whatever the rules depend on, e.g.:
   - which tool was called at step i (use an enumerated datatype of the domain's tool names when they are known, else (declare-fun tool_of (Int) String)),
   - key argument and state observations (order/reservation status at call time, payment method, item counts, ...),
   - process events (user was authenticated by step i, user explicitly confirmed the exact action before step i, ...).
2. One violation predicate per enforceable rule (define-fun rule_<k>_violated ((i Int)) Bool ...), covering BOTH single-call preconditions AND compositional rules across steps: required ordering (authenticate before account actions, explicit confirmation before every database write), cardinality (tools that may be called at most once), and state flow (a later call's precondition established or destroyed by an earlier call's effect).
3. A top-level (define-fun any_violation () Bool (exists ((i Int)) ...)) combining the rule predicates.
4. Do NOT assert any concrete trajectory facts - the theory must stay reusable. Skip rules that are purely stylistic or unformalizable (tone, "do not make up information"); encode the enforceable ones.
5. The theory must be self-contained and CONSISTENT: end with (check-sat), call z3_solve, and repair until it returns a clean sat with no errors.

Once z3_solve returns a clean sat for the complete theory, call finish with answer "OK"."""


@dataclass
class Policy:
    """A domain policy: rulebook text plus its (optional) formal theory.

    ``formal_theory`` is a complete SMT-LIB program (ending in ``check-sat``)
    produced by :func:`formalize_policy` and re-checkable at any time with
    :func:`verify_theory` - the same independent-recheck contract as
    ``AgenticBackend.reverify``.
    """

    name: str
    text: str
    formal_theory: str | None = None

    @classmethod
    def from_markdown(cls, path: str | Path, name: str | None = None) -> Policy:
        """Load a policy from a raw rulebook file (wiki.md / policy.md)."""
        path = Path(path)
        return cls(name=name or path.stem, text=path.read_text())

    def save(self, path: str | Path) -> None:
        """Persist the policy (including its formal theory) as JSON."""
        with open(path, "w") as f:
            json.dump(self.__dict__, f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> Policy:
        """Load a policy previously written by :meth:`save`."""
        with open(path) as f:
            return cls(**json.load(f))


def _last_consistent_program(result: AgenticResult) -> str | None:
    """The most recent trajectory program Z3 accepted with a clean ``sat``."""
    for step in reversed(result.smt_history):
        z3_out = step.get("z3_output") or {}
        if z3_result_is_useful(z3_out) and z3_out.get("sat_result") == "sat":
            return step.get("smt_code")
    return None


def formalize_policy(
    policy: Policy,
    llm_client: Any,
    config: AgenticConfig | None = None,
) -> Policy:
    """Autoformalize a policy into an SMT-LIB theory via the agentic loop.

    Runs the standard ``AgenticSolver`` with the formalization system prompt;
    the returned Policy carries the last theory Z3 confirmed consistent
    (``sat``). Formalization costs LLM calls - persist the result with
    ``policy.save()`` and reload with ``Policy.load()`` instead of
    re-formalizing per run.

    Raises:
        ValueError: If the loop produced no Z3-validated consistent theory.
    """
    config = config or AgenticConfig()
    solver = AgenticSolver(llm_client, replace(config, system_prompt=FORMALIZE_SYSTEM_PROMPT))
    result = solver.solve(
        f"DOMAIN POLICY ({policy.name}):\n\n{policy.text}",
        answer_format='Call finish with answer "OK" once the theory checks out.',
    )
    theory = _last_consistent_program(result)
    if theory is None:
        raise ValueError(
            f"Formalization of policy {policy.name!r} produced no consistent "
            f"(sat) theory in {result.iterations} iterations"
            + (f": {result.error}" if result.error else ".")
        )
    logger.info(
        "Formalized policy %s in %d iterations (%d chars of SMT-LIB)",
        policy.name,
        result.iterations,
        len(theory),
    )
    return replace(policy, formal_theory=theory)


def verify_theory(policy: Policy, timeout_ms: int = 30000) -> bool:
    """Independently re-check that a policy's formal theory is consistent.

    A theory that has drifted to ``unsat`` (or errors) would prove any
    verdict vacuously, so guardrail results built on it are void.
    """
    if not policy.formal_theory:
        return False
    z3_out = Z3Executor(timeout_ms=timeout_ms).execute(policy.formal_theory)
    return z3_result_is_useful(z3_out) and z3_out.get("sat_result") == "sat"


# -- Benchmark policy locations ------------------------------------------------

# tau2 telecom splits its policy across files; main_policy.md is the agent's
# operating policy (the tech-support manual is reference material).
_TAU2_POLICY_FILENAMES = {"telecom": "main_policy.md"}


def taubench_policy(domain: str, repo_root: str | Path) -> Policy:
    """Load a TauBench domain policy (``tau_bench/envs/<domain>/wiki.md``)."""
    path = Path(repo_root) / "tau_bench" / "envs" / domain / "wiki.md"
    return Policy.from_markdown(path, name=f"taubench-{domain}")


def tau2_policy(domain: str, repo_root: str | Path) -> Policy:
    """Load a tau2-bench domain policy (``data/tau2/domains/<domain>/policy.md``)."""
    filename = _TAU2_POLICY_FILENAMES.get(domain, "policy.md")
    path = Path(repo_root) / "data" / "tau2" / "domains" / domain / filename
    return Policy.from_markdown(path, name=f"tau2-{domain}")
