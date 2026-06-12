"""Robust tool-call recovery from raw assistant content.

Models served behind OpenAI-compatible endpoints (vLLM, sglang, llama.cpp,
...) frequently emit *textual* tool calls that the server's parser fails to
extract: hermes JSON inside ``<tool_call>`` tags, qwen3_coder XML
(``<function=name>``), broken hybrids of the two, or even raw SMT-LIB with
no wrapper at all. When that happens the API response carries no structured
``tool_calls`` and a naive agent loop stalls.

This module recovers those calls from the content (or reasoning) channel.
It was battle-tested in the NL2SMTLIB-Benchmark evaluation harness across
tens of thousands of agent trajectories. With well-behaved API models
(OpenAI, Anthropic, Azure) it is a no-op fallback that never fires.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

_TOOL_CALL_BLOCK_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
# qwen3_coder XML: <function=name> ... </function> with <parameter=k>v</parameter>
_QWEN_FN_RE = re.compile(r"<function=([\w_]+)\s*>(.*?)</function>", re.DOTALL)
_QWEN_PARAM_RE = re.compile(r"<parameter=([\w_]+)\s*>\s*(.*?)\s*</parameter>", re.DOTALL)
# Hybrid the model commonly emits: <function=NAME"[, ]"arguments": {...}}
_HYBRID_RE = re.compile(
    r'<function=(\w+)\s*["\s,]+\s*"?arguments"?\s*:\s*(\{.*?)(?:\}\s*\}?\s*$|$)',
    re.DOTALL,
)
# Bare "<function=name>" extractor for truncated input where neither the
# JSON-args nor the closing </function> ever arrived.
_BARE_FN_RE = re.compile(r"<function=(\w+)", re.IGNORECASE)
# Loose key/value scrape that survives truncated JSON.
_ANSWER_RE = re.compile(r'"answer"\s*:\s*"([^"]*)"', re.DOTALL)
_EXPLANATION_RE = re.compile(r'"explanation"\s*:\s*"([^"]*?)"(?:\s*[,}]|$)', re.DOTALL)
_SMT_RE = re.compile(r'"smt_code"\s*:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL)

_SMT_PRIMITIVE_RE = re.compile(
    r"\(\s*(?:declare-(?:const|fun|sort|datatypes)|assert|check-sat|set-logic|get-model)",
    re.IGNORECASE,
)


def _synth_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Build a tool_call dict shaped like the OpenAI API's tool_calls field."""
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def parse_tool_calls_from_content(content: str) -> list[dict[str, Any]]:
    """Extract tool_calls from raw assistant content.

    Handles three syntaxes inside <tool_call>...</tool_call> blocks:
      1. Hermes JSON:  {"name": "fn", "arguments": {...}}
      2. qwen3_coder:  <function=fn><parameter=k>v</parameter></function>
      3. Hybrid:       <function=fn", "arguments": {...}}   (broken but recoverable)

    Returns a list shaped like the OpenAI tool_calls field (id/type/function),
    or [] if nothing parsed. Tolerant of truncation - if we can extract a
    name and an "answer" field for finish, we return a partial call.
    """
    if not content:
        return []
    # No <tool_call> markers at all but the content is clearly an SMT-LIB
    # script - some fine-tuned models emit raw SMT directly instead of
    # wrapping it. Synthesize a z3_solve call. We require multiple
    # distinctive primitives so we don't accidentally swallow plain English
    # mentioning "(declare ...)".
    if "<tool_call>" not in content and "</tool_call>" not in content:
        if _looks_like_bare_smt(content):
            stripped = _strip_bare_smt_envelope(content)
            return [_synth_call("z3_solve", {"smt_code": stripped})]
        return []
    out: list[dict[str, Any]] = []
    bodies = [m.group(1) for m in _TOOL_CALL_BLOCK_RE.finditer(content)]
    # If the closing tag is missing (model truncated mid-call), still try
    # to parse what came after the last opener.
    if not bodies and "<tool_call>" in content:
        idx = content.rfind("<tool_call>")
        if idx >= 0:
            bodies = [content[idx + len("<tool_call>") :]]
    # Server-side tool-call parsers sometimes consume the opening
    # <tool_call>{...JSON wrapper but lose track of the JSON value (often due
    # to escaped newlines inside an SMT string) and emit the remainder +
    # closing </tool_call>. In that case, the remaining content has a closer
    # but no opener. Best we can do is treat the whole prefix as the smt_code
    # value of a z3_solve call (the most common tool emitting long strings).
    elif not bodies and "</tool_call>" in content and "<tool_call>" not in content:
        body = content.split("</tool_call>", 1)[0]
        body = body.rstrip()
        for closer in ('"}}', "'}}", "}}", '"'):
            if body.endswith(closer):
                body = body[: -len(closer)]
                break
        body = body.rstrip()
        if body:
            return [_synth_call("z3_solve", {"smt_code": body})]
    for body in bodies:
        parsed = _try_parse_one(body.strip())
        if parsed is None:
            # Last-resort: the inner JSON wrapper was malformed. If the body
            # contains recognizable SMT-LIB code, synthesize a z3_solve call
            # from the SMT we can see.
            if _looks_like_bare_smt(body):
                stripped = _extract_smt_from_body(body)
                if stripped:
                    out.append(_synth_call("z3_solve", {"smt_code": stripped}))
            continue
        name, args = parsed
        out.append(
            {
                "id": f"call_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args) if isinstance(args, dict) else str(args),
                },
            }
        )
    return out


def _extract_smt_from_body(body: str) -> str:
    """Pull out the SMT-LIB code from a malformed tool_call body.

    Strategy: find the first ``(`` and take the substring through the last
    ``(check-sat)`` if present, unescaping JSON string escapes.
    """
    start = body.find("(")
    if start < 0:
        return ""
    candidate = body[start:]
    cs = candidate.rfind("(check-sat)")
    if cs >= 0:
        candidate = candidate[: cs + len("(check-sat)")]
    candidate = candidate.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
    return candidate.strip()


def _looks_like_bare_smt(text: str) -> bool:
    """Heuristic: does this text look like raw SMT-LIB code?

    Requires >=2 distinct SMT primitives AND a (check-sat) call.
    """
    if "(check-sat" not in text:
        return False
    matches = _SMT_PRIMITIVE_RE.findall(text)
    return len(set(matches)) >= 2


def _strip_bare_smt_envelope(text: str) -> str:
    """When the model emits SMT-LIB directly, sometimes there's a
    natural-language preamble like "Here's the SMT code:" before the first
    ``(``. Drop everything before the first SMT-looking line."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("(") or s.startswith(";"):
            return "\n".join(lines[i:]).strip()
    return text.strip()


def _try_parse_one(body: str) -> tuple[str, dict[str, Any]] | None:
    """Return (name, args_dict) from a single <tool_call> body, or None.

    Order of attempts:
      1. Clean hermes JSON (``{"name": ..., "arguments": {...}}``)
      2. Clean qwen3_coder XML (``<function=name>...</function>`` with parameters)
      3. Hybrid (qwen opener + JSON args)
      4. Last-resort: scrape answer/smt_code from any partial JSON
    """
    body = body.strip()
    if body.startswith("```"):
        body = re.sub(r"^```\w*\s*", "", body)
        body = re.sub(r"\s*```$", "", body)

    # 1. Clean hermes JSON.
    if body.startswith("{"):
        try:
            obj = json.loads(body)
            if isinstance(obj, dict) and "name" in obj:
                args = obj.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        pass
                return obj["name"], (args if isinstance(args, dict) else {})
        except json.JSONDecodeError:
            pass

    # 2. Clean qwen3_coder XML.
    fn = _QWEN_FN_RE.search(body)
    if fn:
        name = fn.group(1)
        args = {k: v for k, v in _QWEN_PARAM_RE.findall(fn.group(2))}
        if args:
            return name, args

    # 3. Hybrid: <function=name"[, ]"arguments": {...}
    hyb = _HYBRID_RE.search(body)
    if hyb:
        name = hyb.group(1)
        args_str = hyb.group(2)
        # Trim possible trailing braces that come from the broken closer
        # and try increasingly aggressive truncations.
        for cut in range(len(args_str), max(0, len(args_str) - 4), -1):
            try:
                obj = json.loads(args_str[:cut])
                if isinstance(obj, dict):
                    return name, obj
            except json.JSONDecodeError:
                continue
        scraped = _scrape_args(args_str)
        if scraped:
            return name, scraped

    # 4. Last resort: name from <function=...>, args from any partial JSON
    # we can scrape. Catches truncated calls and any other malformed shapes.
    bare = _BARE_FN_RE.search(body)
    if bare:
        scraped = _scrape_args(body)
        if scraped:
            return bare.group(1), scraped

    # 5. Truncated hermes: starts with `{` but never closes. Scrape it.
    if body.lstrip().startswith("{"):
        m_name = re.search(r'"name"\s*:\s*"([^"]+)"', body)
        if m_name:
            scraped = _scrape_args(body)
            if scraped:
                return m_name.group(1), scraped

    return None


def _scrape_args(text: str) -> dict[str, Any]:
    """Extract any answer/explanation/smt_code fields we can find. Used
    when the JSON containing the tool arguments was truncated."""
    found: dict[str, Any] = {}
    m = _ANSWER_RE.search(text)
    if m:
        found["answer"] = m.group(1)
    m = _EXPLANATION_RE.search(text)
    if m:
        found["explanation"] = m.group(1)
    m = _SMT_RE.search(text)
    if m:
        s = m.group(1).encode("utf-8").decode("unicode_escape", errors="ignore")
        found["smt_code"] = s
    return found


# ---------------------------------------------------------------------------
# Answer-pattern extraction (lenient mode only)
# ---------------------------------------------------------------------------

_ANSWER_PHRASE_RE = re.compile(
    r"(?:final\s+answer|the\s+answer\s+is|so\s+the\s+answer\s+is|"
    r"thus\s+the\s+answer\s+is|therefore\s+the\s+answer\s+is)\s*[:\.\-]?\s*"
    r"\*?\*?[\(\[]?([A-Za-z][A-Za-z\s\)\]\.\:]*?)\*?\*?\s*[\.\!]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_BOXED_RE = re.compile(r"\\boxed\{\s*([A-Za-z]+)\s*\}", re.IGNORECASE)
_TERMINAL_LETTER_RE = re.compile(r"^\s*[\(\[]?([A-D])[\)\]\.\:]?\s*$", re.IGNORECASE | re.MULTILINE)
_TERMINAL_WORD_RE = re.compile(
    r"^\s*\*?\*?(yes|no|true|false|unknown|uncertain|verified|violated)" r"\*?\*?\s*[\.\!]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def extract_answer_from_text(text: str) -> str | None:
    """Try to recover an answer from natural-language model output.

    Used in lenient mode when the loop exits without a clean finish().
    Returns None if no clear answer pattern is found.
    """
    if not text:
        return None
    # Look at the last 800 chars (the model's conclusion). Earlier text
    # often contains the question's "True or False" mentions which would
    # cause false positives.
    tail = text[-800:]

    # 1. Boxed answer: \boxed{X}
    m = _BOXED_RE.search(tail)
    if m:
        return m.group(1).strip()

    # 2. Phrase: "the answer is X" / "final answer: X"
    m = _ANSWER_PHRASE_RE.search(tail)
    if m:
        return m.group(1).strip().rstrip(".")

    # 3. Terminal single-letter line (very last line is just "A" / "B" / "(C)")
    last_lines = [line for line in tail.splitlines() if line.strip()]
    for line in reversed(last_lines[-3:]):
        letter = _TERMINAL_LETTER_RE.match(line)
        if letter:
            return letter.group(1).strip()
        word = _TERMINAL_WORD_RE.match(line)
        if word:
            return word.group(1).strip()
    return None
