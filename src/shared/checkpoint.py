"""Checkpoint management for long-running batch processing."""
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
from src.infrastructure.logging import get_logger


class CheckpointManager:
    """
    Manages checkpoints for long-running data processing tasks.
    Saves last doc ID processed so processing can resume after crashes.
    """
    
    def __init__(self, checkpoint_name: str, checkpoint_dir: str = None):
        """
        Initialize checkpoint manager.
        
        Args:
            checkpoint_name: Unique name for this checkpoint
            checkpoint_dir: Directory to store checkpoints (default: logs/checkpoints)
        """
        self.checkpoint_name = checkpoint_name
        
        if checkpoint_dir is None:
            # Use project root's logs/checkpoints directory
            project_root = Path(__file__).resolve().parents[2]
            checkpoint_dir = project_root / "logs" / "checkpoints"
        
        self.checkpoint_dir = checkpoint_dir
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        
        self.checkpoint_file = os.path.join(
            self.checkpoint_dir, 
            f"{checkpoint_name}_checkpoint.json"
        )
        
        self.logger = get_logger("CheckpointManager")
    
    def save_checkpoint(
        self, 
        last_doc_id_processed: Any, 
        total_doc_processed: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Save checkpoint with last doc ID processed and metadata.
        
        Args:
            last_doc_id_processed: Last processed document ID
            total_doc_processed: Total number of documents processed
            metadata: Additional metadata
        """
        checkpoint_data = {
            "last_doc_id_processed": last_doc_id_processed,
            "total_doc_processed": total_doc_processed,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        
        with open(self.checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(checkpoint_data, f, indent=2, ensure_ascii=False)
    
    def load_checkpoint(self) -> Optional[Dict[str, Any]]:
        """
        Load checkpoint data if exists.
        
        Returns:
            Checkpoint data dictionary or None if no checkpoint exists
        """
        if not os.path.exists(self.checkpoint_file):
            return None
        
        try:
            with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                checkpoint_data = json.load(f)
            
            self.logger.info(
                f"Checkpoint loaded: doc_id={checkpoint_data.get('last_doc_id_processed')}, "
                f"total={checkpoint_data.get('total_doc_processed')}"
            )
            return checkpoint_data
        except Exception as e:
            self.logger.error(f"Error loading checkpoint: {e}")
            return None
    
    def checkpoint_exists(self) -> bool:
        """Check if checkpoint file exists."""
        return os.path.exists(self.checkpoint_file)
    
    def clear_checkpoint(self) -> None:
        """Delete checkpoint file."""
        if os.path.exists(self.checkpoint_file):
            os.remove(self.checkpoint_file)
            self.logger.info("Checkpoint cleared")
    
    def get_checkpoint_info(self) -> str:
        """Get human-readable checkpoint info."""
        checkpoint_data = self.load_checkpoint()
        if not checkpoint_data:
            return "No checkpoint"
        
        return (
            f"Last ID: {checkpoint_data.get('last_doc_id_processed')}, "
            f"Total: {checkpoint_data.get('total_doc_processed')}, "
            f"Time: {checkpoint_data.get('timestamp')}"
        )
