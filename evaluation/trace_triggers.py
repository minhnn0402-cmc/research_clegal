import pandas as pd
import sys
from pathlib import Path

# Insert project root
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.infrastructure.config import ConfigLoader
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.domain.extractors.content_extractor import ContentExtractor
from src.utils.vbhn_handler import is_vanban_hop_nhat
from src.infrastructure.logging import get_logger
from evaluation.evaluate import _build_clause_context, infer_document_type

# Paths
DIFF_PATH = r"c:\Users\minhnn\Documents\cmcai\CAI_Legal\research\evaluation\datasets\report\diff_rules_vs_llm.csv"

def get_trigger_reason(extractor, data, child_to_parent, clause, cls_so_hieu, cls_title, cls_document_type):
    clause_type = (clause.get("com_type") or "").lower()
    clause_key = clause.get("com_key", "")
    
    # Clean cache
    extractor.processed_clause_content_hashes.clear()
    
    # 1. Parse index by key
    clause_index_by_key = {
        c.get("com_key"): c
        for c in data 
        if c.get("com_key")
    }
    
    # 2. Get clause content
    clause_mapped_content = ContentExtractor.get_content_with_positions(clause)
    
    # 3. Handle VBHN
    if is_vanban_hop_nhat(cls_so_hieu):
        return ["VBHN_FLOW"]
        
    # 4. Extract can_cu
    can_cu_relations, operative_content, operative_mapped_content = extractor._extract_can_cu_relations_and_content(
        clause_type=clause_type,
        clause_key=clause_key,
        clause_mapped_content=clause_mapped_content,
        law_titles=extractor.law_titles_for_regex,
        data=data,
        child_to_parent=child_to_parent,
    )
    
    # 5. Extract references
    references = extractor.base_extractor.extract_references(
        content=operative_content,
        doc_types=extractor.doc_types,
        clause_types=extractor.clause_types,
        law_titles=extractor.law_titles_for_regex,
        clause_type=clause_type,
        clause_key=clause_key,
        data=data,
        child_to_parent=child_to_parent,
        cls_title=cls_title,
        position_mapper=operative_mapped_content.raw_span,
    )
    
    if not references:
        return ["NO_REFERENCES"]
        
    parent_content, grandparent_content = extractor._get_ancestor_clause_contents(
        child_to_parent=child_to_parent,
        clause_key=clause_key,
        clause_index_by_key=clause_index_by_key,
        data=data,
    )
    
    relation_types = extractor.base_extractor.extract_relation_types(
        content=operative_content,
        references=references,
        parent_content=parent_content,
        grandparent_content=grandparent_content,
        clause_type=clause_type,
        rejected_buffer=None,
    )
    
    triggers = []
    
    # C0: References exist, but no relation types detected by Regex
    if not relation_types:
        triggers.append("C0")
        return triggers
        
    relation_matches = extractor.base_extractor.match_relations(
        references=references,
        relation_types=relation_types,
        content=operative_content,
        source_so_hieu=cls_so_hieu,
        source_title=cls_title,
    )
    
    detected_types = {
        relation_type.get("relation_type")
        for relation_type in relation_types or []
        if relation_type.get("relation_type")
    }
    has_eligible_type = bool(detected_types & extractor._LLM_ELIGIBLE_RELATION_TYPES)
    
    # C1: relation keyword exists but no target could be matched.
    if has_eligible_type and not relation_matches:
        triggers.append("C1")
        
    # C3: too many references were left unmatched by the rule matcher.
    if has_eligible_type and relation_matches:
        if len(references or []) - len(relation_matches or []) >= 2:
            triggers.append("C3")
            
    # C4a: "quy dinh chi tiet" and "huong dan" co-fire
    if len(detected_types & {"quy_dinh_chi_tiet", "huong_dan"}) >= 2:
        triggers.append("C4a")
        
    # C4b: "dan_chieu" mixed with stronger action relations
    if "dan_chieu" in detected_types and detected_types & extractor._MAJOR_RELATION_TYPES:
        triggers.append("C4b")
        
    # C5: clause-only target lacks a document component
    c5_hit = False
    for match in relation_matches or []:
        reference = match.get("reference") or {}
        has_external_document = any(
            key not in {"dieu", "khoan", "diem"}
            for key, value in reference.items()
            if isinstance(value, dict)
        )
        if not has_external_document:
            c5_hit = True
            break
    if c5_hit:
        triggers.append("C5")
        
    return triggers if triggers else ["NO_TRIGGER_MET"]

def main():
    print("Loading diff CSV...")
    df_diff = pd.read_csv(DIFF_PATH, sep=",", dtype=str).fillna("")
    
    config = ConfigLoader()
    extractor = RelationsExtractor(
        doc_clause_types=config.doc_clause_types,
        law_titles_for_regex=config.law_titles_for_regex,
        logger=get_logger("TraceTriggers"),
    )
    
    results = []
    
    for idx, row in df_diff.iterrows():
        so_hieu = row["so_hieu"]
        title = row.get("title", "")
        clause_type = row["clause_type"]
        content = row["content"]
        parent_content = row["parent_content"]
        grandparent_content = row["grandparent_content"]
        diff_type = row["diff_type"]
        
        data, child_to_parent, clause = _build_clause_context(
            clause_type=clause_type,
            content=content,
            parent_content=parent_content,
            grandparent_content=grandparent_content,
            idx=idx,
        )
        
        cls_document_type = infer_document_type(title, so_hieu)
        
        triggers = get_trigger_reason(
            extractor, data, child_to_parent, clause, so_hieu, title, cls_document_type
        )
        
        results.append({
            "so_hieu": so_hieu,
            "clause_type": clause_type,
            "diff_type": diff_type,
            "triggers": ",".join(triggers)
        })
        
    df_res = pd.DataFrame(results)
    
    print("\n--- TRIGGER DISTRIBUTION ---")
    dist = df_res.groupby(["diff_type", "triggers"]).size().unstack(fill_value=0)
    print(dist)
    
    print("\n--- DETAILED SUMMARY ---")
    summary = df_res.groupby(["diff_type", "triggers"]).size().reset_index(name="count")
    for idx, row in summary.iterrows():
        print(f"Diff Type: {row['diff_type']:<22} | Triggers: {row['triggers']:<12} | Count: {row['count']}")

if __name__ == "__main__":
    main()
