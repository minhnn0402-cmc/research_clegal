"""Hierarchical structure builders for legal documents."""
from typing import List, Dict, Tuple


class HierarchyBuilder: 
    """
    Builder for hierarchical clause structures.
    Builds parent-child relationships between document clauses.
    """
    CLAUSE_LEVELS = ['dieu', 'khoan', 'diem']

    @staticmethod 
    def build_hierarchy(data_parsing: List[Dict]) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
        """
        Build parent-child clause mappings from parsing data.
        
        Args:
            data_parsing: List of parsed clause dictionaries
            
        Returns:
            Tuple of (parent_to_children, child_to_parent) mappings
        """
        parent_to_children = {}
        child_to_parent = {}

        for clause in data_parsing:
            clause_key = clause.get('com_key')
            if not clause_key: 
                continue 
            parent_to_children[clause_key] = []

        for clause in data_parsing:
            clause_key = clause.get('com_key')
            if not clause_key:
                continue
            parts = clause_key.split('_') 
            if len(parts) >= 3:
                for i in range(len(parts)): 
                    if parts[i] in HierarchyBuilder.CLAUSE_LEVELS and i > 0:
                        potential_parent = '_'.join(parts[i:])
                        if potential_parent in parent_to_children: 
                            parent_to_children[potential_parent].append(clause_key)
                            child_to_parent[clause_key] = potential_parent
                        break

        return parent_to_children, child_to_parent
    

