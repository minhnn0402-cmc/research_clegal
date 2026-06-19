"""End-to-end tests for relation extraction using real dataset samples."""

import json
import logging
import unittest
from pathlib import Path

from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader

logging.disable(logging.INFO)

class TestExtractRelationsE2E(unittest.TestCase):
    """E2E Test validate relations against actual True Positives from dataset."""

    @classmethod
    def setUpClass(cls):
        """Load the test dataset once for all E2E tests."""
        cls.config = ConfigLoader()
        cls.extractor = RelationsExtractor(
            doc_clause_types=cls.config.doc_clause_types,
            law_titles_for_regex=cls.config.law_titles_for_regex,
        )
        
        test_data_path = Path(__file__).parent.parent / "test_data" / "tp_samples.json"
        with open(test_data_path, "r", encoding="utf-8") as f:
            cls.tp_samples = json.load(f)

    def _build_context(self, sample) -> tuple:
        """Helper to build data format exactly like _process_clause needs."""
        clause_type = sample["clause_type"]
        cur_key = "eval_1"
        parent_key = "eval_1_parent"
        grandparent_key = "eval_1_grandparent"
        
        clause = {"com_type": clause_type, "com_key": cur_key, "com_title": sample["content"]}
        
        if clause_type in {"vanban", "dieu"} or not sample["parent_content"].strip():
            return [clause], {}, clause
            
        if clause_type == "khoan":
            parent_clause = {"com_type": "dieu", "com_key": parent_key, "com_title": sample["parent_content"]}
            return [parent_clause, clause], {cur_key: parent_key}, clause
            
        if clause_type == "diem":
            parent_clause = {"com_type": "khoan", "com_key": parent_key, "com_title": sample["parent_content"]}
            child_to_parent = {cur_key: parent_key}
            
            if sample["grandparent_content"].strip():
                grandparent_clause = {"com_type": "dieu", "com_key": grandparent_key, "com_title": sample["grandparent_content"]}
                child_to_parent[parent_key] = grandparent_key
                return [grandparent_clause, parent_clause, clause], child_to_parent, clause
                
            return [parent_clause, clause], child_to_parent, clause
            
        return [clause], {}, clause

    def _run_extraction(self, sample) -> list:
        data, child_to_parent, clause = self._build_context(sample)
        
        # Clear cache 
        self.extractor.processed_clause_content_hashes.clear()
        
        result = self.extractor._process_clause(
            data=data,
            child_to_parent=child_to_parent,
            clause=clause,
            law_titles=self.config.law_titles_for_regex,
            cls_so_hieu=sample["so_hieu"],
            cls_title=sample["title"],
            use_llm=False
        )
        
        # Flatten relations
        flat_results = []
        if result:
            from evaluation.converter import relations_to_flat
            flat_results = relations_to_flat(result)
        return flat_results

    def _assert_relation_extracted(self, target_relation: str, min_samples: int):
        """Generic runner to assert relations for a type."""
        samples = self.tp_samples.get(target_relation, [])
        self.assertGreaterEqual(len(samples), min_samples, f"Not enough samples for {target_relation}")
        
        for idx, sample in enumerate(samples):
            with self.subTest(relation=target_relation, index=idx, so_hieu=sample["so_hieu"]):
                results = self._run_extraction(sample)
                # Check if there is ANY result that matches the target reference and relation
                found = False
                for r in results:
                    if r["relation"] == target_relation and r["reference"] == sample["tp_reference"]:
                        found = True
                        break
                
                self.assertTrue(
                    found, 
                    f"Failed to find TP relation '{target_relation}' for reference '{sample['tp_reference']}' in {sample['so_hieu']}."
                )

    # ================== MAIN 5 RELATIONS (At least 5 samples) ==================

    def test_e2e_sua_doi_bo_sung(self):
        self._assert_relation_extracted("sua_doi_bo_sung", 3)

    def test_e2e_dan_chieu(self):
        self._assert_relation_extracted("dan_chieu", 5)

    def test_e2e_bai_bo(self):
        self._assert_relation_extracted("bai_bo", 5)

    def test_e2e_thay_the(self):
        self._assert_relation_extracted("thay_the", 5)

    def test_e2e_can_cu(self):
        self._assert_relation_extracted("can_cu", 5)

    # ================== OTHER RELATIONS (At least 3 samples) ==================

    def test_e2e_hop_nhat(self):
        self._assert_relation_extracted("hop_nhat", 3)

    def test_e2e_huy_bo(self):
        self._assert_relation_extracted("huy_bo", 3)

    def test_e2e_keo_dai_hieu_luc(self):
        self._assert_relation_extracted("keo_dai_hieu_luc", 3)

    def test_e2e_quy_dinh_chi_tiet(self):
        self._assert_relation_extracted("quy_dinh_chi_tiet", 3)

    def test_e2e_huong_dan(self):
        self._assert_relation_extracted("huong_dan", 3)

    def test_e2e_dinh_chinh(self):
        self._assert_relation_extracted("dinh_chinh", 3)
        
    def test_e2e_dinh_chi(self):
        self._assert_relation_extracted("dinh_chi", 3)
        
    def test_e2e_ngung_hieu_luc(self):
        self._assert_relation_extracted("ngung_hieu_luc", 3)

if __name__ == "__main__":
    unittest.main()
