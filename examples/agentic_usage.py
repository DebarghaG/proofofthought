"""Agentic SMT-LIB scratchpad usage — the paradigm ProofOfThought is moving towards.

The model iteratively calls the z3_solve tool, reads Z3's verdict, repairs its
encoding, and calls finish only once the answer is formally verified
(canonically a clean UNSAT of the negated candidate answer).

Works with any OpenAI-compatible client: OpenAI, AzureOpenAI, or a local
vLLM/sglang endpoint wrapped in the OpenAI SDK.
"""

import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

from z3adapter.agentic import AgenticConfig, AgenticSolver
from z3adapter.reasoning import ProofOfThought

logging.basicConfig(level=logging.INFO)

load_dotenv()


def main() -> None:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    # For a local endpoint instead:
    # client = OpenAI(base_url="http://localhost:8000/v1", api_key="none")

    # --- High-level API: agentic is the default backend ------------------
    pot = ProofOfThought(llm_client=client, model="gpt-5")

    result = pot.query("Is there an integer that is both greater than 5 and less than 3?")
    print(f"Answer (bool):  {result.answer}")
    print(f"Answer (text):  {result.answer_text}")
    print(f"Verified:       {result.verified}")
    print(f"Iterations:     {result.iterations}")
    print("Trajectory:")
    for i, step in enumerate(result.smt_history or [], 1):
        verdict = step["z3_output"]["sat_result"]
        print(f"  [{i}] z3_solve -> {verdict}")
        print("      " + step["smt_code"].replace("\n", "\n      "))

    # --- Direct solver access: full control over the loop ----------------
    config = AgenticConfig(model="gpt-5", max_iterations=10, max_consecutive_nudges=2)
    solver = AgenticSolver(client, config)
    direct = solver.solve(
        "If all bloops are razzies and all razzies are lazzies, "
        "are all bloops definitely lazzies?",
        answer_format="Answer with exactly one of: Yes, No.",
    )
    print(f"\nDirect solve: {direct.answer} (via {direct.extraction_method})")
    print(f"Token usage: {sum(u.get('total_tokens', 0) for u in direct.token_usage)} total")


if __name__ == "__main__":
    main()
