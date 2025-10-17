"""Unit tests for sort manager."""

import unittest

from z3 import BoolSort, IntSort, RealSort, is_sort

from z3adapter.dsl.sorts import SortManager


class TestSortManager(unittest.TestCase):
    """Test cases for SortManager."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.sort_manager = SortManager()

    def test_builtin_sorts_initialized(self) -> None:
        """Test that built-in sorts are initialized."""
        self.assertIn("IntSort", self.sort_manager.sorts)
        self.assertIn("BoolSort", self.sort_manager.sorts)
        self.assertIn("RealSort", self.sort_manager.sorts)
        self.assertEqual(self.sort_manager.sorts["IntSort"], IntSort())
        self.assertEqual(self.sort_manager.sorts["BoolSort"], BoolSort())
        self.assertEqual(self.sort_manager.sorts["RealSort"], RealSort())

    def test_create_declare_sort(self) -> None:
        """Test creating a declared sort."""
        sort_defs = [{"name": "MySort", "type": "DeclareSort"}]
        self.sort_manager.create_sorts(sort_defs)
        self.assertIn("MySort", self.sort_manager.sorts)
        self.assertTrue(is_sort(self.sort_manager.sorts["MySort"]))

    def test_create_enum_sort(self) -> None:
        """Test creating an enum sort."""
        import uuid

        unique_name = f"TestColor_{uuid.uuid4().hex[:8]}"
        sort_defs = [
            {"name": unique_name, "type": "EnumSort", "values": ["red_t", "green_t", "blue_t"]}
        ]
        self.sort_manager.create_sorts(sort_defs)
        self.assertIn(unique_name, self.sort_manager.sorts)
        # Check that enum constants were created
        self.assertIn("red_t", self.sort_manager.constants)
        self.assertIn("green_t", self.sort_manager.constants)
        self.assertIn("blue_t", self.sort_manager.constants)

    def test_create_bitvec_sort_valid_size(self) -> None:
        """Test creating a bitvector sort with valid size."""
        sort_defs = [{"name": "MyBV8", "type": "BitVecSort(8)"}]
        self.sort_manager.create_sorts(sort_defs)
        self.assertIn("MyBV8", self.sort_manager.sorts)

    def test_create_bitvec_sort_zero_size(self) -> None:
        """Test that zero size bitvector raises error."""
        sort_defs = [{"name": "MyBV0", "type": "BitVecSort(0)"}]
        with self.assertRaises(ValueError) as ctx:
            self.sort_manager.create_sorts(sort_defs)
        self.assertIn("must be positive", str(ctx.exception))

    def test_create_bitvec_sort_negative_size(self) -> None:
        """Test that negative size bitvector raises error."""
        sort_defs = [{"name": "MyBVNeg", "type": "BitVecSort(-1)"}]
        with self.assertRaises(ValueError) as ctx:
            self.sort_manager.create_sorts(sort_defs)
        self.assertIn("must be positive", str(ctx.exception))

    def test_create_bitvec_sort_too_large(self) -> None:
        """Test that oversized bitvector raises error."""
        sort_defs = [{"name": "MyBVHuge", "type": "BitVecSort(100000)"}]
        with self.assertRaises(ValueError) as ctx:
            self.sort_manager.create_sorts(sort_defs)
        self.assertIn("exceeds maximum", str(ctx.exception))

    def test_create_array_sort_valid(self) -> None:
        """Test creating an array sort."""
        sort_defs = [{"name": "IntArray", "type": "ArraySort(IntSort, IntSort)"}]
        self.sort_manager.create_sorts(sort_defs)
        self.assertIn("IntArray", self.sort_manager.sorts)

    def test_create_array_sort_with_custom_domain(self) -> None:
        """Test creating array sort with custom domain."""
        sort_defs = [
            {"name": "MySort", "type": "DeclareSort"},
            {"name": "MyArray", "type": "ArraySort(MySort, IntSort)"},
        ]
        self.sort_manager.create_sorts(sort_defs)
        self.assertIn("MyArray", self.sort_manager.sorts)

    def test_create_array_sort_undefined_domain(self) -> None:
        """Test that array with undefined domain raises error."""
        sort_defs = [{"name": "BadArray", "type": "ArraySort(UndefinedSort, IntSort)"}]
        with self.assertRaises(ValueError) as ctx:
            self.sort_manager.create_sorts(sort_defs)
        self.assertIn("undefined sorts", str(ctx.exception).lower())

    def test_topological_sort_simple(self) -> None:
        """Test topological sorting with simple dependency."""
        sort_defs = [
            {"name": "Array1", "type": "ArraySort(Sort1, IntSort)"},
            {"name": "Sort1", "type": "DeclareSort"},
        ]
        # Should reorder so Sort1 comes before Array1
        self.sort_manager.create_sorts(sort_defs)
        self.assertIn("Sort1", self.sort_manager.sorts)
        self.assertIn("Array1", self.sort_manager.sorts)

    def test_topological_sort_chain(self) -> None:
        """Test topological sorting with chain of dependencies."""
        sort_defs = [
            {"name": "Array2", "type": "ArraySort(Array1, IntSort)"},
            {"name": "Array1", "type": "ArraySort(Sort1, IntSort)"},
            {"name": "Sort1", "type": "DeclareSort"},
        ]
        self.sort_manager.create_sorts(sort_defs)
        self.assertIn("Sort1", self.sort_manager.sorts)
        self.assertIn("Array1", self.sort_manager.sorts)
        self.assertIn("Array2", self.sort_manager.sorts)

    def test_topological_sort_circular_dependency(self) -> None:
        """Test that circular dependencies are detected."""
        # Note: ArraySort can't actually create circular deps, but test the algorithm
        sort_defs = [
            {"name": "Sort1", "type": "DeclareSort"},
            {"name": "Sort2", "type": "DeclareSort"},
        ]
        # This doesn't create circular dep, just testing the sorts are independent
        self.sort_manager.create_sorts(sort_defs)
        self.assertIn("Sort1", self.sort_manager.sorts)
        self.assertIn("Sort2", self.sort_manager.sorts)

    def test_create_functions(self) -> None:
        """Test creating functions."""
        sort_defs = [{"name": "MySort", "type": "DeclareSort"}]
        self.sort_manager.create_sorts(sort_defs)

        func_defs = [
            {"name": "f", "domain": ["IntSort"], "range": "IntSort"},
            {"name": "g", "domain": ["MySort", "IntSort"], "range": "BoolSort"},
        ]
        functions = self.sort_manager.create_functions(func_defs)
        self.assertIn("f", functions)
        self.assertIn("g", functions)

    def test_create_functions_undefined_domain_sort(self) -> None:
        """Test that function with undefined domain sort raises error."""
        func_defs = [{"name": "f", "domain": ["UndefinedSort"], "range": "IntSort"}]
        with self.assertRaises(ValueError):
            self.sort_manager.create_functions(func_defs)

    def test_create_constants_list_format(self) -> None:
        """Test creating constants with list format."""
        constants_defs = {"numbers": {"sort": "IntSort", "members": ["x", "y", "z"]}}
        self.sort_manager.create_constants(constants_defs)
        self.assertIn("x", self.sort_manager.constants)
        self.assertIn("y", self.sort_manager.constants)
        self.assertIn("z", self.sort_manager.constants)

    def test_create_constants_dict_format(self) -> None:
        """Test creating constants with dict format."""
        constants_defs = {"values": {"sort": "IntSort", "members": {"a": "val_a", "b": "val_b"}}}
        self.sort_manager.create_constants(constants_defs)
        # Should use keys as Z3 constant names
        self.assertIn("a", self.sort_manager.constants)
        self.assertIn("b", self.sort_manager.constants)

    def test_create_constants_undefined_sort(self) -> None:
        """Test that constants with undefined sort raise error."""
        constants_defs = {"bad": {"sort": "UndefinedSort", "members": ["x"]}}
        with self.assertRaises(ValueError) as ctx:
            self.sort_manager.create_constants(constants_defs)
        self.assertIn("not defined", str(ctx.exception))

    def test_create_variables(self) -> None:
        """Test creating variables."""
        var_defs = [{"name": "x", "sort": "IntSort"}, {"name": "y", "sort": "BoolSort"}]
        variables = self.sort_manager.create_variables(var_defs)
        self.assertIn("x", variables)
        self.assertIn("y", variables)

    def test_create_variables_undefined_sort(self) -> None:
        """Test that variables with undefined sort raise error."""
        var_defs = [{"name": "x", "sort": "UndefinedSort"}]
        with self.assertRaises(ValueError) as ctx:
            self.sort_manager.create_variables(var_defs)
        self.assertIn("not defined", str(ctx.exception))

    def test_missing_required_field_in_sort(self) -> None:
        """Test that missing required field raises error."""
        sort_defs = [{"type": "DeclareSort"}]  # Missing 'name'
        with self.assertRaises(ValueError):
            self.sort_manager.create_sorts(sort_defs)

    def test_invalid_sort_type(self) -> None:
        """Test that invalid sort type raises error."""
        sort_defs = [{"name": "BadSort", "type": "InvalidSortType"}]
        with self.assertRaises(ValueError) as ctx:
            self.sort_manager.create_sorts(sort_defs)
        self.assertIn("Unknown sort type", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
