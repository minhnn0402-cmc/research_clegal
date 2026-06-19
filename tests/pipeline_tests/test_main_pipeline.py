import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import main as pipeline_main


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TestMainPipeline(unittest.TestCase):
    def test_dry_run_forwards_mongo_extraction_collection_to_build_phase(self):
        doc_ids_file = _PROJECT_ROOT / "data" / "doc_ids.json"
        old_argv = sys.argv
        sys.argv = [
            "main.py",
            "--doc-ids-file",
            str(doc_ids_file),
            "--dry-run",
            "--mongo-extraction-collection",
            "test",
        ]
        stdout = io.StringIO()
        try:
            with redirect_stdout(stdout):
                pipeline_main.main()
        finally:
            sys.argv = old_argv

        output = stdout.getvalue()
        self.assertIn("[DRY-RUN] Planned Phase 2:", output)
        self.assertIn("--mongo-extraction-collection test", output)


if __name__ == "__main__":
    unittest.main()
