"""Convert grouped extractor output into flat evaluation records."""

from __future__ import annotations

from typing import Dict, List, Optional
import re

_CLAUSE_LABEL: Dict[str, str] = {
    "diem": "điểm",
    "khoan": "khoản",
    "dieu": "điều",
}
_CLAUSE_ORDER: List[str] = ["diem", "khoan", "dieu"]


def tail_to_reference(tail: Dict) -> Optional[str]:
    """Render one relation tail into a human-readable reference string."""
    if not tail:
        return None

    parts: List[str] = [] # Ordered parts of the reference string, to be joined with spaces

    for key in _CLAUSE_ORDER:
        info = tail.get(key, {}).get("information", "").strip() # Get the information for this key, or an empty string if not present 
        if info:
            # If the information already starts with the clause label (e.g., "điểm 1"), use it as is; otherwise, prepend the clause label (e.g., "điểm 1").
            if re.match(rf"^{re.escape(_CLAUSE_LABEL[key])}\b", info, re.IGNORECASE):
                parts.append(info)
            else:
                parts.append(f"{_CLAUSE_LABEL[key]} {info}")

    for key, entry in tail.items():
        if key in _CLAUSE_LABEL:
            continue

        doc_info = entry.get("information", "").strip()
        if doc_info:
            parts.append(doc_info)
            break

    return " ".join(parts) if parts else None 


def relations_to_flat(relations_output: List[Dict]) -> List[Dict]:
    """Flatten extractor output into ``{reference, relation}`` items."""
    flat: List[Dict] = []

    for clause_entry in relations_output or []:
        for relation_entry in clause_entry.get("relations", []):
            tails = relation_entry.get("tail", [])
            # Support both single dict and list of dicts
            if isinstance(tails, dict):
                tails = [tails]
            
            for tail in tails:
                reference = tail_to_reference(tail)
                if not reference:
                    continue

                flat.append(
                    {
                        "reference": reference,
                        "relation": relation_entry.get("relation", ""),
                    }
                )

    return flat
