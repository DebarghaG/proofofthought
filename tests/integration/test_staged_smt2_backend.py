"""Integration tests for StagedSMT2Backend."""

import os
import tempfile

import pytest

from z3adapter.backends.smt2 import (
    ConversionContext,
    ExecutionResult,
    Pipeline,
    StagedSMT2Backend,
)


# Skip tests if Z3 is not installed
def z3_available():
    import shutil
    return shutil.which("z3") is not None


@pytest.mark.skipif(not z3_available(), reason="Z3 not installed")
class TestStagedSMT2BackendExecution:
    """Tests for StagedSMT2Backend execution."""

    @pytest.fixture
    def backend(self):
        return StagedSMT2Backend()

    def test_execute_simple_sat(self, backend):
        """Test executing a simple SAT program."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".smt2", delete=False) as f:
            f.write("""
(set-logic ALL)
(declare-const x Int)
(assert (> x 0))
(check-sat)
""")
            f.flush()
            result = backend.execute(f.name)
            os.unlink(f.name)

        assert result.success is True
        assert result.answer is True
        assert result.sat_count == 1

    def test_execute_simple_unsat(self, backend):
        """Test executing a simple UNSAT program."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".smt2", delete=False) as f:
            f.write("""
(set-logic ALL)
(declare-const x Int)
(assert (and (> x 10) (< x 5)))
(check-sat)
""")
            f.flush()
            result = backend.execute(f.name)
            os.unlink(f.name)

        assert result.success is True
        assert result.answer is False
        assert result.unsat_count == 1

    def test_execute_config_simple(self, backend):
        """Test execute_config with a simple configuration."""
        config = {
            "sorts": [],
            "functions": [],
            "constants": {},
            "knowledge_base": ["x > 0"],
            "verifications": [
                {"name": "check_positive", "constraint": "x > 0"}
            ]
        }

        verify_result, exec_result = backend.execute_config(config)

        assert verify_result.success is True
        # At least one check should be present
        assert verify_result.sat_count + verify_result.unsat_count > 0

    def test_execute_config_with_sorts(self, backend):
        """Test execute_config with custom sorts."""
        config = {
            "sorts": [{"name": "Person", "type": "DeclareSort"}],
            "functions": [
                {"name": "age", "domain": ["Person"], "range": "IntSort"}
            ],
            "constants": {
                "people": {"sort": "Person", "members": ["alice", "bob"]}
            },
            "knowledge_base": [
                "age(alice) == 30",
                "age(bob) == 25",
            ],
            "verifications": [
                {"name": "alice_older", "constraint": "age(alice) > age(bob)"}
            ]
        }

        verify_result, exec_result = backend.execute_config(config)

        assert verify_result.success is True
        assert len(exec_result.queries) >= 1

    def test_generate_smt2(self, backend):
        """Test generating SMT-LIB without execution."""
        config = {
            "sorts": [{"name": "Person", "type": "DeclareSort"}],
            "functions": [{"name": "age", "domain": ["Person"], "range": "IntSort"}],
        }

        smt2 = backend.generate_smt2(config)

        assert "(set-logic ALL)" in smt2
        assert "(declare-sort Person 0)" in smt2
        assert "(declare-fun age (Person) Int)" in smt2


@pytest.mark.skipif(not z3_available(), reason="Z3 not installed")
class TestFoundationReuse:
    """Tests for foundation building and reuse."""

    @pytest.fixture
    def backend(self):
        return StagedSMT2Backend()

    def test_build_foundation(self, backend):
        """Test building a foundation."""
        config = {
            "sorts": [{"name": "Person", "type": "DeclareSort"}],
            "functions": [{"name": "age", "domain": ["Person"], "range": "IntSort"}],
            "constants": {"people": {"sort": "Person", "members": ["alice"]}},
            "knowledge_base": ["age(alice) == 30"],
            "rules": [],
        }

        foundation = backend.build_foundation(config)

        assert "(declare-sort Person 0)" in foundation
        assert "(declare-fun age" in foundation
        assert "(declare-const alice Person)" in foundation

    def test_add_query_to_foundation(self, backend):
        """Test adding a query to an existing foundation."""
        config = {
            "sorts": [{"name": "Person", "type": "DeclareSort"}],
            "functions": [{"name": "age", "domain": ["Person"], "range": "IntSort"}],
            "knowledge_base": ["age(alice) == 30"],
        }

        foundation = backend.build_foundation(config)
        program = backend.add_query(
            {"name": "check_age", "constraint": "age(alice) > 20"},
            foundation
        )

        assert "(set-logic ALL)" in program
        assert "(check-sat)" in program
        assert "(assert (> (age alice) 20))" in program

    def test_multiple_queries_on_foundation(self, backend):
        """Test adding multiple queries to the same foundation."""
        config = {
            "sorts": [],
            "functions": [],
            "knowledge_base": [],
        }

        foundation = backend.build_foundation(config)

        query1 = backend.add_query(
            {"name": "q1", "constraint": "x > 0"},
            foundation
        )
        query2 = backend.add_query(
            {"name": "q2", "constraint": "y < 10"},
            foundation
        )

        assert "x > 0" in query1 or "(> x 0)" in query1
        assert "y < 10" in query2 or "(< y 10)" in query2


class TestConversionContext:
    """Tests for conversion context access."""

    @pytest.fixture
    def backend(self):
        return StagedSMT2Backend()

    def test_get_context_after_generate(self, backend):
        """Test getting context after generation."""
        config = {
            "sorts": [{"name": "Person", "type": "DeclareSort"}],
            "functions": [{"name": "age", "domain": ["Person"], "range": "IntSort"}],
        }

        backend.generate_smt2(config)
        ctx = backend.get_context()

        assert ctx is not None
        assert "Person" in ctx.sorts
        assert "age" in ctx.functions

    def test_get_context_summary(self, backend):
        """Test getting context summary."""
        config = {
            "sorts": [{"name": "Person", "type": "DeclareSort"}],
            "functions": [{"name": "age", "domain": ["Person"], "range": "IntSort"}],
            "constants": {"people": {"sort": "Person", "members": ["alice"]}},
        }

        backend.generate_smt2(config)
        summary = backend.get_context_summary()

        assert "; Logic: ALL" in summary
        assert "Person" in summary
        assert "age" in summary
        assert "alice" in summary


class TestPipelineIntegration:
    """Integration tests for the Pipeline class."""

    def test_full_pipeline_smt2_output(self):
        """Test that full pipeline produces valid SMT-LIB."""
        pipeline = Pipeline()
        config = {
            "logic": "ALL",
            "sorts": [
                {"name": "Person", "type": "DeclareSort"},
                {"name": "Color", "type": "EnumSort", "values": ["red", "green", "blue"]},
            ],
            "functions": [
                {"name": "age", "domain": ["Person"], "range": "IntSort"},
                {"name": "favorite_color", "domain": ["Person"], "range": "Color"},
            ],
            "constants": {
                "people": {"sort": "Person", "members": ["alice", "bob"]},
            },
            "variables": [
                {"name": "p", "sort": "Person"},
            ],
            "knowledge_base": [
                "age(alice) == 30",
                "age(bob) == 25",
            ],
            "rules": [
                {
                    "forall": [{"name": "p", "sort": "Person"}],
                    "implies": {
                        "antecedent": "age(p) > 18",
                        "consequent": "is_adult(p)",
                    }
                }
            ],
            "verifications": [
                {"name": "alice_older", "constraint": "age(alice) > age(bob)"},
            ]
        }

        smt2 = pipeline.run(config)

        # Verify structure
        assert "(set-logic ALL)" in smt2
        assert "(declare-sort Person 0)" in smt2
        assert "declare-datatypes" in smt2  # For enum
        assert "(declare-fun age (Person) Int)" in smt2
        assert "(declare-const alice Person)" in smt2
        assert "(assert (= (age alice) 30))" in smt2
        assert "(forall" in smt2
        assert "(push 1)" in smt2
        assert "(check-sat)" in smt2
        assert "(pop 1)" in smt2


class TestBackendInitialization:
    """Tests for backend initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        if not z3_available():
            pytest.skip("Z3 not installed")
        backend = StagedSMT2Backend()
        assert backend.verify_timeout == 10000
        assert backend.z3_path == "z3"

    def test_init_with_custom_timeout(self):
        """Test initialization with custom timeout."""
        if not z3_available():
            pytest.skip("Z3 not installed")
        backend = StagedSMT2Backend(verify_timeout=5000)
        assert backend.verify_timeout == 5000

    def test_init_with_invalid_z3_path(self):
        """Test initialization with invalid Z3 path raises error."""
        with pytest.raises(FileNotFoundError):
            StagedSMT2Backend(z3_path="/nonexistent/path/to/z3")

    def test_get_file_extension(self):
        """Test file extension method."""
        if not z3_available():
            pytest.skip("Z3 not installed")
        backend = StagedSMT2Backend()
        assert backend.get_file_extension() == ".smt2"


@pytest.mark.skipif(not z3_available(), reason="Z3 not installed")
class TestErrorHandling:
    """Tests for error handling."""

    @pytest.fixture
    def backend(self):
        return StagedSMT2Backend()

    def test_execute_nonexistent_file(self, backend):
        """Test executing a nonexistent file."""
        result = backend.execute("/nonexistent/file.smt2")
        assert result.success is False
        assert result.error is not None

    def test_add_query_without_foundation(self, backend):
        """Test adding query without building foundation first."""
        with pytest.raises(ValueError, match="No foundation built"):
            backend.add_query({"name": "q", "constraint": "x > 0"})
