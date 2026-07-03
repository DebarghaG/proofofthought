"""Guardrail TauBench / tau2-bench agent trajectories via formal verification.

Pipeline:
  1. Load a domain policy (tau-bench wiki.md or tau2 policy.md).
  2. Autoformalize it ONCE into a step-indexed SMT-LIB theory (agentic loop),
     and cache it to disk.
  3. Audit recorded trajectories: each audit asserts the theory, the concrete
     tool-call facts, and any_violation - UNSAT proves the trajectory safe
     (proof by contradiction), SAT witnesses a concrete rule violation.
  4. Demonstrate online gating of a single proposed tool call.

Run from the repo root (with tau benchmarks cloned into external/):

    git clone --depth 1 https://github.com/sierra-research/tau-bench external/tau-bench
    git clone --depth 1 https://github.com/sierra-research/tau2-bench external/tau2-bench
    python examples/guardrail_taubench.py --max-trajectories 3

Any OpenAI-compatible client works (OpenAI, AzureOpenAI, vLLM, Bedrock via
the BedrockClient shim).
"""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from z3adapter.agentic import AgenticConfig
from z3adapter.guardrails import (
    Policy,
    TrajectoryGuardrail,
    formalize_policy,
    load_tau2_trajectories,
    load_taubench_trajectories,
    tau2_policy,
    taubench_policy,
    verify_theory,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_client_and_model(model: str | None):
    """Pick a client from the environment: OpenAI key, or Bedrock fallback."""
    load_dotenv()
    if os.getenv("OPENAI_API_KEY"):
        from openai import OpenAI

        return OpenAI(), model or "gpt-5"
    # Bedrock (default AWS credential chain); see bedrock-connect.py
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "bedrock_connect", REPO_ROOT / "bedrock-connect.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.BedrockClient(), model or "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", choices=["taubench", "tau2"], default="taubench")
    parser.add_argument("--domain", default="retail")
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-trajectories", type=int, default=3)
    parser.add_argument(
        "--trajectories",
        default=None,
        help="Path to a results file (default: a checked-in fixture of the benchmark)",
    )
    args = parser.parse_args()

    client, model = make_client_and_model(args.model)
    config = AgenticConfig(model=model, max_iterations=10)

    # -- 1+2. Load and (once) formalize the policy --------------------------
    if args.benchmark == "taubench":
        policy = taubench_policy(args.domain, REPO_ROOT / "external" / "tau-bench")
        default_traj = (
            REPO_ROOT / "external/tau-bench/historical_trajectories" / f"gpt-4o-{args.domain}.json"
        )
        load = load_taubench_trajectories
    else:
        policy = tau2_policy(args.domain, REPO_ROOT / "external" / "tau2-bench")
        default_traj = (
            REPO_ROOT
            / "external/tau2-bench/data/tau2/results/final"
            / f"gpt-4.1-2025-04-14_{args.domain}_default_gpt-4.1-2025-04-14_4trials.json"
        )
        load = load_tau2_trajectories

    cache = REPO_ROOT / "results" / f"guardrail_policy_{policy.name}.json"
    if cache.exists():
        policy = Policy.load(cache)
        print(f"Loaded cached formal theory for {policy.name} ({cache})")
    else:
        print(f"Formalizing policy {policy.name} ({len(policy.text)} chars)...")
        policy = formalize_policy(policy, client, config)
        cache.parent.mkdir(exist_ok=True)
        policy.save(cache)
        print(f"Formal theory cached to {cache}")
    assert verify_theory(policy), "cached theory must re-check as consistent"
    print(f"Theory: {len(policy.formal_theory)} chars of SMT-LIB, consistent (sat)\n")

    # -- 3. Audit recorded trajectories --------------------------------------
    trajectories = load(args.trajectories or default_traj)[: args.max_trajectories]
    guard = TrajectoryGuardrail(client, policy, config)

    for verdict in guard.check_trajectories(trajectories):
        print(
            f"task {verdict.task_id} trial {verdict.trial}: "
            f"{verdict.status.upper()}  "
            f"(proof={verdict.proof_status}, "
            f"benchmark reward={verdict.metadata['benchmark_reward']}, "
            f"{verdict.result.iterations} verifier iterations)"
        )
        if verdict.explanation:
            print(f"    {verdict.explanation}")

    # -- 4. Online gating of one proposed tool call ---------------------------
    # Take the prefix of the first trajectory before its last tool call and
    # ask whether that call should be allowed to execute.
    traj = trajectories[0]
    last_call = traj.tool_calls[-1]
    prefix = traj.messages[: last_call.message_index]
    print(f"\nOnline gate: proposing {last_call.name} after {len(prefix)} messages...")
    verdict = guard.check_tool_call(prefix, last_call.name, last_call.arguments)
    print(f"  -> {verdict.status.upper()} (allowed={verdict.allowed})")


if __name__ == "__main__":
    main()
