"""Configuration loader for application settings and data."""
import os
import yaml
from dataclasses import dataclass, field
from typing import Optional
from threading import Lock
from pathlib import Path
from src.infrastructure.logging import get_logger
import pandas as pd


class ConfigLoader:
    """
    Singleton class to load and cache configuration data and supporting files.
    Provides centralized access to:
    - Law documents dataframe
    - Document and clause type definitions
    - Law titles for regex matching
    """
    _instance: Optional['ConfigLoader'] = None
    _lock: Lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
            
        self._initialized = True
        self.logger = get_logger('ConfigLoader')

        # Establish data paths
        self.project_root = Path(__file__).resolve().parents[2]
        self.data_dir = self.project_root / 'data'
        self.config_dir = self.project_root / 'src' / 'configs'
        
        # Cached data
        self._laws_dataframe: Optional[pd.DataFrame] = None
        self._law_titles_for_regex: Optional[list] = None
        self._doc_clause_types: Optional[dict] = None
        self._loai_van_ban_mapping: Optional[dict] = None
        self._doc_number_patterns: Optional[dict] = None
        
        self.logger.info("ConfigLoader initialized")
    
    @property
    def laws_dataframe(self) -> pd.DataFrame:
        """Load law documents CSV (lazy loading)."""
        if self._laws_dataframe is None:
            law_docs_path = self.data_dir / "law_docs.csv"
            self._laws_dataframe = pd.read_csv(law_docs_path)
            self.logger.info("Law documents CSV loaded")
        return self._laws_dataframe
    
    @property
    def law_titles_for_regex(self) -> list:
        """Prepare law documents for regex matching (lazy loading)."""
        if self._law_titles_for_regex is None:
            # Sort by length descending to match longer titles first
            self._law_titles_for_regex = sorted(
                set(self.laws_dataframe['tieu_de']),
                key=len,
                reverse=True
            )
            self.logger.info("Law titles for regexing prepared")
        return self._law_titles_for_regex
    
    @property
    def loai_van_ban_mapping(self) -> dict:
        """Load loai_van_ban key-value mapping from YAML (lazy loading)."""
        if self._loai_van_ban_mapping is None:
            path = self.config_dir / "doc_key_val_mapping.yml"
            with open(path, 'r', encoding='utf-8') as f:
                self._loai_van_ban_mapping = yaml.safe_load(f)
            self.logger.info("loai_van_ban_mapping loaded")
        return self._loai_van_ban_mapping

    @property
    def doc_number_patterns_for_regex(self) -> dict:
        """Load document number regex patterns from YAML (lazy loading)."""
        if self._doc_number_patterns is None:
            path = self.config_dir / "doc_number_patterns.yml"
            with open(path, 'r', encoding='utf-8') as f:
                self._doc_number_patterns = yaml.safe_load(f)
            assert len(self._doc_number_patterns) == 22, (
                f"doc_number_patterns.yml: expected 22 keys, got {len(self._doc_number_patterns)}"
            )
            total = sum(len(v) for v in self._doc_number_patterns.values())
            assert total == 140, (
                f"doc_number_patterns.yml: expected 140 patterns, got {total}"
            )
            self.logger.info("doc_number_patterns_for_regex loaded")
        return self._doc_number_patterns

    @property
    def doc_clause_types(self) -> dict:
        """Load document types YAML (lazy loading)."""
        if self._doc_clause_types is None:
            doc_clause_types_path = self.config_dir / "doc_and_clause_types.yml"
            with open(doc_clause_types_path,'r', encoding='utf-8') as file:
                self._doc_clause_types = yaml.load(file, Loader=yaml.FullLoader)
            self.logger.info("Document and clause types loaded")
        return self._doc_clause_types


@dataclass
class AppConfig:
    cls_database: str = field(default_factory=lambda: os.getenv('CLS_DATABASE', 'vanbanphapluat'))
    cls_collection: str = field(default_factory=lambda: os.getenv('CLS_COLLECTION', 'cls_ver2'))
    ie_database: str = field(default_factory=lambda: os.getenv('IE_DATABASE', 'ie'))
    ie_collection: str = field(default_factory=lambda: os.getenv('IE_COLLECTION', 'ie_collection'))
    max_ids_per_query: int = 50_000
    bulk_buffer_size: int = 500


def get_config_loader() -> ConfigLoader:
    """Get the singleton ConfigLoader instance."""
    return ConfigLoader()


def __getattr__(name: str):
    if name == 'loai_van_ban_mapping':
        return ConfigLoader().loai_van_ban_mapping
    if name == 'doc_number_patterns_for_regex':
        return ConfigLoader().doc_number_patterns_for_regex
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'ConfigLoader',
    'AppConfig',
    'get_config_loader',
    'loai_van_ban_mapping',
    'doc_number_patterns_for_regex'
]
