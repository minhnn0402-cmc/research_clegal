"""
Multiple reference expander for legal document references.

This module handles expansion of patterns like "các khoản 3, 4 và 5 Điều 121"
into multiple separate references for each clause component.

Examples:
    - "các khoản 3, 4 và 5" → khoan 3, khoan 4, khoan 5
    - "các điều 10, 11 và 12" → dieu 10, dieu 11, dieu 12
    - "điểm a, b, c" → diem a, diem b, diem c
"""

import re
from typing import List, Dict
from copy import deepcopy


class MultipleReferenceExpander:
    """
    Expands multiple reference patterns into individual references.
    
    Handles Vietnamese legal text patterns that list multiple clause numbers
    in a comma-separated format.
    """
    
    # Patterns to detect multiple references
    # Format: "các {clause_type} {numbers with commas and 'và'}"
    MULTIPLE_PATTERN = re.compile(
        r'\b(các\s+)?(khoản|điều|điểm)\s+'
        r'([\d\w]+(?:\s*,\s*[\d\w]+)*(?:\s+và\s+[\d\w]+)?)\b',
        re.IGNORECASE
    )
    CLAUSE_LABELS = {
        'diem': 'điểm',
        'khoan': 'khoản',
        'dieu': 'Điều',
    }
    
    
    @classmethod
    def extract_numbers_list(cls, numbers_text: str) -> List[str]:
        """
        Extract list of numbers/letters from comma-separated text.
        
        Args:
            numbers_text: Text like "3, 4 và 5" or "a, b, c"
            
        Returns:
            List of individual numbers/letters
        """
        # Replace "và" with comma for uniform processing
        normalized = numbers_text.replace(' và ', ', ')
        
        # Split by comma and clean up
        items = [item.strip() for item in normalized.split(',')]
        
        # Filter out empty strings
        return [item for item in items if item]
    
    @classmethod
    def expand_references(cls, references: List[Dict]) -> List[Dict]:
        """
        Expand references that contain multiple clause numbers.
        
        This processes references extracted by the normal flow and expands
        any that reference multiple clauses (e.g., "các khoản 3, 4 và 5").
        
        Args:
            references: List of reference dictionaries
            
        Returns:
            Expanded list with one reference per clause number
        """
        expanded = []
        
        for ref in references:
            expanded_refs = cls._expand_single_reference(ref)
            
            expanded.extend(expanded_refs)
        
        return expanded
    
    @classmethod
    def _expand_single_reference(cls, reference: Dict) -> List[Dict]:
        """
        Expand a single reference if it contains multiple clause numbers.
        
        Args:
            reference: Single reference dictionary
            
        Returns:
            List of expanded references (single item if no expansion needed)
        """
        # Get the lowest-level clause component (khoan, dieu, diem, etc.)
        clause_types = ['diem', 'khoan', 'dieu']
        
        # Find which clause type exists in this reference
        for clause_type in clause_types:
            if clause_type in reference:
                clause_info = reference[clause_type]
                clause_value = clause_info.get('information', '')
                
                # Check if this value represents multiple items
                if cls._is_multiple_value(clause_value):
                    return cls._expand_clause_component(reference, clause_type, clause_value)
        
        # No expansion needed
        return [reference]
    
    @classmethod
    def _is_multiple_value(cls, value: str) -> bool:
        """
        Check if a clause value represents multiple items.
        
        Args:
            value: Clause value (e.g., "3, 4 và 5")
            
        Returns:
            True if value contains multiple items
        """
        if not isinstance(value, str):
            return False
        
        # Check for comma or "và" indicating multiple items
        return ',' in value or ' và ' in value
    
    @classmethod
    def _expand_clause_component(
        cls,
        reference: Dict,
        clause_type: str,
        multiple_value: str
    ) -> List[Dict]:
        """
        Expand a reference component that has multiple values.
        
        Args:
            reference: Original reference dictionary
            clause_type: Type of clause being expanded (khoan, dieu, etc.)
            multiple_value: The multiple value string (e.g., "3, 4 và 5")
            
        Returns:
            List of expanded references
        """
        # Extract individual numbers/letters
        items = cls.extract_numbers_list(multiple_value)
        
        if len(items) <= 1:
            # No actual multiple values
            return [reference]
        
        expanded_refs = []
        
        cursor = 0
        original_component = reference.get(clause_type, {})
        original_start = original_component.get("position_start")
        raw_start = original_component.get("_raw_position_start")

        for item in items:
            # Create a deep copy of the reference
            new_ref = deepcopy(reference)
            
            # Update the clause component with the individual value
            label = cls.CLAUSE_LABELS.get(clause_type, clause_type)
            item_text = item
            item_local_start = multiple_value.lower().find(item_text.lower(), cursor)
            if item_local_start >= 0:
                cursor = item_local_start + len(item_text)
            item = re.sub(r'^\s*' + re.escape(label) + r'\s+', '', item, flags=re.IGNORECASE)
            new_ref[clause_type]['information'] = f"{label} {item}".strip()
            if item_local_start >= 0 and original_start is not None:
                item_start = int(original_start) + item_local_start
                item_end = item_start + len(item_text)
                new_ref[clause_type]['position_start'] = item_start
                new_ref[clause_type]['position_end'] = item_end
                if raw_start is not None:
                    new_ref[clause_type]['_raw_position_start'] = int(raw_start) + item_local_start
                    new_ref[clause_type]['_raw_position_end'] = int(raw_start) + item_local_start + len(item_text) - 1
            
            expanded_refs.append(new_ref)
        
        return expanded_refs
    


def expand_multiple_references(references: List[Dict]) -> List[Dict]:
    """
    Convenience function to expand multiple references.
    
    Args:
        references: List of reference dictionaries
        
    Returns:
        Expanded list with one reference per clause number
    """
    return MultipleReferenceExpander.expand_references(references)
