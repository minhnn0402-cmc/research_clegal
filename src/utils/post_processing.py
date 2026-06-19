# Deprecated shim — import from src.services.extraction.reference_resolution_service instead.
from src.services.extraction.reference_resolution_service import (  # noqa: F401
    post_process_relations,
    _prepare_reference_for_mongo,
    _filter_conflicting_relations,
    _create_clause_key_reference,
    _post_processing_component_name,
    _process_single_reference,
    _conflict_priority,
    _get_executor,
    _get_law_titles_for_regex,
    _get_law_dataframe,
)
