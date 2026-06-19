"""
Elasticsearch repository for legal document search operations.

This module provides the ElasticsearchRepository class which encapsulates all
Elasticsearch search operations, providing clean separation from business logic.
"""

from typing import Dict, List, Optional
from elasticsearch import Elasticsearch

from src.infrastructure.logging import get_logger


class ElasticsearchRepository:
    """
    Repository for Elasticsearch search operations.
    
    Provides clean abstraction over Elasticsearch operations for legal document search,
    handling queries, indexing, and search with proper error handling.
    """
    
    def __init__(self, es_client: Elasticsearch, logger=None):
        """
        Initialize the Elasticsearch repository.
        
        Args:
            es_client: Elasticsearch client instance
            logger: Optional logger instance (creates one if not provided)
        """
        self.es_client = es_client
        self.logger = logger or get_logger(self.__class__.__name__)
    
    def search(
        self, 
        index: str, 
        query: Dict, 
        size: int = 10,
        from_: int = 0,
        source: Optional[List[str]] = None,
        sort: Optional[List] = None
    ) -> Dict:
        """
        Search documents in Elasticsearch.
        
        Args:
            index: Index name to search
            query: Elasticsearch query DSL
            size: Number of results to return
            from_: Starting offset for pagination
            source: List of fields to include in results
            sort: Sort criteria
            
        Returns:
            Elasticsearch response dictionary with 'hits', 'total', etc.
            
        Raises:
            Exception: If search operation fails
        """
        try:
            body = {"query": query}
            if sort:
                body["sort"] = sort
            
            response = self.es_client.search(
                index=index,
                body=body,
                size=size,
                from_=from_,
                _source=source
            )
            return response
        except Exception as e:
            self.logger.error(f"Error searching Elasticsearch: {e}")
            raise
    
    def get_document(
        self, 
        index: str, 
        doc_id: str, 
        source: Optional[List[str]] = None
    ) -> Optional[Dict]:
        """
        Get a document by ID.
        
        Args:
            index: Index name
            doc_id: Document ID
            source: List of fields to include
            
        Returns:
            Document source or None if not found
            
        Raises:
            Exception: If get operation fails
        """
        try:
            response = self.es_client.get(
                index=index,
                id=doc_id,
                _source=source
            )
            return response.get('_source')
        except Exception as e:
            if e.status_code == 404:
                return None
            self.logger.error(f"Error getting document from Elasticsearch: {e}")
            raise
    
    def index_document(
        self, 
        index: str, 
        doc_id: str, 
        document: Dict
    ) -> bool:
        """
        Index a document.
        
        Args:
            index: Index name
            doc_id: Document ID
            document: Document data to index
            
        Returns:
            True if indexed successfully, False otherwise
            
        Raises:
            Exception: If indexing fails
        """
        try:
            response = self.es_client.index(
                index=index,
                id=doc_id,
                body=document
            )
            return response.get('result') in ['created', 'updated']
        except Exception as e:
            self.logger.error(f"Error indexing document: {e}")
            raise
    
    def bulk_index(
        self, 
        index: str, 
        documents: List[Dict]
    ) -> Dict:
        """
        Bulk index multiple documents.
        
        Args:
            index: Index name
            documents: List of documents with '_id' and '_source' fields
            
        Returns:
            Bulk response dictionary
            
        Raises:
            Exception: If bulk operation fails
        """
        try:
            from elasticsearch.helpers import bulk
            
            actions = [
                {
                    "_index": index,
                    "_id": doc.get('_id'),
                    "_source": doc.get('_source', doc)
                }
                for doc in documents
            ]
            
            success, failed = bulk(self.es_client, actions, raise_on_error=False)
            return {
                'success': success,
                'failed': failed
            }
        except Exception as e:
            self.logger.error(f"Error bulk indexing: {e}")
            raise
    
    def delete_document(self, index: str, doc_id: str) -> bool:
        """
        Delete a document by ID.
        
        Args:
            index: Index name
            doc_id: Document ID
            
        Returns:
            True if deleted successfully, False otherwise
            
        Raises:
            Exception: If delete operation fails
        """
        try:
            response = self.es_client.delete(
                index=index,
                id=doc_id
            )
            return response.get('result') == 'deleted'
        except Exception as e:
            if e.status_code == 404:
                return False
            self.logger.error(f"Error deleting document: {e}")
            raise
    
    def count(self, index: str, query: Optional[Dict] = None) -> int:
        """
        Count documents matching the query.
        
        Args:
            index: Index name
            query: Optional query DSL (counts all if None)
            
        Returns:
            Number of matching documents
            
        Raises:
            Exception: If count operation fails
        """
        try:
            body = {"query": query} if query else None
            response = self.es_client.count(index=index, body=body)
            return response.get('count', 0)
        except Exception as e:
            self.logger.error(f"Error counting documents: {e}")
            raise
    
    def match_query(
        self, 
        index: str, 
        field: str, 
        value: str, 
        size: int = 10
    ) -> List[Dict]:
        """
        Perform a simple match query on a field.
        
        Args:
            index: Index name
            field: Field name to search
            value: Value to search for
            size: Number of results to return
            
        Returns:
            List of matching documents
            
        Raises:
            Exception: If search fails
        """
        query = {
            "match": {
                field: value
            }
        }
        response = self.search(index, query, size=size)
        return [hit['_source'] for hit in response.get('hits', {}).get('hits', [])]
    
    def multi_match_query(
        self, 
        index: str, 
        fields: List[str], 
        value: str, 
        size: int = 10
    ) -> List[Dict]:
        """
        Perform a multi-match query across multiple fields.
        
        Args:
            index: Index name
            fields: List of field names to search
            value: Value to search for
            size: Number of results to return
            
        Returns:
            List of matching documents
            
        Raises:
            Exception: If search fails
        """
        query = {
            "multi_match": {
                "query": value,
                "fields": fields
            }
        }
        response = self.search(index, query, size=size)
        return [hit['_source'] for hit in response.get('hits', {}).get('hits', [])]
