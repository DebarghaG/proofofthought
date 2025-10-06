#!/usr/bin/env python3
"""
Example: Implementing an Audited Reasoning Workflow with ProofOfThought.

This program demonstrates a "defense-in-depth" strategy for using the
ProofOfThought system in a large-scale, automated environment. It addresses
the challenge of ensuring that the LLM's logical decompositions are free
from bias and fallacies, which is impossible to do manually at scale.

The script defines an `AuditedProofOfThought` class that wraps the core
components of the `z3dsl` library. The workflow is as follows:

1.  **Programmer LLM**: A primary LLM is prompted with advanced instructions
    to act as a neutral logician and generate a Z3 DSL program from a question.
2.  **Auditor LLM**: A second LLM, with a different set of instructions,
    acts as a critical specialist. It reviews the generated program for
    bias, fallacies, and emotionally loaded terms.
3.  **Audit & Self-Correction**:
    - If the Auditor deems the program safe, it proceeds to verification.
    - If the Auditor flags the program as high-risk, its feedback is
      sent back to the Programmer LLM, which attempts to generate a corrected,
      more neutral program.
4.  **Verification**: Only after a program passes the audit is it sent to the
    Z3Verifier for a final, logically sound True/False answer.

This example requires the `openai` and `z3-solver` packages to be installed,
and an `OPENAI_API_KEY` to be set in your environment variables.
"""

import os
import json
import logging
import tempfile
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, ConfigDict

# Assume 'z3dsl' is installed and available in the Python path.
# In a real repository, these imports would work directly.
from z3dsl.reasoning import Z3ProgramGenerator, Z3Verifier, VerificationResult, GenerationResult

# For this example, we'll use the OpenAI client, but any client compatible
# with the library's LLM interface would work.
from openai import OpenAI

# --- Configuration ---
# Configure logging for clear output
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load OpenAI API key from environment variables
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set. Please set it to your API key.")

# We can use the same model for both roles or different ones.
# Using a powerful model for both is recommended for best results.
PROGRAMMER_MODEL = "gpt-5"
AUDITOR_MODEL = "gpt-5"


class AuditReport(BaseModel):
    """Structured response returned by the auditor model."""

    risk_score: int
    is_safe: bool
    justification: str

    model_config = ConfigDict(extra="forbid")


class AuditedProofOfThought:
    """
    An enhanced reasoning system that adds a layer of automated auditing
    and self-correction to the ProofOfThought process.
    """

    def __init__(self, llm_client: Any, risk_threshold: int = 5):
        """
        Initializes the audited reasoning system.

        Args:
            llm_client: An OpenAI-compatible client.
            risk_threshold: A score (1-10) above which a program is considered biased.
        """
        self.programmer_generator = Z3ProgramGenerator(llm_client=llm_client, model=PROGRAMMER_MODEL)
        self.auditor_llm = llm_client
        self.verifier = Z3Verifier()
        self.risk_threshold = risk_threshold
        logging.info("AuditedProofOfThought system initialized.")

    def _get_programmer_prompt(self, question: str) -> str:
        """Applies advanced prompt engineering for neutrality."""
        # This function would ideally import the `build_prompt` from the library
        # and prepend these instructions. For this standalone example, we create it here.
        from z3dsl.reasoning.prompt_template import DSL_INSTRUCTIONS

        neutrality_instructions = """
        **CRITICAL Directives for Neutrality and Accuracy**:
        1.  **Principle of Charity**: You are a neutral logician. Represent all concepts in their most objective, verifiable, and quantitative form.
        2.  **Avoid Subjectivity**: Do not use emotionally loaded or subjective terms (e.g., 'good', 'bad', 'chaotic'). Instead, model the world using measurable metrics (e.g., 'air_quality_score', 'cost_in_usd').
        3.  **Fallacy Check**: Before outputting the JSON, you must review your logic for common fallacies (ad hominem, straw man, false dichotomy, overgeneralization). Your primary goal is logical soundness, not persuasive rhetoric.
        ---
        """
        return neutrality_instructions + DSL_INSTRUCTIONS + f"\nQuestion: {question}"

    def _get_auditor_prompt(self, json_program_str: str, original_question: str) -> str:
        """Creates the prompt for the Auditor LLM."""
        return f"""
        You are a specialist in detecting logical fallacies, cognitive biases, and stereotypes in structured reasoning programs. Your sole purpose is to ensure neutrality.

        Analyze the following JSON program, which was generated to answer the question: "{original_question}"

        Program:
        ```json
        {json_program_str}
        ```

        Your Task:
        1.  Scrutinize the 'knowledge_base' for biased assumptions, overgeneralizations, or subjective opinions presented as objective facts.
        2.  Examine all names (functions, constants, variables) for emotionally loaded or non-neutral language.
        3.  Assess if the 'verifications' section neutrally and accurately represents the core of the original question.
        4.  Provide a JSON response with exactly three fields:
            - "risk_score": An integer from 1 (completely neutral) to 10 (highly biased or fallacious).
            - "is_safe": A boolean (true if risk_score is below {self.risk_threshold}, otherwise false).
            - "justification": A concise string explaining your reasoning, especially if the program is unsafe. This justification will be used as feedback.
        """

    def _audit_program(self, json_program: Dict, original_question: str) -> Tuple[bool, str]:
        """Uses the Auditor LLM to check the generated program for bias."""
        logging.info("Auditing generated program for bias and fallacies...")
        json_program_str = json.dumps(json_program, indent=2)
        auditor_prompt = self._get_auditor_prompt(json_program_str, original_question)

        responses_api = getattr(self.auditor_llm, "responses", None)
        parse_fn = getattr(responses_api, "parse", None) if responses_api else None

        if parse_fn is not None:
            try:
                structured_response = parse_fn(
                    model=AUDITOR_MODEL,
                    input=[
                        {
                            "role": "system",
                            "content": (
                                "You review DSL programs for bias. Respond using the provided schema."
                            ),
                        },
                        {"role": "user", "content": auditor_prompt},
                    ],
                    text_format=AuditReport,
                )
                audit_report: Optional[AuditReport] = getattr(
                    structured_response, "output_parsed", None
                )
                if audit_report is not None:
                    risk_score = audit_report.risk_score
                    is_safe = audit_report.is_safe and risk_score < self.risk_threshold
                    justification = audit_report.justification

                    logging.info(f"Audit Complete. Risk Score: {risk_score}. Safe: {is_safe}.")
                    if not is_safe:
                        logging.warning(f"Auditor's Justification: {justification}")

                    return is_safe, justification
            except Exception as exc:
                logging.warning(
                    "Structured audit request failed, falling back to legacy parsing: %s", exc
                )

        response = self.auditor_llm.chat.completions.create(
            model=AUDITOR_MODEL,
            messages=[{"role": "user", "content": auditor_prompt}],
            response_format={"type": "json_object"},
        )

        try:
            audit_result = json.loads(response.choices[0].message.content)
            risk_score = audit_result.get("risk_score", 10)
            is_safe = bool(risk_score < self.risk_threshold)
            justification = audit_result.get("justification", "No justification provided.")

            logging.info(f"Audit Complete. Risk Score: {risk_score}. Safe: {is_safe}.")
            if not is_safe:
                logging.warning(f"Auditor's Justification: {justification}")

            return is_safe, justification
        except (json.JSONDecodeError, KeyError) as e:
            logging.error(f"Audit failed: Could not parse auditor LLM response. Error: {e}")
            return False, "Auditor LLM response was malformed."

    def query(self, question: str) -> Optional[VerificationResult]:
        """Orchestrates the generate-audit-verify workflow with self-correction."""
        logging.info(f"--- Processing New Query: '{question}' ---")
        
        # --- Generation Attempt 1 ---
        logging.info("Step 1: Generating initial logical program...")
        programmer_prompt = self._get_programmer_prompt(question)
        gen_result: GenerationResult = self.programmer_generator.generate(question=question) # The library builds the prompt internally

        if not gen_result.success or not gen_result.json_program:
            logging.error("Initial program generation failed.")
            return None

        program = gen_result.json_program
        
        # --- Auditing Attempt 1 ---
        is_safe, justification = self._audit_program(program, question)

        if not is_safe:
            logging.warning("Step 2: Audit FAILED. Attempting self-correction with feedback...")
            
            # --- Self-Correction Attempt ---
            gen_result = self.programmer_generator.generate_with_feedback(
                question=question,
                error_trace=f"The initial program was rejected by a logical audit. Reason: {justification}. Please generate a new, more neutral program based on objective, verifiable metrics.",
                previous_response=gen_result.raw_response
            )

            if not gen_result.success or not gen_result.json_program:
                logging.error("Self-correction generation failed.")
                return None
            
            program = gen_result.json_program

            # --- Auditing Attempt 2 (on the corrected program) ---
            logging.info("Re-auditing the corrected program...")
            is_safe, justification = self._audit_program(program, question)
            
            if not is_safe:
                logging.error("Self-correction FAILED audit. Escalating for human review.")
                return None

        logging.info("Step 2: Audit PASSED. Program is safe.")
        
        # --- Final Verification Step ---
        logging.info("Step 3: Executing with Z3 Verifier...")
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json") as tmp_file:
            json.dump(program, tmp_file, indent=2)
            json_path = tmp_file.name
        
        try:
            verification_result = self.verifier.verify(json_path)
            logging.info(f"Step 4: Z3 Verification Complete. Final Answer: {verification_result.answer}")
            return verification_result
        finally:
            os.remove(json_path)


def main():
    """Main function to run the audited reasoning examples."""
    llm_client = OpenAI(api_key=api_key)
    
    audited_pot = AuditedProofOfThought(
        llm_client=llm_client,
        risk_threshold=6
    )
    
    print("\n" + "="*80)
    print("SCENARIO 1: A straightforward, objective question that should pass the audit.")
    print("="*80)
    objective_question = "Is a Boeing 737's cost covered by the box office receipts of the film 'Wonder Woman' (2017)?"
    audited_pot.query(objective_question)
    
    print("\n" + "="*80)
    print("SCENARIO 2: A subjective, high-risk question that should fail the first audit and self-correct.")
    print("="*80)
    subjective_question = "Is it better to live in the city or the country?"
    audited_pot.query(subjective_question)


if __name__ == "__main__":
    main()
