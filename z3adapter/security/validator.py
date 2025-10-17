"""Expression validator for security checks."""

import ast
from typing import Any


class ExpressionValidator:
    """Validates expressions for security issues before evaluation."""

    @staticmethod
    def check_safe_ast(node: ast.AST, expr_str: str) -> None:
        """Check AST for dangerous constructs.

        Args:
            node: AST node to check
            expr_str: Original expression string for error messages

        Raises:
            ValueError: If dangerous construct found
        """
        for n in ast.walk(node):
            # Block attribute access to dunder methods
            if isinstance(n, ast.Attribute):
                if n.attr.startswith("__") and n.attr.endswith("__"):
                    raise ValueError(
                        f"Access to dunder attribute '{n.attr}' not allowed in '{expr_str}'"
                    )
            # Block imports
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                raise ValueError(f"Import statements not allowed in '{expr_str}'")
            # Block function/class definitions
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                raise ValueError(f"Function/class definitions not allowed in '{expr_str}'")
            # Block exec/eval
            elif isinstance(n, ast.Call):
                if isinstance(n.func, ast.Name) and n.func.id in (
                    "eval",
                    "exec",
                    "compile",
                    "__import__",
                ):
                    raise ValueError(f"Call to '{n.func.id}' not allowed in '{expr_str}'")

    @staticmethod
    def safe_eval(expr_str: str, safe_globals: dict[str, Any], context: dict[str, Any]) -> Any:
        """Safely evaluate expression string with restricted globals.

        Args:
            expr_str: Expression string to evaluate
            safe_globals: Safe global functions/operators
            context: Local context dictionary

        Returns:
            Evaluated expression

        Raises:
            ValueError: If expression cannot be evaluated safely
        """
        try:
            # Parse to AST and check for dangerous constructs
            tree = ast.parse(expr_str, mode="eval")
            ExpressionValidator.check_safe_ast(tree, expr_str)

            # Compile and evaluate with restricted builtins
            code = compile(tree, "<string>", "eval")
            return eval(code, {"__builtins__": {}}, {**safe_globals, **context})
        except SyntaxError as e:
            raise ValueError(f"Syntax error in expression '{expr_str}': {e}") from e
        except NameError as e:
            raise ValueError(f"Undefined name in expression '{expr_str}': {e}") from e
        except Exception as e:
            raise ValueError(f"Error evaluating expression '{expr_str}': {e}") from e
