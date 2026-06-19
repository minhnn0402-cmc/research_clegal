import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import run_pipeline


def _ns(**overrides):
    """Build a parsed-args namespace with run_pipeline's defaults, overridable per test."""
    defaults = {
        "mode": None,
        "doc_ids_file": None,
        "skip_collect": False,
        "skip_enrich": False,
        "dry_run": False,
        "suffix": None,
        "extraction_batch_size": None,
        "extraction_parallel_workers": None,
        "mongo_extraction_collection": None,
        "graph_batch_size": None,
        "graph_parallel_workers": None,
        "neo4j_db": None,
        "neo4j_env": None,
        "graph_audit_output": None,
        "graph_resolution_mode": None,
        "node_batch_size": None,
        "structural_rel_batch_size": None,
        "status_rel_batch_size": None,
        "inferred_rel_batch_size": None,
        "tvpl_batch_size": None,
        "luoc_do_batch_size": None,
        "orphan_node_batch_size": None,
        "with_tvpl": False,
        "with_luoc_do_export": False,
        "reconcile_after_build": False,
        "clear_es_cache": False,
        "clear_checkpoints": False,
        "delete_orphan_nodes": False,
    }
    defaults.update(overrides)
    import argparse
    return argparse.Namespace(**defaults)


class TestAssembleDocIds(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._base = Path(self._tmpdir.name)
        self._files = {}
        for key, ids in {
            "central_ids": [1, 2, 3],
            "local_ids": [3, 4],
            "latest_central_ids": [10],
            "latest_local_ids": [10, 11],
        }.items():
            path = self._base / f"{key}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(ids, f)
            self._files[key] = str(path)
        self._files["law_ids"] = str(self._base / "law_ids.json")
        self._files["latest_law_ids"] = str(self._base / "latest_law_ids.json")
        self.output_path = self._base / "doc_ids.json"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_full_mode_assembles_from_central_and_local_deduped(self):
        ids = run_pipeline._assemble_doc_ids("full", self._files, self.output_path)

        self.assertEqual(ids, [1, 2, 3, 4])
        with open(self.output_path, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f), [1, 2, 3, 4])

    def test_incremental_mode_assembles_from_latest_central_and_local_deduped(self):
        ids = run_pipeline._assemble_doc_ids("incremental", self._files, self.output_path)

        self.assertEqual(ids, [10, 11])
        with open(self.output_path, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f), [10, 11])


class TestBuildMainArgv(unittest.TestCase):
    def test_swaps_doc_ids_file_and_replaces_clear_before_build_with_reset_relations(self):
        argv = run_pipeline._build_main_argv("./data/doc_ids.json", _ns())

        self.assertEqual(argv[:3], ["--doc-ids-file", "./data/doc_ids.json", "--reset-relations"])
        self.assertNotIn("--clear-before-build", argv)

    def test_forwards_only_explicitly_set_pass_through_flags(self):
        argv = run_pipeline._build_main_argv(
            "./data/doc_ids.json",
            _ns(neo4j_env="DEV", graph_batch_size=500, with_tvpl=True),
        )

        self.assertIn("--neo4j-env", argv)
        self.assertEqual(argv[argv.index("--neo4j-env") + 1], "DEV")
        self.assertIn("--graph-batch-size", argv)
        self.assertEqual(argv[argv.index("--graph-batch-size") + 1], "500")
        self.assertIn("--with-tvpl", argv)

        # Flags the user never set are omitted entirely (so main.py's defaults apply).
        self.assertNotIn("--neo4j-db", argv)
        self.assertNotIn("--extraction-batch-size", argv)
        self.assertNotIn("--clear-es-cache", argv)
        self.assertNotIn("--clear-checkpoints", argv)

    def test_forwards_reconcile_after_build_with_audit_options(self):
        argv = run_pipeline._build_main_argv(
            "./data/doc_ids.json",
            _ns(
                reconcile_after_build=True,
                graph_audit_output="reports/strict_graph_audit.json",
                graph_resolution_mode="strict",
            ),
        )

        self.assertIn("--reconcile-after-build", argv)
        self.assertIn("--graph-audit-output", argv)
        self.assertEqual(
            argv[argv.index("--graph-audit-output") + 1],
            "reports/strict_graph_audit.json",
        )
        self.assertIn("--graph-resolution-mode", argv)
        self.assertEqual(argv[argv.index("--graph-resolution-mode") + 1], "strict")

    def test_forwards_mongo_extraction_collection_to_main(self):
        argv = run_pipeline._build_main_argv(
            "./data/doc_ids.json",
            _ns(mongo_extraction_collection="test"),
        )

        self.assertIn("--mongo-extraction-collection", argv)
        self.assertEqual(argv[argv.index("--mongo-extraction-collection") + 1], "test")


class TestResolveDocIdsFile(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn_manager = MagicMock()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_custom_doc_ids_file_bypasses_collect_and_enrich(self):
        ns = _ns(doc_ids_file="./data/my_ids.json")

        with patch.object(run_pipeline, "_collect_ids") as mock_collect, \
             patch.object(run_pipeline, "_enrich_law_docs") as mock_enrich:
            result = run_pipeline._resolve_doc_ids_file(ns, self.conn_manager)

        self.assertEqual(result, "./data/my_ids.json")
        mock_collect.assert_not_called()
        mock_enrich.assert_not_called()

    def test_mode_path_runs_collect_then_enrich_then_assembles(self):
        ns = _ns(mode="incremental")
        file_paths = {
            "central_ids": "./data/doc_ids/central_ids.json",
            "local_ids": "./data/doc_ids/local_ids.json",
            "law_ids": "./data/doc_ids/law_ids.json",
            "latest_central_ids": "./data/doc_ids/latest_central_ids.json",
            "latest_local_ids": "./data/doc_ids/latest_local_ids.json",
            "latest_law_ids": "./data/doc_ids/latest_law_ids.json",
        }
        output_path = Path(self._tmpdir.name) / "doc_ids.json"

        with patch.object(run_pipeline, "_collect_ids", return_value=file_paths) as mock_collect, \
             patch.object(run_pipeline, "_enrich_law_docs", return_value=True) as mock_enrich, \
             patch.object(run_pipeline, "DOC_IDS_OUTPUT_PATH", output_path), \
             patch.object(run_pipeline, "_assemble_doc_ids", return_value=[1, 2]) as mock_assemble:
            result = run_pipeline._resolve_doc_ids_file(ns, self.conn_manager)

        mock_collect.assert_called_once_with(ns, self.conn_manager)
        mock_enrich.assert_called_once_with(ns, self.conn_manager, file_paths)
        mock_assemble.assert_called_once_with("incremental", file_paths, output_path)
        self.assertEqual(result, str(output_path))

    def test_returns_none_when_collect_fails(self):
        ns = _ns(mode="full")

        with patch.object(run_pipeline, "_collect_ids", return_value=None), \
             patch.object(run_pipeline, "_enrich_law_docs") as mock_enrich:
            result = run_pipeline._resolve_doc_ids_file(ns, self.conn_manager)

        self.assertIsNone(result)
        mock_enrich.assert_not_called()

    def test_dry_run_assembles_nothing_but_returns_planned_path(self):
        ns = _ns(mode="full", dry_run=True)
        file_paths = {"central_ids": "c.json", "local_ids": "l.json", "law_ids": "law.json",
                      "latest_central_ids": "lc.json", "latest_local_ids": "ll.json", "latest_law_ids": "ll2.json"}
        output_path = Path(self._tmpdir.name) / "doc_ids.json"

        with patch.object(run_pipeline, "_collect_ids", return_value=file_paths), \
             patch.object(run_pipeline, "_enrich_law_docs", return_value=True), \
             patch.object(run_pipeline, "DOC_IDS_OUTPUT_PATH", output_path), \
             patch.object(run_pipeline, "_assemble_doc_ids") as mock_assemble:
            result = run_pipeline._resolve_doc_ids_file(ns, self.conn_manager)

        mock_assemble.assert_not_called()
        self.assertFalse(output_path.exists())
        self.assertEqual(result, str(output_path))


class TestDedupPreserveOrder(unittest.TestCase):
    def test_dedupes_across_lists_preserving_first_seen_order(self):
        result = run_pipeline._dedup_preserve_order([1, 2, 3], [3, 4, 2, 5])

        self.assertEqual(result, [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
