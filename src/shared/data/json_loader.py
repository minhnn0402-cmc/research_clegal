"""JSON file loading utilities."""
import os 
import json 


def load_doc_ids(file_path: str):
    """
    Load document IDs from a JSON file.
    
    Args:
        file_path: Path to JSON file containing document IDs
        
    Returns:
        List of document IDs (as integers if possible)
        
    Raises:
        FileNotFoundError: If file doesn't exist
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"IDs file not found: {file_path}")
    
    with open(file_path, "r", encoding="utf-8") as f:
        ids = json.load(f)
    
    # Ensure ints (some files may contain strings)
    try:
        ids = [int(x) for x in ids]
    except Exception:
        # keep original if conversion fails
        pass
    
    return ids
