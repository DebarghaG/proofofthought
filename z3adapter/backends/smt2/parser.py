"""Parser for Z3 output with multi-query support."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ModelValue:
    """A value from a Z3 model."""

    name: str
    sort: str
    value: str


@dataclass
class SMTQueryResult:
    """Result of a single query."""

    query_id: str
    query_name: str
    status: str  # "sat", "unsat", "unknown", "timeout"
    model: list[ModelValue] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)
    raw_output: str = ""


@dataclass
class ExecutionResult:
    """Result of executing an SMT-LIB program with multiple queries."""

    success: bool
    queries: list[SMTQueryResult] = field(default_factory=list)
    sat_count: int = 0
    unsat_count: int = 0
    unknown_count: int = 0
    error: str | None = None
    raw_output: str = ""

    @property
    def answer(self) -> bool | None:
        """
        Determine boolean answer from results.

        Returns:
            True if all queries SAT and no UNSAT
            False if any query UNSAT and no SAT
            None if mixed or unknown
        """
        if self.sat_count > 0 and self.unsat_count == 0:
            return True
        elif self.unsat_count > 0 and self.sat_count == 0:
            return False
        return None


class Z3OutputParser:
    """Parser for Z3 output with support for multiple queries."""

    # Patterns for parsing
    SAT_PATTERN = re.compile(r"(?<!un)\bsat\b", re.IGNORECASE)
    UNSAT_PATTERN = re.compile(r"\bunsat\b", re.IGNORECASE)
    UNKNOWN_PATTERN = re.compile(r"\bunknown\b", re.IGNORECASE)
    TIMEOUT_PATTERN = re.compile(r"\btimeout\b", re.IGNORECASE)

    # Model parsing patterns
    MODEL_START = re.compile(r"\(model")
    DEFINE_FUN_PATTERN = re.compile(
        r"\(define-fun\s+(\S+)\s+\(\)\s+(\S+)\s+(.+?)\s*\)", re.DOTALL
    )

    def parse(
        self, output: str, query_names: list[str] | None = None
    ) -> ExecutionResult:
        """
        Parse Z3 output into structured results.

        Args:
            output: Raw Z3 output string
            query_names: Optional list of query names (in order)

        Returns:
            ExecutionResult with parsed query results
        """
        # Split by push/pop blocks if present
        # Each block represents a separate query
        blocks = self._split_by_blocks(output)

        query_results = []
        sat_count = 0
        unsat_count = 0
        unknown_count = 0

        for i, block in enumerate(blocks):
            query_id = f"query_{i}"
            query_name = (
                query_names[i] if query_names and i < len(query_names) else query_id
            )

            # Determine status
            if self.TIMEOUT_PATTERN.search(block):
                status = "timeout"
                unknown_count += 1
            elif self.UNSAT_PATTERN.search(block):
                status = "unsat"
                unsat_count += 1
            elif self.SAT_PATTERN.search(block):
                status = "sat"
                sat_count += 1
            elif self.UNKNOWN_PATTERN.search(block):
                status = "unknown"
                unknown_count += 1
            else:
                # No status found - likely empty or error
                continue

            # Parse model if SAT
            model = []
            if status == "sat":
                model = self._parse_model(block)

            query_results.append(
                SMTQueryResult(
                    query_id=query_id,
                    query_name=query_name,
                    status=status,
                    model=model,
                    raw_output=block,
                )
            )

        return ExecutionResult(
            success=len(query_results) > 0,
            queries=query_results,
            sat_count=sat_count,
            unsat_count=unsat_count,
            unknown_count=unknown_count,
            error="No query results parsed from Z3 output" if not query_results else None,
            raw_output=output,
        )

    def _split_by_blocks(self, output: str) -> list[str]:
        """
        Split output by query blocks.

        Z3 outputs results for each query (push/check-sat/pop block).
        We split by detecting sat/unsat lines while tracking model boundaries
        to avoid false matches inside model output.
        """
        lines = output.strip().split("\n")
        if not lines or not output.strip():
            return []

        blocks = []
        current_block: list[str] = []
        in_model = False
        paren_depth = 0
        has_status = False

        for line in lines:
            stripped = line.strip()
            current_block.append(line)

            # Track if we're inside a model
            if not in_model and "(model" in stripped:
                in_model = True
                paren_depth = 0
                for char in stripped:
                    if char == "(":
                        paren_depth += 1
                    elif char == ")":
                        paren_depth -= 1
                continue

            if in_model:
                for char in stripped:
                    if char == "(":
                        paren_depth += 1
                    elif char == ")":
                        paren_depth -= 1
                        if paren_depth <= 0:
                            in_model = False
                            break
                continue

            # Outside model: check if this is a status line
            if stripped in ("sat", "unsat", "unknown", "timeout"):
                has_status = True
            # Check if we've seen a status and model is done — next status starts a new block
            elif has_status and current_block and stripped in ("sat", "unsat", "unknown", "timeout"):
                pass  # Will be handled by next iteration

        # If we couldn't split meaningfully, fall back to status-line splitting
        if not has_status:
            return [output] if output.strip() else []

        # Use line-based splitting: each status line (outside model) starts a new block
        blocks = []
        current_block = []
        in_model = False
        paren_depth = 0

        for line in lines:
            stripped = line.strip()

            if not in_model and "(model" in stripped:
                in_model = True
                paren_depth = 0
                for char in stripped:
                    if char == "(":
                        paren_depth += 1
                    elif char == ")":
                        paren_depth -= 1
                current_block.append(line)
                continue

            if in_model:
                current_block.append(line)
                for char in stripped:
                    if char == "(":
                        paren_depth += 1
                    elif char == ")":
                        paren_depth -= 1
                        if paren_depth <= 0:
                            in_model = False
                            break
                continue

            # Status line outside model: this belongs to current block, then finalize
            if stripped in ("sat", "unsat", "unknown", "timeout"):
                # If we already have a block with a status, start a new one
                if current_block and any(
                    l.strip() in ("sat", "unsat", "unknown", "timeout")
                    for l in current_block
                ):
                    blocks.append("\n".join(current_block))
                    current_block = [line]
                else:
                    current_block.append(line)
            else:
                current_block.append(line)

        if current_block:
            blocks.append("\n".join(current_block))

        return blocks if blocks else [output] if output.strip() else []

    def _parse_model(self, block: str) -> list[ModelValue]:
        """Parse model definitions from a block."""
        model = []

        # Find model section
        model_match = self.MODEL_START.search(block)
        if not model_match:
            return model

        # Extract model content
        start = model_match.start()
        paren_depth = 0
        end = start

        for i, char in enumerate(block[start:], start):
            if char == "(":
                paren_depth += 1
            elif char == ")":
                paren_depth -= 1
                if paren_depth == 0:
                    end = i + 1
                    break

        model_text = block[start:end]

        # Parse define-fun declarations
        for match in self.DEFINE_FUN_PATTERN.finditer(model_text):
            name = match.group(1)
            sort = match.group(2)
            value = match.group(3).strip()
            model.append(ModelValue(name=name, sort=sort, value=value))

        return model

    def parse_simple(self, output: str) -> tuple[int, int]:
        """
        Simple parsing for backward compatibility.

        Returns:
            Tuple of (sat_count, unsat_count)
        """
        sat_matches = self.SAT_PATTERN.findall(output)
        unsat_matches = self.UNSAT_PATTERN.findall(output)
        return len(sat_matches), len(unsat_matches)
