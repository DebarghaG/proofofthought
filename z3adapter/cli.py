"""Command-line interface for Z3 JSON DSL interpreter."""

import argparse
import logging
import sys

from z3adapter.interpreter import Z3JSONInterpreter

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Z3 JSON DSL Interpreter - Execute Z3 solver configurations from JSON files",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("json_file", type=str, help="Path to JSON configuration file")
    parser.add_argument(
        "--verify-timeout",
        type=int,
        default=Z3JSONInterpreter.DEFAULT_VERIFY_TIMEOUT,
        help="Timeout for verification checks in milliseconds",
    )
    parser.add_argument(
        "--optimize-timeout",
        type=int,
        default=Z3JSONInterpreter.DEFAULT_OPTIMIZE_TIMEOUT,
        help="Timeout for optimization in milliseconds",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point for CLI."""
    args = parse_args()

    # Configure logging when running as main script
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")

    try:
        interpreter = Z3JSONInterpreter(
            args.json_file,
            verify_timeout=args.verify_timeout,
            optimize_timeout=args.optimize_timeout,
        )
        interpreter.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
