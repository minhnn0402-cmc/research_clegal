"""
MongoDB repository for legal document data access.

This module provides the MongoRepository class which encapsulates all MongoDB
data access operations, providing a clean separation between data access and business logic.
"""

from typing import Dict, List, Optional, Any
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from src.infrastructure.logging import get_logger


class MongoRepository:
    """
    Repository for MongoDB data access operations.
    
    Provides clean abstraction over MongoDB operations for legal documents,
    handling queries, updates, and data retrieval with proper error handling.
    """
    
    def __init__(self, collection: Collection, logger=None):
        """
        Initialize the MongoDB repository.
        
        Args:
            collection: PyMongo collection instance
            logger: Optional logger instance (creates one if not provided)
        """
        self.collection = collection
        self.logger = logger or get_logger(self.__class__.__name__)
    
    def find_documents(
        self, 
        query: Dict, 
        projection: Optional[Dict] = None,
        skip: int = 0,
        limit: int = 0,
        sort: Optional[List] = None
    ) -> List[Dict]:
        """
        Find documents matching the query.
        
        Args:
            query: MongoDB query dictionary
            projection: Fields to include/exclude
            skip: Number of documents to skip
            limit: Maximum number of documents to return (0 = no limit)
            sort: List of (field, direction) tuples for sorting
            
        Returns:
            List of matching documents
            
        Raises:
            PyMongoError: If database operation fails
        """
        try:
            cursor = self.collection.find(query, projection)
            
            if skip > 0:
                cursor = cursor.skip(skip)
            if limit > 0:
                cursor = cursor.limit(limit)
            if sort:
                cursor = cursor.sort(sort)
            
            return list(cursor)
        except PyMongoError as e:
            self.logger.error(f"Error finding documents: {e}")
            raise
    
    def find_one(
        self, 
        query: Dict, 
        projection: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        Find a single document matching the query.
        
        Args:
            query: MongoDB query dictionary
            projection: Fields to include/exclude
            
        Returns:
            Matching document or None if not found
            
        Raises:
            PyMongoError: If database operation fails
        """
        try:
            return self.collection.find_one(query, projection)
        except PyMongoError as e:
            self.logger.error(f"Error finding document: {e}")
            raise
    
    def count_documents(self, query: Dict) -> int:
        """
        Count documents matching the query.
        
        Args:
            query: MongoDB query dictionary
            
        Returns:
            Number of matching documents
            
        Raises:
            PyMongoError: If database operation fails
        """
        try:
            return self.collection.count_documents(query)
        except PyMongoError as e:
            self.logger.error(f"Error counting documents: {e}")
            raise
    
    def update_one(
        self, 
        query: Dict, 
        update: Dict, 
        upsert: bool = False
    ) -> bool:
        """
        Update a single document.
        
        Args:
            query: MongoDB query to find document
            update: Update operations to apply
            upsert: Whether to insert if document doesn't exist
            
        Returns:
            True if document was modified or upserted, False otherwise
            
        Raises:
            PyMongoError: If database operation fails
        """
        try:
            result = self.collection.update_one(query, update, upsert=upsert)
            return result.modified_count > 0 or (upsert and result.upserted_id is not None)
        except PyMongoError as e:
            self.logger.error(f"Error updating document: {e}")
            raise
    
    def update_many(
        self, 
        query: Dict, 
        update: Dict, 
        upsert: bool = False
    ) -> int:
        """
        Update multiple documents.
        
        Args:
            query: MongoDB query to find documents
            update: Update operations to apply
            upsert: Whether to insert if no documents match
            
        Returns:
            Number of documents modified
            
        Raises:
            PyMongoError: If database operation fails
        """
        try:
            result = self.collection.update_many(query, update, upsert=upsert)
            return result.modified_count
        except PyMongoError as e:
            self.logger.error(f"Error updating documents: {e}")
            raise
    
    def insert_one(self, document: Dict) -> Any:
        """
        Insert a single document.
        
        Args:
            document: Document to insert
            
        Returns:
            Inserted document ID
            
        Raises:
            PyMongoError: If database operation fails
        """
        try:
            result = self.collection.insert_one(document)
            return result.inserted_id
        except PyMongoError as e:
            self.logger.error(f"Error inserting document: {e}")
            raise
    
    def insert_many(self, documents: List[Dict]) -> List[Any]:
        """
        Insert multiple documents.
        
        Args:
            documents: List of documents to insert
            
        Returns:
            List of inserted document IDs
            
        Raises:
            PyMongoError: If database operation fails
        """
        try:
            result = self.collection.insert_many(documents)
            return result.inserted_ids
        except PyMongoError as e:
            self.logger.error(f"Error inserting documents: {e}")
            raise
    
    def delete_one(self, query: Dict) -> bool:
        """
        Delete a single document.
        
        Args:
            query: MongoDB query to find document
            
        Returns:
            True if document was deleted, False otherwise
            
        Raises:
            PyMongoError: If database operation fails
        """
        try:
            result = self.collection.delete_one(query)
            return result.deleted_count > 0
        except PyMongoError as e:
            self.logger.error(f"Error deleting document: {e}")
            raise
    
    def delete_many(self, query: Dict) -> int:
        """
        Delete multiple documents.
        
        Args:
            query: MongoDB query to find documents
            
        Returns:
            Number of documents deleted
            
        Raises:
            PyMongoError: If database operation fails
        """
        try:
            result = self.collection.delete_many(query)
            return result.deleted_count
        except PyMongoError as e:
            self.logger.error(f"Error deleting documents: {e}")
            raise
    
    def aggregate(self, pipeline: List[Dict]) -> List[Dict]:
        """
        Execute an aggregation pipeline.
        
        Args:
            pipeline: List of aggregation pipeline stages
            
        Returns:
            List of aggregation results
            
        Raises:
            PyMongoError: If database operation fails
        """
        try:
            cursor = self.collection.aggregate(pipeline)
            return list(cursor)
        except PyMongoError as e:
            self.logger.error(f"Error executing aggregation: {e}")
            raise
    
    def distinct(self, field: str, query: Optional[Dict] = None) -> List:
        """
        Get distinct values for a field.
        
        Args:
            field: Field name to get distinct values for
            query: Optional query to filter documents
            
        Returns:
            List of distinct values
            
        Raises:
            PyMongoError: If database operation fails
        """
        try:
            if query:
                return self.collection.distinct(field, query)
            return self.collection.distinct(field)
        except PyMongoError as e:
            self.logger.error(f"Error getting distinct values: {e}")
            raise
