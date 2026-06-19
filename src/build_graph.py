"""Neo4j Knowledge Graph Builder - Main Entry Point."""

# ruff: noqa: E402

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.app.build_graph_app import (  # noqa: F401 — re-exported for tests
    BuildGraphApp,
    parse_arguments,
    _write_graph_audit_report,
    _process_status_relationship_batch,
)


def main(argv=None):
    """Main entry point."""
    args = parse_arguments(argv)
    return BuildGraphApp(args).run()


if __name__ == "__main__":
    sys.exit(main())
