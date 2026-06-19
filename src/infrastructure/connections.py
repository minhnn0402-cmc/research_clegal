"""Database connection management for MongoDB, Neo4j, and Elasticsearch."""
import os
import json
from typing import Optional, Dict, Any, List
from pymongo import MongoClient
from neo4j import GraphDatabase
from threading import Lock
from dataclasses import dataclass
from src.infrastructure.logging import get_logger


@dataclass
class MongoConfig:
    """MongoDB connection configuration."""
    name: str
    host: str
    port: int
    username: str
    password: str
    database: str
    
    @classmethod
    def from_env(cls, prefix: str):
        """Create config from environment variables with prefix."""
        port_raw = os.getenv(f'{prefix}_PORT')
        if port_raw is None or str(port_raw).strip() == "":
            raise ValueError(
                f"Missing required env var: {prefix}_PORT (e.g. {prefix}_PORT=27982)"
            )

        host = os.getenv(f'{prefix}_HOST')
        if host is None or str(host).strip() == "":
            raise ValueError(
                f"Missing required env var: {prefix}_HOST (e.g. {prefix}_HOST=10.4.0.126)"
            )

        return cls(
            name=prefix.lower(),
            host=host,
            port=int(str(port_raw).strip()),
            username=os.getenv(f'{prefix}_USER'),
            password=os.getenv(f'{prefix}_PASSWORD'),
            database=os.getenv(f'{prefix}_DATABASE')
        )


@dataclass
class Neo4jConfig:
    """Neo4j connection configuration."""
    name: str
    host: str
    port: int
    username: str
    password: str
    database: str
    max_connection_lifetime: int = 3600
    
    @classmethod
    def from_env(cls, prefix: str):
        """Create config from environment variables with prefix."""
        return cls(
            name=prefix.lower(),
            host=os.getenv(f'{prefix}_HOST'),
            port=int(os.getenv(f'{prefix}_PORT')),
            username=os.getenv(f'{prefix}_USER'),
            password=os.getenv(f'{prefix}_PASSWORD'),
            database=os.getenv(f'{prefix}_DATABASE')
        )


@dataclass
class ElasticsearchConfig:
    """Elasticsearch connection configuration."""
    name: str
    hosts: List[str]
    username: Optional[str] = None
    password: Optional[str] = None
    force_create_index: bool = False

    @property
    def endpoint(self) -> str:
        """Backward-compatible alias for first host."""
        return self.hosts[0]

    @staticmethod
    def _normalize_host(raw_host: str) -> str:
        """Normalize an Elasticsearch host string."""
        host = str(raw_host).strip()
        if not host:
            return ""
        if "://" not in host:
            host = f"http://{host}"
        return host

    @classmethod
    def _parse_hosts(cls, raw_hosts: Optional[str]) -> List[str]:
        """
        Parse ES hosts from env value.

        Supported formats:
        - Single endpoint: http://localhost:9200
        - Comma-separated: http://a:9200,http://b:9200
        - JSON list: ["http://a:9200","http://b:9200"]
        """
        if raw_hosts is None:
            return []

        raw_hosts = str(raw_hosts).strip()
        if not raw_hosts:
            return []

        parsed_hosts: List[str] = []

        # Allow JSON list for explicit multi-host configuration.
        if raw_hosts.startswith("["):
            try:
                value = json.loads(raw_hosts)
                if isinstance(value, list):
                    parsed_hosts = [str(item) for item in value]
            except json.JSONDecodeError:
                parsed_hosts = []

        # Fallback to comma-separated values.
        if not parsed_hosts:
            parsed_hosts = [part.strip() for part in raw_hosts.split(",")]

        normalized = [cls._normalize_host(host) for host in parsed_hosts]
        return [host for host in normalized if host]

    @classmethod
    def from_env(cls, prefix: str):
        """Create config from environment variables with prefix."""
        raw_hosts = os.getenv(f'{prefix}_ENDPOINTS') or os.getenv(f'{prefix}_ENDPOINT')
        hosts = cls._parse_hosts(raw_hosts)
        if not hosts:
            raise ValueError(
                f"Missing required env var: {prefix}_ENDPOINT or {prefix}_ENDPOINTS "
                "(e.g. ES_PROD_ENDPOINT=http://10.4.0.204:9252)"
            )

        return cls(
            name=prefix.lower(),
            hosts=hosts,
            username=os.getenv(f'{prefix}_USER'),
            password=os.getenv(f'{prefix}_PASSWORD')
        )


class ConnectionManager:
    """
    Singleton class to manage multiple database connections.
    Supports multiple MongoDB, Neo4j, and Elasticsearch instances.
    """
    _instance: Optional['ConnectionManager'] = None
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
        self.logger = get_logger('ConnectionManager')
        
        # Store multiple connections by name
        self._mongo_clients: Dict[str, MongoClient] = {}
        self._neo4j_drivers: Dict[str, Any] = {}
        self._es_clients: Dict[str, Any] = {}
        
        # Cache for databases and collections
        self._mongo_databases: Dict[str, Any] = {}
        self._mongo_collections: Dict[str, Any] = {}
        
        # Store configurations
        self._mongo_configs: Dict[str, MongoConfig] = {}
        self._neo4j_configs: Dict[str, Neo4jConfig] = {}
        self._es_configs: Dict[str, ElasticsearchConfig] = {}
        
        self.logger.info("ConnectionManager initialized")
    
    # ==================== MongoDB Methods ====================
    
    def register_mongo(self, config: MongoConfig):
        """Register a MongoDB configuration."""
        self._mongo_configs[config.name] = config
        self.logger.info(f"MongoDB config '{config.name}' registered")
    
    def register_mongo_from_env(self, name: str, prefix: str):
        """Register MongoDB from environment variables."""
        config = MongoConfig.from_env(prefix)
        config.name = name
        self.register_mongo(config)
    
    def get_mongo_client(self, name: str) -> MongoClient:
        """Get MongoDB client by name (lazy initialization)."""
        if name not in self._mongo_clients:
            if name not in self._mongo_configs:
                raise ValueError(f"MongoDB config '{name}' not registered")
            
            config = self._mongo_configs[name]
            self._mongo_clients[name] = MongoClient(
                host=config.host,
                port=config.port,
                username=config.username,
                password=config.password,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=10000,
                maxPoolSize=100,  # Increased from default 100
                minPoolSize=10,   # Keep connections warm
                maxIdleTimeMS=45000,
                waitQueueTimeoutMS=10000
            )
            self.logger.info(f"MongoDB client '{name}' connected with optimized pool settings")
        
        return self._mongo_clients[name]
    
    def get_mongo_database(self, client_name: str, db_name: str = None):
        """Get MongoDB database."""
        key = f"{client_name}_{db_name}"
        
        if key not in self._mongo_databases:
            client = self.get_mongo_client(client_name)
            if db_name is None:
                db_name = self._mongo_configs[client_name].database
            self._mongo_databases[key] = client[db_name]
            self.logger.info(f"Database '{db_name}' accessed on client '{client_name}'")
        
        return self._mongo_databases[key]
    
    def get_mongo_collection(self, client_name: str, collection_name: str, 
                            db_name: str = None, create_index: Optional[str] = None):
        """Get MongoDB collection with optional index creation."""
        if db_name is None:
            db_name = self._mongo_configs[client_name].database
        if db_name is None or str(db_name).strip() == "":
            raise ValueError(
                f"MongoDB database name not provided for client '{client_name}'. "
                "Pass db_name=... or set <PREFIX>_DATABASE in the environment."
            )
        
        key = f"{client_name}_{db_name}_{collection_name}"
        
        if key not in self._mongo_collections:
            database = self.get_mongo_database(client_name, db_name)
            collection = database[collection_name]
            
            if create_index:
                try:
                    collection.create_index(create_index, unique=True)
                    self.logger.info(f"Index '{create_index}' created on {collection_name}")
                except Exception as e:
                    self.logger.warning(f"Index creation failed: {e}")
            
            self._mongo_collections[key] = collection
            self.logger.info(f"Collection '{collection_name}' accessed")
        
        return self._mongo_collections[key]
    
    # ==================== Neo4j Methods ====================
    
    def register_neo4j(self, config: Neo4jConfig):
        """Register a Neo4j configuration."""
        self._neo4j_configs[config.name] = config
        self.logger.info(f"Neo4j config '{config.name}' registered")
    
    def register_neo4j_from_env(self, name: str, prefix: str):
        """Register Neo4j from environment variables."""
        config = Neo4jConfig.from_env(prefix)
        config.name = name
        self.register_neo4j(config)
    
    def get_neo4j_driver(self, name: str):
        """Get Neo4j driver by name (lazy initialization)."""
        if name not in self._neo4j_drivers:
            if name not in self._neo4j_configs:
                raise ValueError(f"Neo4j config '{name}' not registered")
            
            config = self._neo4j_configs[name]
            uri = f"neo4j://{config.host}:{config.port}"
            self._neo4j_drivers[name] = GraphDatabase.driver(
                uri=uri,
                auth=(config.username, config.password),
                max_connection_lifetime=config.max_connection_lifetime
            )
            self.logger.info(f"Neo4j driver '{name}' connected")
        
        return self._neo4j_drivers[name]
    
    def get_neo4j_session(self, name: str, database: str = None):
        """Get Neo4j session."""
        driver = self.get_neo4j_driver(name)
        if database is None:
            database = self._neo4j_configs[name].database
        return driver.session(database=database)
    
    # ==================== Elasticsearch Methods ====================
    
    def register_elasticsearch(self, config: ElasticsearchConfig):
        """Register an Elasticsearch configuration."""
        self._es_configs[config.name] = config
        self.logger.info(f"Elasticsearch config '{config.name}' registered")
    
    def register_elasticsearch_from_env(self, name: str, prefix: str):
        """Register Elasticsearch from environment variables."""
        config = ElasticsearchConfig.from_env(prefix)
        config.name = name
        self.register_elasticsearch(config)
    
    def get_es_client(self, name: str, es_client_class):
        """Get Elasticsearch client by name (lazy initialization) with custom client class."""
        if name not in self._es_clients:
            if name not in self._es_configs:
                raise ValueError(f"Elasticsearch config '{name}' not registered")
            
            config = self._es_configs[name]
            self._es_clients[name] = es_client_class(
                endpoint=config.endpoint,
                user_name=config.username,
                password=config.password,
                force_create_index=config.force_create_index
            )
            self.logger.info(f"Elasticsearch client '{name}' connected")
        
        return self._es_clients[name]
    
    def get_es_client_direct(self, name: str):
        """Get Elasticsearch client by name using stored client or basic dict-like object."""
        if name not in self._es_clients:
            if name not in self._es_configs:
                raise ValueError(f"Elasticsearch config '{name}' not registered")
            
            config = self._es_configs[name]
            
            try:
                from elasticsearch import Elasticsearch
                client_args: Dict[str, Any] = {
                    "hosts": config.hosts,
                    "verify_certs": False,
                    # Reference-resolution dispatches up to 32 concurrent ES requests
                    # via the module-level executor; the default connections_per_node
                    # of 10 forces 22 of them to queue waiting for a free HTTP
                    # connection. Sizing the pool to match the executor parallelism
                    # eliminates that head-of-line waiting on VPN-bound runs.
                    "connections_per_node": 32,
                    # gzip on the wire — large law-doc responses compress well
                    # and VPN bandwidth is the binding constraint.
                    "http_compress": True,
                    # Default is 10s — too tight for VPN-bound runs with large
                    # law-doc payloads; raise to avoid spurious timeout errors.
                    "request_timeout": 30,
                }
                if config.username or config.password:
                    client_args["basic_auth"] = (config.username, config.password)

                self._es_clients[name] = Elasticsearch(**client_args)
                self.logger.info(f"Elasticsearch client '{name}' connected using elasticsearch library")
            except ImportError:
                class SimpleESClient:
                    def __init__(self, hosts, username, password, force_create_index=False):
                        self.hosts = hosts
                        self.endpoint = hosts[0] if hosts else None
                        self.username = username
                        self.password = password
                        self.force_create_index = force_create_index
                
                self._es_clients[name] = SimpleESClient(
                    hosts=config.hosts,
                    username=config.username,
                    password=config.password,
                    force_create_index=config.force_create_index
                )
                self.logger.warning(
                    f"Elasticsearch client '{name}' created as simple config object. "
                    "Install 'elasticsearch' library for full functionality."
                )
        
        return self._es_clients[name]
    
    # ==================== Utility Methods ====================
    
    def list_connections(self):
        """List all registered connections."""
        return {
            'mongodb': list(self._mongo_configs.keys()),
            'neo4j': list(self._neo4j_configs.keys()),
            'elasticsearch': list(self._es_configs.keys())
        }
    
    def close_all(self):
        """Close all connections."""
        for name, client in self._mongo_clients.items():
            client.close()
            self.logger.info(f"MongoDB client '{name}' closed")
        
        for name, driver in self._neo4j_drivers.items():
            driver.close()
            self.logger.info(f"Neo4j driver '{name}' closed")
        
        self._mongo_clients.clear()
        self._neo4j_drivers.clear()
        self._es_clients.clear()
        self._mongo_databases.clear()
        self._mongo_collections.clear()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_all()


def get_connection_manager() -> ConnectionManager:
    """Get the singleton ConnectionManager instance."""
    return ConnectionManager()
