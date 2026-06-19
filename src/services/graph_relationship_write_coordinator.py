import json
import re
import threading
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


NodeRef = Tuple[str, Any]


class GraphNodeAutoHealer:
    """Build missing graph nodes from Mongo data before strict relationship writes."""

    def __init__(self, cls_collection, node_prep_service, neo4j_repository, logger=None):
        self.cls_collection = cls_collection
        self.node_prep_service = node_prep_service
        self.neo4j_repository = neo4j_repository
        self.logger = logger
        self.last_reason_by_ref: Dict[NodeRef, str] = {}

    def ensure_nodes(self, node_refs: Iterable[NodeRef]) -> Set[NodeRef]:
        refs = set(node_refs)
        self.last_reason_by_ref = {}
        doc_id_by_ref = {
            ref: self._extract_doc_id(ref[0], ref[1])
            for ref in refs
        }
        for ref, doc_id in doc_id_by_ref.items():
            if doc_id is None:
                self.last_reason_by_ref[ref] = "invalid_node_id_format"

        doc_ids = sorted(
            {
                doc_id
                for doc_id in doc_id_by_ref.values()
                if doc_id is not None
            }
        )
        if not doc_ids:
            return set()

        try:
            docs = list(self.cls_collection.find({"cls_ID": {"$in": doc_ids}}))
        except Exception:
            for ref, doc_id in doc_id_by_ref.items():
                if doc_id is not None:
                    self.last_reason_by_ref[ref] = "mongo_lookup_error"
            return set()

        if not docs:
            for ref, doc_id in doc_id_by_ref.items():
                if doc_id is not None:
                    self.last_reason_by_ref[ref] = "not_found_in_mongo"
            return set()

        found_doc_ids = {doc.get("cls_ID") for doc in docs}
        for ref, doc_id in doc_id_by_ref.items():
            if doc_id is not None and doc_id not in found_doc_ids:
                self.last_reason_by_ref[ref] = "not_found_in_mongo"

        try:
            doc_params, term_params = self.node_prep_service.batch_prepare_nodes(docs)
            if doc_params or term_params:
                self.neo4j_repository.bulk_upsert_nodes(doc_params=doc_params, term_params=term_params)
        except Exception:
            for ref, doc_id in doc_id_by_ref.items():
                if doc_id in found_doc_ids:
                    self.last_reason_by_ref[ref] = "node_prepare_failed"
            return set()

        existing = set(self.neo4j_repository.fetch_existing_node_keys(refs))
        for ref, doc_id in doc_id_by_ref.items():
            if doc_id in found_doc_ids and ref not in existing:
                self.last_reason_by_ref[ref] = "node_prepare_failed"
        return existing

    @staticmethod
    def _extract_doc_id(label: str, node_id: Any) -> Optional[int]:
        try:
            if label == "VAN_BAN":
                return int(node_id)
            if label == "DIEU_KHOAN" and "#" in str(node_id):
                return int(str(node_id).split("#")[-1])
        except (TypeError, ValueError):
            return None
        return None


class GraphRelationshipWriteCoordinator:
    """Strict-safe relationship writer with optional auto-heal and audit detail."""

    VALID_MODES = {"legacy", "shadow-strict", "strict-auto-heal", "strict-no-heal"}
    INSERTED_TARGET_RELATION_TYPES = frozenset({"bo_sung", "bao_gom_sau_bo_sung"})

    def __init__(
        self,
        neo4j_repository,
        mode: str = "strict-auto-heal",
        node_healer: Optional[GraphNodeAutoHealer] = None,
        logger=None,
    ):
        if mode not in self.VALID_MODES:
            raise ValueError(f"mode must be one of {sorted(self.VALID_MODES)}")
        self.neo4j_repository = neo4j_repository
        self.mode = mode
        self.node_healer = node_healer
        self.logger = logger
        self.detail_records: List[Dict[str, Any]] = []
        self._summary = Counter()
        self._reason_counts = Counter()
        self._lock = threading.Lock()

    def uses_strict_writer(self) -> bool:
        return self.mode in {"strict-auto-heal", "strict-no-heal"}

    def write_grouped_relationships(self, relationships_by_type: Dict[str, List[Dict[str, Any]]]) -> Dict[str, int]:
        grouped = self._deduplicate_grouped_relationships(relationships_by_type)
        attempted = sum(len(params) for params in grouped.values())
        self._increment("attempted", attempted)

        if self.mode == "legacy":
            return self.neo4j_repository.bulk_create_multiple_relationships(grouped)

        if self.mode in {"strict-auto-heal", "strict-no-heal"}:
            inserted_nodes = self._upsert_inserted_target_nodes(grouped)
            self._increment("healed_nodes", len(inserted_nodes))
            grouped = self._remap_to_existing_clause_variants(grouped)

        writable, blocked_records, missing_refs = self._partition_grouped_relationships(grouped)

        if self.mode == "shadow-strict":
            self._record_shadow(blocked_records)
            return self.neo4j_repository.bulk_create_multiple_relationships(grouped, strict_nodes=False)

        if self.mode == "strict-auto-heal" and missing_refs and self.node_healer:
            healed = self.node_healer.ensure_nodes(missing_refs)
            self._increment("healed_nodes", len(healed))
            writable, blocked_records, _ = self._partition_grouped_relationships(
                grouped,
                heal_reasons=getattr(self.node_healer, "last_reason_by_ref", {}),
            )

        self._record_blocked(blocked_records, status="deferred")
        if not writable:
            return {"total": 0}

        result = self.neo4j_repository.bulk_create_multiple_relationships(writable, strict_nodes=True)
        self._increment("written", result.get("total", sum(len(params) for params in writable.values())))
        return result

    def _upsert_inserted_target_nodes(
        self,
        grouped: Dict[str, List[Dict[str, Any]]],
    ) -> Set[NodeRef]:
        """Create synthetic inserted clause targets before strict relationship checks."""
        if not hasattr(self.neo4j_repository, "bulk_upsert_nodes"):
            return set()

        term_params_by_id: Dict[Any, Dict[str, Any]] = {}
        for rel_type, params_list in grouped.items():
            if rel_type not in self.INSERTED_TARGET_RELATION_TYPES:
                continue
            for param in params_list:
                if param.get("tail_class") == "DIEU_KHOAN":
                    tail_id = param.get("tail_ID")
                    if tail_id:
                        node_props = deepcopy(param.get("target_node_props") or {})
                        node_props["ID"] = tail_id
                        term_params_by_id.setdefault(tail_id, node_props)
                # For bao_gom_sau_bo_sung, the head (parent clause) may also be synthetic —
                # create it so that the relationship write does not get blocked by a missing node.
                if rel_type == "bao_gom_sau_bo_sung" and param.get("head_class") == "DIEU_KHOAN":
                    head_id = param.get("head_ID")
                    head_props = param.get("head_node_props")
                    if head_id and head_props:
                        node_props = deepcopy(head_props)
                        node_props["ID"] = head_id
                        term_params_by_id.setdefault(head_id, node_props)

        if not term_params_by_id:
            return set()

        self.neo4j_repository.bulk_upsert_nodes(
            doc_params=[],
            term_params=list(term_params_by_id.values()),
        )
        return {("DIEU_KHOAN", node_id) for node_id in term_params_by_id}

    # Mutually-exclusive action relation groups for conflict resolution.
    # When merging TVPL data into Neo4j, a TVPL relation is skipped if Neo4j
    # already contains a relation from a *different* group for the same (head, tail)
    # pair — in either direction (existing wins over incoming TVPL, per spec).
    _TVPL_CONFLICT_GROUPS: List[frozenset] = [
        frozenset({"sua_doi_bo_sung", "sua_doi", "bo_sung"}),
        frozenset({"thay_the"}),
        frozenset({"bai_bo"}),
        frozenset({"huy_bo"}),
    ]

    def write_tvpl_relationships(self, rel_list: List[Dict[str, Any]], query: str) -> int:
        grouped = defaultdict(list)
        for rel in rel_list:
            grouped[rel.get("rel_type", "")].append(rel)

        deduped = self._deduplicate_grouped_relationships(dict(grouped))
        if self.mode in {"strict-auto-heal", "strict-no-heal"}:
            deduped = self._remap_to_existing_clause_variants(deduped)

        writable_grouped, blocked_records, missing_refs = self._partition_grouped_relationships(deduped)
        attempted = len(rel_list)
        self._increment("attempted", attempted)

        if self.mode == "shadow-strict":
            self._record_shadow(blocked_records)
            return self.neo4j_repository.bulk_create_tvpl_relationships(rel_list, query)

        if self.mode == "strict-auto-heal" and missing_refs and self.node_healer:
            healed = self.node_healer.ensure_nodes(missing_refs)
            self._increment("healed_nodes", len(healed))
            writable_grouped, blocked_records, _ = self._partition_grouped_relationships(
                deduped,
                heal_reasons=getattr(self.node_healer, "last_reason_by_ref", {}),
            )

        self._record_blocked(blocked_records, status="deferred")
        writable = [rel for params in writable_grouped.values() for rel in params]
        if not writable:
            return 0

        # Skip TVPL relations whose action type conflicts with an already-committed
        # relation in Neo4j for the same (head, tail) pair.
        writable = self._filter_tvpl_by_existing_conflicts(writable)
        if not writable:
            return 0

        created = self.neo4j_repository.bulk_create_tvpl_relationships(writable, query)
        self._increment("written", created)
        return created

    def _filter_tvpl_by_existing_conflicts(
        self, rel_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Remove TVPL rels that conflict with relations already present in Neo4j.

        A conflict exists when Neo4j already has any relation in a different
        conflict group for the same (head_ID, tail_ID) pair.  Both directions
        are blocked: existing bai_bo → incoming thay_the is skipped, and
        existing thay_the → incoming bai_bo is also skipped.
        """
        all_conflict_types: Set[str] = set().union(*self._TVPL_CONFLICT_GROUPS)
        # Only check rels that belong to a conflict group
        candidate_rels = [
            r for r in rel_list if r.get("rel_type") in all_conflict_types
        ]
        if not candidate_rels:
            return rel_list

        pairs = [
            {"head_ID": r["head_ID"], "tail_ID": r["tail_ID"]}
            for r in candidate_rels
            if r.get("head_ID") is not None and r.get("tail_ID") is not None
        ]
        if not pairs:
            return rel_list

        # Query Neo4j for any existing conflicting relations on these pairs
        existing_conflict_map: Dict[Tuple[Any, Any], Set[str]] = {}
        try:
            query_existing = (
                "UNWIND $pairs AS pair "
                "MATCH (a {ID: pair.head_ID})-[r]->(b {ID: pair.tail_ID}) "
                "WHERE type(r) IN $conflict_types "
                "RETURN pair.head_ID AS head_ID, pair.tail_ID AS tail_ID, type(r) AS rel_type"
            )
            with self.neo4j_repository.driver.session(
                database=self.neo4j_repository.database
            ) as session:
                records = session.run(
                    query_existing,
                    pairs=pairs,
                    conflict_types=list(all_conflict_types),
                ).data()
            for row in records:
                key = (row["head_ID"], row["tail_ID"])
                existing_conflict_map.setdefault(key, set()).add(row["rel_type"])
        except Exception:
            # If the query fails, be conservative and allow all rels through
            return rel_list

        def _group_index(rel_type: str) -> int:
            for i, grp in enumerate(self._TVPL_CONFLICT_GROUPS):
                if rel_type in grp:
                    return i
            return -1

        filtered: List[Dict[str, Any]] = []
        for rel in rel_list:
            rel_type = rel.get("rel_type", "")
            if rel_type not in all_conflict_types:
                filtered.append(rel)
                continue
            key = (rel.get("head_ID"), rel.get("tail_ID"))
            existing = existing_conflict_map.get(key, set())
            incoming_group = _group_index(rel_type)
            # If any existing relation belongs to a DIFFERENT conflict group → skip
            has_conflict = any(
                _group_index(e) != incoming_group and _group_index(e) >= 0
                for e in existing
            )
            if not has_conflict:
                filtered.append(rel)
        return filtered

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "mode": self.mode,
                "attempted": self._summary["attempted"],
                "written": self._summary["written"],
                "healed_nodes": self._summary["healed_nodes"],
                "deferred": self._summary["deferred"],
                "rejected": self._summary["rejected"],
                "shadow_deferred": self._summary["shadow_deferred"],
                "reason_counts": dict(self._reason_counts),
            }

    def write_audit_files(self, summary_path: Any, detail_path: Any) -> None:
        summary_output = Path(summary_path)
        detail_output = Path(detail_path)
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        detail_output.parent.mkdir(parents=True, exist_ok=True)

        summary_output.write_text(
            json.dumps(self.summary(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with detail_output.open("w", encoding="utf-8") as f:
            for record in self.detail_records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _partition_grouped_relationships(
        self,
        grouped: Dict[str, List[Dict[str, Any]]],
        heal_reasons: Optional[Dict[NodeRef, str]] = None,
    ) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]], Set[NodeRef]]:
        node_refs = self._collect_node_refs(grouped)
        existing_refs = self._fetch_existing_node_refs(node_refs)
        target_props = self._fetch_target_properties(grouped)
        writable = defaultdict(list)
        blocked_records = []
        missing_refs: Set[NodeRef] = set()
        heal_reasons = heal_reasons or {}

        for rel_type, params_list in grouped.items():
            for param in params_list:
                head_ref = self._node_ref(param, "head")
                tail_ref = self._node_ref(param, "tail")
                reason = None
                extra = {}
                if head_ref is None or tail_ref is None:
                    reason = "invalid_node_id_format"
                elif head_ref not in existing_refs:
                    reason = self._missing_reason("source", head_ref, heal_reasons)
                    missing_refs.add(head_ref)
                elif tail_ref not in existing_refs:
                    reason = self._missing_reason("target", tail_ref, heal_reasons)
                    missing_refs.add(tail_ref)
                else:
                    reason, extra = self._target_validation(param, target_props.get(tail_ref, {}))

                if reason:
                    status = "rejected" if self._is_rejected_reason(reason) else "deferred"
                    blocked_records.append(
                        self._detail_record(param, rel_type, reason, status=status, extra=extra)
                    )
                else:
                    writable[rel_type].append(param)

        return dict(writable), blocked_records, missing_refs

    def _remap_to_existing_clause_variants(
        self,
        grouped: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        variant_refs = self._resolve_existing_clause_variant_refs(grouped)
        if not variant_refs:
            return grouped

        remapped = defaultdict(list)
        for rel_type, params_list in grouped.items():
            for param in params_list:
                remapped_param = param
                for side in ("head", "tail"):
                    replacement = variant_refs.get(self._node_ref(param, side))
                    if replacement is None:
                        continue
                    if remapped_param is param:
                        remapped_param = param.copy()
                    remapped_param[f"{side}_ID"] = replacement[1]
                remapped[rel_type].append(remapped_param)

        return dict(remapped)

    def _resolve_existing_clause_variant_refs(
        self,
        grouped: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[NodeRef, NodeRef]:
        if not hasattr(self.neo4j_repository, "fetch_dieu_khoan_variant_node_keys"):
            return {}

        node_refs = self._collect_node_refs(grouped)
        if not node_refs:
            return {}

        existing_refs = self._fetch_existing_node_refs(node_refs)
        missing_clause_refs = {
            ref
            for ref in node_refs - existing_refs
            if self._can_resolve_clause_variant(ref)
        }
        if not missing_clause_refs:
            return {}

        return self.neo4j_repository.fetch_dieu_khoan_variant_node_keys(missing_clause_refs)

    @staticmethod
    def _can_resolve_clause_variant(node_ref: NodeRef) -> bool:
        label, node_id = node_ref
        node_id_str = str(node_id)
        if label != "DIEU_KHOAN" or "#" not in node_id_str:
            return False

        prefix, _ = node_id_str.rsplit("#", 1)
        return "_dk_" not in prefix and "_bosung_" not in prefix

    def _fetch_existing_node_refs(self, node_refs: Set[NodeRef]) -> Set[NodeRef]:
        if not node_refs:
            return set()
        if hasattr(self.neo4j_repository, "fetch_existing_node_keys"):
            return set(self.neo4j_repository.fetch_existing_node_keys(node_refs))
        return {
            (label, node_id)
            for label, node_id in node_refs
            if self.neo4j_repository.verify_node_exists(node_id, label)
        }

    def _fetch_target_properties(self, grouped: Dict[str, List[Dict[str, Any]]]) -> Dict[NodeRef, Dict[str, Any]]:
        if not hasattr(self.neo4j_repository, "fetch_node_properties"):
            return {}

        targets = set()
        for params_list in grouped.values():
            for param in params_list:
                if self._has_target_expectation(param):
                    target_ref = self._node_ref(param, "tail")
                    if target_ref is not None:
                        targets.add(target_ref)

        if not targets:
            return {}

        return self.neo4j_repository.fetch_node_properties(
            list(targets),
            [
                "so_hieu",
                "so_ky_hieu",
                "co_quan_ban_hanh",
                "ngay_ban_hanh",
                "nam_ban_hanh",
                "ten_day_du",
                "trich_yeu",
            ],
        )

    @staticmethod
    def _missing_reason(side: str, node_ref: NodeRef, heal_reasons: Dict[NodeRef, str]) -> str:
        heal_reason = heal_reasons.get(node_ref)
        if heal_reason == "not_found_in_mongo":
            return f"{side}_not_found_in_mongo"
        if heal_reason in {"mongo_lookup_error", "node_prepare_failed", "invalid_node_id_format"}:
            return heal_reason
        return f"missing_{side}"

    @staticmethod
    def _has_target_expectation(param: Dict[str, Any]) -> bool:
        return any(
            param.get(key) is not None
            for key in [
                "target_so_ky_hieu_expected",
                "target_so_hieu_expected",
                "target_co_quan_expected",
                "target_year_expected",
                "target_title_expected",
            ]
        )

    def _target_validation(self, param: Dict[str, Any], target_props: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
        if not self._has_target_expectation(param):
            return None, {}
        if not target_props:
            return None, {"validation_status": "not_enough_evidence"}

        expected_symbol = param.get("target_so_ky_hieu_expected") or param.get("target_so_hieu_expected")
        actual_symbol = target_props.get("so_hieu") or target_props.get("so_ky_hieu")
        if expected_symbol and actual_symbol and self._normalize_text(expected_symbol) != self._normalize_text(actual_symbol):
            return "target_symbol_mismatch", {
                "expected_symbol": expected_symbol,
                "actual_symbol": actual_symbol,
            }

        expected_agency = param.get("target_co_quan_expected")
        actual_agency = target_props.get("co_quan_ban_hanh")
        if expected_agency and actual_agency and self._normalize_text(expected_agency) != self._normalize_text(actual_agency):
            return "target_agency_mismatch", {
                "expected_agency": expected_agency,
                "actual_agency": actual_agency,
            }

        expected_year = param.get("target_year_expected")
        actual_year = target_props.get("nam_ban_hanh") or self._extract_year(target_props.get("ngay_ban_hanh"))
        if expected_year and actual_year and str(expected_year) != str(actual_year):
            return "target_year_mismatch", {
                "expected_year": expected_year,
                "actual_year": actual_year,
            }

        return None, {}

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return re.sub(r"\s+", "", str(value or "").strip().lower())

    @staticmethod
    def _extract_year(value: Any) -> Optional[str]:
        if value is None:
            return None
        match = re.search(r"(\d{4})", str(value))
        return match.group(1) if match else None

    @staticmethod
    def _is_rejected_reason(reason: str) -> bool:
        return reason.endswith("_mismatch") or reason in {"ambiguous_target", "low_confidence_target"}

    @staticmethod
    def _audit_metadata(reason: str) -> Dict[str, Any]:
        if reason in {"source_not_found_in_mongo", "target_not_found_in_mongo"}:
            return {
                "retryable": False,
                "retry_action": "ingest_missing_cls_document_then_rerun",
            }
        if reason == "mongo_lookup_error":
            return {
                "retryable": True,
                "retry_action": "retry_after_mongo_lookup_recovers",
            }
        if reason == "node_prepare_failed":
            return {
                "retryable": True,
                "retry_action": "fix_node_preparation_error_then_rerun",
            }
        if reason in {"missing_source", "missing_target"}:
            return {
                "retryable": True,
                "retry_action": "run_strict_auto_heal_or_ingest_missing_nodes",
            }
        if reason in {"invalid_node_id_format", "ambiguous_target", "low_confidence_target"} or reason.endswith("_mismatch"):
            return {
                "retryable": False,
                "retry_action": "review_target_resolution_before_rerun",
            }
        return {
            "retryable": False,
            "retry_action": "manual_review_required",
        }

    def _deduplicate_grouped_relationships(
        self,
        grouped: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        deduped = {}
        for rel_type, params_list in grouped.items():
            by_key: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
            for param in params_list:
                key = self._dedup_key(rel_type, param)
                if key not in by_key:
                    merged = deepcopy(param)
                    by_key[key] = merged
                else:
                    self._merge_relationship_props(by_key[key], param)
            deduped[rel_type] = list(by_key.values())
        return deduped

    def _merge_relationship_props(self, base: Dict[str, Any], incoming: Dict[str, Any]) -> None:
        merged_ids = self._merge_id_relations(
            base.get("danh_sach_id_lien_quan", {}),
            incoming.get("danh_sach_id_lien_quan", {}),
        )
        if merged_ids:
            base["danh_sach_id_lien_quan"] = merged_ids
        for key in ("mo_ta", "moi_quan_he_goc"):
            if key not in incoming:
                continue
            if key == "moi_quan_he_goc":
                current = base.get(key, [])
                current_list = current if isinstance(current, list) else [current]
                incoming_list = incoming[key] if isinstance(incoming[key], list) else [incoming[key]]
                base[key] = sorted({*current_list, *incoming_list})
            elif incoming[key] and incoming[key] != base.get(key):
                base[key] = "\n".join(
                    item for item in [base.get(key), incoming[key]] if item
                )

    @staticmethod
    def _merge_id_relations(current: Any, incoming: Any) -> Dict[str, Any]:
        merged = deepcopy(current) if isinstance(current, dict) else {}
        if not isinstance(incoming, dict):
            return merged
        for key, value in incoming.items():
            if key not in merged:
                merged[key] = deepcopy(value)
                continue
            if isinstance(merged[key], list) and isinstance(value, list):
                for item in value:
                    if item not in merged[key]:
                        merged[key].append(item)
            elif merged[key] != value:
                merged[key] = [merged[key], value]
        return merged

    @staticmethod
    def _evidence_list(param: Dict[str, Any]) -> List[str]:
        values = []
        if param.get("danh_sach_bang_chung"):
            values.extend(param["danh_sach_bang_chung"])
        if param.get("bang_chung"):
            values.append(param["bang_chung"])
        return [value for i, value in enumerate(values) if value and value not in values[:i]]

    @staticmethod
    def _dedup_key(rel_type: str, param: Dict[str, Any]) -> Tuple[Any, ...]:
        return (
            rel_type,
            param.get("head_class"),
            param.get("head_ID"),
            param.get("tail_class"),
            param.get("tail_ID"),
            param.get("pham_vi", "document"),
        )

    @staticmethod
    def _node_ref(param: Dict[str, Any], side: str) -> Optional[NodeRef]:
        node_id = param.get(f"{side}_ID")
        node_class = param.get(f"{side}_class")
        if node_id is None or node_id == "" or not node_class:
            return None
        return (node_class, node_id)

    def _collect_node_refs(self, grouped: Dict[str, List[Dict[str, Any]]]) -> Set[NodeRef]:
        refs = set()
        for params_list in grouped.values():
            for param in params_list:
                for side in ("head", "tail"):
                    ref = self._node_ref(param, side)
                    if ref is not None:
                        refs.add(ref)
        return refs

    def _detail_record(
        self,
        param: Dict[str, Any],
        rel_type: str,
        reason: str,
        status: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        record = {
            "relation_type": rel_type,
            "source_doc_id": self._doc_id_from_node_id(param.get("head_ID")),
            "target_doc_id": self._doc_id_from_node_id(param.get("tail_ID")),
            "head_ID": param.get("head_ID"),
            "tail_ID": param.get("tail_ID"),
            "head_class": param.get("head_class"),
            "tail_class": param.get("tail_class"),
            "scope": param.get("pham_vi", "document"),
            "source": param.get("nguon_quan_he"),
            "reason": reason,
        }
        record.update(self._audit_metadata(reason))
        if status:
            record["status"] = status
        if extra:
            record.update(extra)
        return record

    @staticmethod
    def _doc_id_from_node_id(node_id: Any) -> Any:
        if isinstance(node_id, int):
            return node_id
        if node_id is None:
            return None
        text = str(node_id)
        if "#" in text:
            suffix = text.split("#")[-1]
            try:
                return int(suffix)
            except ValueError:
                return suffix
        return node_id

    def _record_shadow(self, records: List[Dict[str, Any]]) -> None:
        if not records:
            return
        shadow_records = [{**record, "status": "shadow_deferred"} for record in records]
        with self._lock:
            self.detail_records.extend(shadow_records)
            self._summary["shadow_deferred"] += len(shadow_records)
            for record in shadow_records:
                self._reason_counts[record["reason"]] += 1

    def _record_blocked(self, records: List[Dict[str, Any]], status: str) -> None:
        if not records:
            return
        detail = [{**record, "status": record.get("status", status)} for record in records]
        with self._lock:
            self.detail_records.extend(detail)
            for record in detail:
                self._summary[record["status"]] += 1
                self._reason_counts[record["reason"]] += 1

    def _increment(self, key: str, value: int) -> None:
        if value <= 0:
            return
        with self._lock:
            self._summary[key] += value
