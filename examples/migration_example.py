#!/usr/bin/env python3
"""
Migration Example: From benchmark_pipeline.py to ProofOfThought API

This example shows how to migrate from the original benchmark_pipeline.py
implementation to the new DSPy-style ProofOfThought API.
"""

import logging
import os

from openai import OpenAI

from z3adapter.reasoning import EvaluationPipeline, ProofOfThought

# Configure logging (same as original)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# =============================================================================
# OLD WAY (benchmark_pipeline.py) - 800+ lines
# =============================================================================
"""
client = OpenAI(api_key="...")
with open('strategyqa_train.json', 'r') as f:
    data = json.load(f)

max_questions = 10
correct_answers = 0
wrong_answers = 0

for idx, question_data in enumerate(data[:max_questions]):
    qid = question_data['qid']
    question_text = question_data['question']
    actual_answer = question_data['answer']

    # 700-line prompt
    initial_prompt_content = '''
    ** Instructions for Generating JSON-Based DSL Programs for Theorem Proving**
    ... (700 more lines)
    '''

    num_attempts = 0
    max_attempts = 3
    success = False

    while num_attempts < max_attempts and not success:
        # Manual LLM call
        response = client.chat.completions.create(...)

        # Manual JSON extraction
        extracted_json = extract_json_from_markdown(response.content)

        # Manual Z3 execution
        interpreter = Z3JSONInterpreter(output_json_path)
        interpreter.run()

        # Manual result parsing
        sat_occurrences = full_output.count(': SAT')
        unsat_occurrences = full_output.count(': UNSAT')
        # ... more manual logic

    if predicted_answer == actual_answer:
        correct_answers += 1

# Manual metrics calculation
accuracy = correct_answers / (correct_answers + wrong_answers)
"""

# =============================================================================
# NEW WAY (ProofOfThought) - 5 lines
# =============================================================================

# Initialize client (same as before)
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError(
        "OPENAI_API_KEY is not set. " "Please set it in your .env file or environment variables."
    )

client = OpenAI(api_key=api_key)

# Create ProofOfThought with same settings as original
pot = ProofOfThought(
    llm_client=client,
    model="gpt-4o",
    max_attempts=3,  # Same as original max_attempts
    verify_timeout=10000,
    cache_dir="strategyqa_outputs/programs",
)

# Create evaluation pipeline
evaluator = EvaluationPipeline(
    proof_of_thought=pot, output_dir="strategyqa_outputs/evaluation_results"
)

# Run evaluation (replaces entire 800-line loop)
result = evaluator.evaluate(
    dataset="strategyqa_train.json",
    question_field="question",
    answer_field="answer",
    id_field="qid",
    max_samples=10,  # Same as original max_questions
    skip_existing=True,
)

# Results are automatically computed
print("\n" + "=" * 80)
print("MIGRATION COMPLETE - RESULTS COMPARISON")
print("=" * 80)
print(f"Total Samples: {result.metrics.total_samples}")
print(f"Correct: {result.metrics.correct_answers}")
print(f"Wrong: {result.metrics.wrong_answers}")
print(f"Failed: {result.metrics.failed_answers}")
print(f"Accuracy: {result.metrics.accuracy:.2%}")
print()
print("Additional metrics not in original:")
print(f"  Precision: {result.metrics.precision:.4f}")
print(f"  Recall: {result.metrics.recall:.4f}")
print(f"  F1 Score: {result.metrics.f1_score:.4f}")
print(f"  Specificity: {result.metrics.specificity:.4f}")
print()
print("Confusion Matrix:")
print(f"  TP: {result.metrics.tp}, FP: {result.metrics.fp}")
print(f"  TN: {result.metrics.tn}, FN: {result.metrics.fn}")

# =============================================================================
# BENEFITS OF MIGRATION
# =============================================================================

print("\n" + "=" * 80)
print("BENEFITS OF NEW API")
print("=" * 80)
print("✓ 800+ lines → 5 lines of code")
print("✓ No manual prompt management")
print("✓ No manual JSON extraction")
print("✓ No manual Z3 execution")
print("✓ No manual result parsing")
print("✓ No manual retry logic")
print("✓ No manual metrics calculation")
print("✓ Automatic caching and resume")
print("✓ Better error handling")
print("✓ More comprehensive metrics")
print("✓ Cleaner, maintainable code")

# =============================================================================
# ACCESSING DETAILED RESULTS (if needed)
# =============================================================================

print("\n" + "=" * 80)
print("DETAILED RESULTS ACCESS")
print("=" * 80)

# You can still access individual results if needed
for i, query_result in enumerate(result.results[:3]):
    print(f"\n[Sample {i+1}]")
    print(f"  Question: {query_result.question[:60]}...")
    print(f"  Answer: {query_result.answer}")
    print(f"  Success: {query_result.success}")
    print(f"  Attempts: {query_result.num_attempts}")

    # Access generated program if needed
    if query_result.json_program:
        print("  Program structure:")
        print(f"    - Sorts: {len(query_result.json_program.get('sorts', []))}")
        print(f"    - Functions: {len(query_result.json_program.get('functions', []))}")
        print(f"    - KB assertions: {len(query_result.json_program.get('knowledge_base', []))}")

# Ground truth and predictions are also available
print(f"\nGround truth labels: {result.y_true[:10]}")
print(f"Predicted labels: {result.y_pred[:10]}")
