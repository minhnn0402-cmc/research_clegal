import json
from pathlib import Path

from evaluation.converter import relations_to_flat
from src.domain.extractors.relations_extractor import RelationsExtractor
from src.infrastructure.config import ConfigLoader


DATA_PATH = Path(__file__).parent.parent / "test_data" / "mongo_relation_cases.json"


def _load_cases():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return [case for case in data["cases"] if case.get("status") == "active"]


def _data_for_extractor(case):
    data = []
    for clause in case["data"]:
        prepared_clause = dict(clause)
        if prepared_clause.get("com_content"):
            prepared_clause["mongo_com_title"] = prepared_clause.get("com_title")
            prepared_clause["com_title"] = prepared_clause["com_content"]
        data.append(prepared_clause)
    return data


def _extract(case):
    config = ConfigLoader()
    extractor = RelationsExtractor(
        doc_clause_types=config.doc_clause_types,
        law_titles_for_regex=config.law_titles_for_regex,
    )
    source = case["source"]
    results = extractor.extract_relations(
        data=_data_for_extractor(case),
        cls_so_hieu=source.get("so_hieu", ""),
        cls_title=source.get("title", ""),
        cls_document_type=source.get("loai_van_ban", ""),
        use_llm=False,
    )
    return relations_to_flat(results)


def test_mongo_derived_relation_cases_match_expected_relations():
    for case in _load_cases():
        flat = _extract(case)
        pairs = {(item["relation"], item["reference"]) for item in flat}

        for expected in case["expected_relations"]:
            assert (
                expected["relation"],
                expected["reference"],
            ) in pairs, f"{case['id']} missing expected relation: {expected}"


def test_mongo_derived_relation_cases_reject_forbidden_relations():
    for case in _load_cases():
        flat = _extract(case)
        pairs = {(item["relation"], item["reference"]) for item in flat}

        for forbidden in case["forbidden_relations"]:
            assert (
                forbidden["relation"],
                forbidden["reference"],
            ) not in pairs, f"{case['id']} produced forbidden relation: {forbidden}"


def test_mongo_derived_fixtures_include_real_mongo_snapshot_cases():
    cases = _load_cases()
    mongo_cases = [
        case
        for case in cases
        if case.get("fixture_source", {}).get("kind") == "mongo_snapshot"
    ]

    assert mongo_cases, "Expected at least one offline fixture exported from live Mongo"
    for case in mongo_cases:
        assert case["source"].get("cls_ID"), f"{case['id']} missing source cls_ID"
        assert case["data"], f"{case['id']} missing clause data"
        for clause in case["data"]:
            assert clause.get("com_key"), f"{case['id']} has clause without com_key"
            assert clause.get("com_type"), f"{case['id']} has clause without com_type"
            assert clause.get("com_content"), f"{case['id']} has clause without com_content"
