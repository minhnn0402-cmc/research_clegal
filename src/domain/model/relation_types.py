"""Single source of truth for all legal relation type constants.

Consumers should import from here instead of defining their own copies.
Values here must stay in sync with the business domain — when a new
relation type is introduced, add it here first, then update the relevant
extractors, services, and graph builders.
"""

# All relation types that can appear anywhere in the system.
# Includes extraction-time types (extractor output) and graph-time
# sub-types (sua_doi, bo_sung, bao_gom_sau_bo_sung, hop_nhat).
ALL_RELATION_TYPES: frozenset = frozenset({
    "can_cu",
    "dan_chieu",
    "bai_bo",
    "huy_bo",
    "sua_doi_bo_sung",
    "sua_doi",
    "bo_sung",
    "dinh_chi",
    "dinh_chinh",
    "huong_dan",
    "quy_dinh_chi_tiet",
    "thay_the",
    "keo_dai_hieu_luc",
    "hop_nhat",
    "ngung_hieu_luc",
    "bao_gom_sau_bo_sung",
})

# Relation types the extractor recognises and emits.
# Matches RelationsExtractor.get_relationship_types() exactly.
EXTRACTOR_RELATION_TYPES: tuple = (
    "can_cu",
    "dan_chieu",
    "bai_bo",
    "huy_bo",
    "sua_doi_bo_sung",
    "dinh_chi",
    "dinh_chinh",
    "huong_dan",
    "quy_dinh_chi_tiet",
    "thay_the",
    "keo_dai_hieu_luc",
    "hop_nhat",
    "ngung_hieu_luc",
)

# Strong action relations — used to decide conflict priority and LLM triggers.
# Matches RelationsExtractor._MAJOR_RELATION_TYPES exactly.
MAJOR_RELATION_TYPES: frozenset = frozenset({
    "sua_doi_bo_sung",
    "thay_the",
    "bai_bo",
    "huy_bo",
    "dinh_chi",
    "dinh_chinh",
    "ngung_hieu_luc",
    "can_cu",
    "keo_dai_hieu_luc",
    "quy_dinh_chi_tiet",
    "huong_dan",
})

# Relation types eligible for LLM fallback when rule-based extraction is uncertain.
# Matches RelationsExtractor._LLM_ELIGIBLE_RELATION_TYPES exactly.
LLM_ELIGIBLE_RELATION_TYPES: frozenset = frozenset({
    "sua_doi_bo_sung",
    "dan_chieu",
    "thay_the",
    "bai_bo",
    "dinh_chi",
    "dinh_chinh",
    "huong_dan",
    "quy_dinh_chi_tiet",
    "keo_dai_hieu_luc",
    "ngung_hieu_luc",
    "huy_bo",
    "can_cu",
})

# Relation types for which LLM extraction is the primary (not just fallback) path.
# Matches RelationsExtractor.LLM_FALLBACK_RELATION_TYPES exactly.
LLM_FALLBACK_RELATION_TYPES: frozenset = frozenset({
    "dan_chieu",
    "sua_doi_bo_sung",
})

# Relation types preserved by a host-scoped outgoing-relationship reset
# (never deleted when rebuilding a VAN_BAN's relations in place).
# bao_gom is the document's own structural containment.
# bao_gom_sau_bo_sung is *authored* by the amending document but *hosted* on
# the amended target (status_relationship_service.py:200-275 — edge head is
# parent_key#target_doc_id) and carries no author property (no
# nguon_quan_he, only the constant nguon_cap_nhat='cmcai'). A host-scoped
# reset of the target therefore cannot attribute the edge to its author, and
# the target's own rebuild never restores it — only the amender's rebuild
# does. Deleting it would sever a valid out-of-scope bo_sung that an
# incremental run (where the amender is usually out of batch) would not
# recreate, losing the inserted article.
PRESERVED_RELATION_TYPES: frozenset = frozenset({
    "bao_gom",
    "bao_gom_sau_bo_sung",
})

# Ordered list of relation types written to Neo4j in Phase 2.
# Order is preserved for deterministic graph writes.
# Matches StatusRelationshipPreparationService.STATUS_REL_TYPES exactly.
STATUS_RELATION_TYPES: tuple = (
    "sua_doi_bo_sung",
    "sua_doi",
    "bo_sung",
    "thay_the",
    "bai_bo",
    "dinh_chi",
    "dinh_chinh",
    "huong_dan",
    "quy_dinh_chi_tiet",
    "huy_bo",
    "can_cu",
    "dan_chieu",
    "keo_dai_hieu_luc",
    "ngung_hieu_luc",
    "hop_nhat",
    "bao_gom_sau_bo_sung",
)
