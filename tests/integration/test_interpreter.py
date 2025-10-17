"""Integration tests for Z3JSONInterpreter."""

import json
import os
import tempfile
import unittest

from z3adapter.interpreter import Z3JSONInterpreter


class TestZ3JSONInterpreter(unittest.TestCase):
    """Integration tests for the full interpreter."""

    def test_load_and_run_simple_config(self) -> None:
        """Test loading and running a simple configuration."""
        interpreter = Z3JSONInterpreter("tests/fixtures/simple_test.json")
        # Should not raise
        interpreter.run()

    def test_load_and_run_bitvec_config(self) -> None:
        """Test running configuration with bitvector sorts."""
        interpreter = Z3JSONInterpreter("tests/fixtures/bitvec_test.json")
        # Should not raise
        interpreter.run()

    def test_load_and_run_enum_config(self) -> None:
        """Test running configuration with enum sorts."""
        interpreter = Z3JSONInterpreter("tests/fixtures/enum_test.json")
        # Should not raise
        interpreter.run()

    def test_load_and_run_existing_test(self) -> None:
        """Test running the existing test file."""
        interpreter = Z3JSONInterpreter("tests/3.json")
        # Should not raise
        interpreter.run()

    def test_load_nonexistent_file(self) -> None:
        """Test that loading nonexistent file raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            Z3JSONInterpreter("nonexistent.json")

    def test_load_invalid_json(self) -> None:
        """Test that loading invalid JSON raises JSONDecodeError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json")
            temp_file = f.name

        try:
            with self.assertRaises(json.JSONDecodeError):
                Z3JSONInterpreter(temp_file)
        finally:
            os.unlink(temp_file)

    def test_custom_timeouts(self) -> None:
        """Test that custom timeouts are respected."""
        interpreter = Z3JSONInterpreter(
            "tests/fixtures/simple_test.json", verify_timeout=5000, optimize_timeout=20000
        )
        self.assertEqual(interpreter.verify_timeout, 5000)
        self.assertEqual(interpreter.optimize_timeout, 20000)
        interpreter.run()

    def test_missing_sections_get_defaults(self) -> None:
        """Test that missing sections get appropriate defaults."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({}, f)
            temp_file = f.name

        try:
            interpreter = Z3JSONInterpreter(temp_file)
            self.assertIn("sorts", interpreter.config)
            self.assertIn("functions", interpreter.config)
            self.assertEqual(interpreter.config["sorts"], [])
            # Should not crash on run with empty config
            interpreter.run()
        finally:
            os.unlink(temp_file)

    def test_invalid_constants_section_structure(self) -> None:
        """Test that invalid constants structure is corrected."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"constants": ["not", "a", "dict"]}, f)
            temp_file = f.name

        try:
            with self.assertLogs(level="WARNING") as cm:
                interpreter = Z3JSONInterpreter(temp_file)
            self.assertTrue(any("dictionary" in msg for msg in cm.output))
            self.assertEqual(interpreter.config["constants"], {})
        finally:
            os.unlink(temp_file)

    def test_unknown_action_logs_warning(self) -> None:
        """Test that unknown action logs warning."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"actions": ["unknown_action"]}, f)
            temp_file = f.name

        try:
            interpreter = Z3JSONInterpreter(temp_file)
            with self.assertLogs(level="WARNING") as cm:
                interpreter.run()
            self.assertTrue(any("Unknown action" in msg for msg in cm.output))
        finally:
            os.unlink(temp_file)

    def test_verify_conditions_action(self) -> None:
        """Test that verify_conditions action works."""
        config = {
            "constants": {"nums": {"sort": "IntSort", "members": ["x"]}},
            "knowledge_base": ["x > 0"],
            "verifications": [{"name": "positive", "constraint": "x > 0"}],
            "actions": ["verify_conditions"],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            temp_file = f.name

        try:
            interpreter = Z3JSONInterpreter(temp_file)
            with self.assertLogs(level="INFO") as cm:
                interpreter.run()
            output = " ".join(cm.output)
            self.assertIn("SAT", output)
        finally:
            os.unlink(temp_file)

    def test_optimization_action(self) -> None:
        """Test that optimization action works."""
        config = {
            "optimization": {
                "variables": [{"name": "y", "sort": "IntSort"}],
                "constraints": ["y >= 0", "y <= 10"],
                "objectives": [{"expression": "y", "type": "maximize"}],
            },
            "actions": ["optimize"],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            temp_file = f.name

        try:
            interpreter = Z3JSONInterpreter(temp_file)
            # Should not raise
            interpreter.run()
        finally:
            os.unlink(temp_file)

    def test_topological_sort_of_sorts(self) -> None:
        """Test that sorts are topologically sorted."""
        config = {
            "sorts": [
                {"name": "Array1", "type": "ArraySort(Sort1, IntSort)"},
                {"name": "Sort1", "type": "DeclareSort"},
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            temp_file = f.name

        try:
            interpreter = Z3JSONInterpreter(temp_file)
            # Should not raise even though Array1 comes before Sort1
            interpreter.run()
        finally:
            os.unlink(temp_file)


if __name__ == "__main__":
    unittest.main()
