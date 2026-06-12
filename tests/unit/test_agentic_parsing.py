"""Unit tests for tool-call recovery from raw assistant content."""

import json
import unittest

from z3adapter.agentic.parsing import extract_answer_from_text, parse_tool_calls_from_content


class TestToolCallParsing(unittest.TestCase):
    """Test recovery of textual tool calls the server parser missed."""

    def test_clean_hermes_json(self) -> None:
        content = (
            '<tool_call>\n{"name": "z3_solve", "arguments": '
            '{"smt_code": "(check-sat)"}}\n</tool_call>'
        )
        calls = parse_tool_calls_from_content(content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "z3_solve")
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertEqual(args["smt_code"], "(check-sat)")

    def test_finish_call(self) -> None:
        content = (
            '<tool_call>{"name": "finish", "arguments": '
            '{"answer": "Yes", "explanation": "UNSAT proved it."}}</tool_call>'
        )
        calls = parse_tool_calls_from_content(content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "finish")
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertEqual(args["answer"], "Yes")

    def test_qwen_xml_format(self) -> None:
        content = (
            "<tool_call>\n<function=z3_solve>\n"
            "<parameter=smt_code>(declare-const x Int)\n(check-sat)</parameter>\n"
            "</function>\n</tool_call>"
        )
        calls = parse_tool_calls_from_content(content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "z3_solve")
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertIn("(check-sat)", args["smt_code"])

    def test_bare_smt_synthesized(self) -> None:
        content = "Here's the SMT code:\n" "(declare-const x Int)\n(assert (> x 5))\n(check-sat)"
        calls = parse_tool_calls_from_content(content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "z3_solve")
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertTrue(args["smt_code"].startswith("(declare-const"))

    def test_plain_english_not_swallowed(self) -> None:
        content = "I will write a (declare ...) statement soon."
        self.assertEqual(parse_tool_calls_from_content(content), [])

    def test_empty_content(self) -> None:
        self.assertEqual(parse_tool_calls_from_content(""), [])
        self.assertEqual(parse_tool_calls_from_content(None), [])

    def test_truncated_call_missing_closer(self) -> None:
        content = (
            '<tool_call>\n{"name": "finish", "arguments": {"answer": "No", '
            '"explanation": "contradiction'
        )
        calls = parse_tool_calls_from_content(content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "finish")
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertEqual(args["answer"], "No")

    def test_orphan_closer_recovered_as_smt(self) -> None:
        # Server consumed the opener+JSON wrapper, leaving SMT + closer.
        content = '(declare-const x Int)\n(assert (> x 1))\n(check-sat)"}}\n</tool_call>'
        calls = parse_tool_calls_from_content(content)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "z3_solve")

    def test_multiple_calls(self) -> None:
        content = (
            '<tool_call>{"name": "z3_solve", "arguments": {"smt_code": "(check-sat)"}}'
            "</tool_call>\n"
            '<tool_call>{"name": "finish", "arguments": {"answer": "True"}}</tool_call>'
        )
        calls = parse_tool_calls_from_content(content)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["function"]["name"], "z3_solve")
        self.assertEqual(calls[1]["function"]["name"], "finish")


class TestAnswerExtraction(unittest.TestCase):
    """Test lenient answer extraction from natural-language output."""

    def test_boxed(self) -> None:
        self.assertEqual(extract_answer_from_text(r"Thus \boxed{Yes}"), "Yes")

    def test_answer_phrase(self) -> None:
        self.assertEqual(extract_answer_from_text("So the answer is False."), "False")

    def test_answer_phrase_strips_wrapper_punctuation(self) -> None:
        # Regression: '(A).' used to come back as 'A)'.
        self.assertEqual(extract_answer_from_text("The answer is (A)."), "A")
        self.assertEqual(extract_answer_from_text("Thus the answer is B:"), "B")
        self.assertEqual(extract_answer_from_text("final answer: **Yes**"), "Yes")

    def test_terminal_letter(self) -> None:
        self.assertEqual(extract_answer_from_text("blah blah\n(B)"), "B")

    def test_terminal_word(self) -> None:
        self.assertEqual(extract_answer_from_text("reasoning...\n**True**"), "True")

    def test_no_answer(self) -> None:
        self.assertIsNone(extract_answer_from_text("I am still thinking about this."))
        self.assertIsNone(extract_answer_from_text(""))


if __name__ == "__main__":
    unittest.main()
