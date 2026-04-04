"""
GraphitiClient - Abstraction layer for Graphiti + Neo4j

Replaces the Zep Cloud SDK with self-hosted Graphiti-core backed by local Neo4j.
Provides the same logical interface that MiroFish services expect:
  - Graph lifecycle (create, delete)
  - Ontology definition
  - Episode ingestion (batch and single)
  - Semantic search (edges, nodes, episodes)
  - Node/edge retrieval and pagination
  - Temporal fact tracking

Uses local abliterated LLM for entity extraction (no content filtering)
and local Ollama embeddings for semantic search.
"""

import asyncio
import uuid
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.graph_client')

# Lazy-loaded EpisodeType enum
_EpisodeType = None

def _get_episode_type():
    global _EpisodeType
    if _EpisodeType is None:
        from graphiti_core.graphiti import EpisodeType
        _EpisodeType = EpisodeType
    return _EpisodeType

# Thread-local event loop for running async Graphiti calls from sync Flask context
_local = threading.local()


def _get_event_loop():
    """Get or create an event loop for the current thread."""
    if not hasattr(_local, 'loop') or _local.loop is None or _local.loop.is_closed():
        _local.loop = asyncio.new_event_loop()
    return _local.loop


def _run_async(coro):
    """Run an async coroutine from sync context (Flask/thread)."""
    loop = _get_event_loop()
    return loop.run_until_complete(coro)


# --- Data Classes (compatible with existing MiroFish service interfaces) ---

@dataclass
class NodeInfo:
    """Graph node information, compatible with Zep's node structure."""
    uuid: str
    name: str
    labels: List[str] = field(default_factory=list)
    summary: str = ''
    attributes: Dict[str, Any] = field(default_factory=dict)
    group_id: str = ''
    created_at: Optional[datetime] = None
    name_embedding: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'uuid': self.uuid,
            'name': self.name,
            'labels': self.labels,
            'summary': self.summary,
            'attributes': self.attributes,
            'group_id': self.group_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class EdgeInfo:
    """Graph edge information, compatible with Zep's edge structure."""
    uuid: str
    name: str
    fact: str = ''
    source_node_uuid: str = ''
    target_node_uuid: str = ''
    episodes: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    group_id: str = ''
    created_at: Optional[datetime] = None
    valid_at: Optional[datetime] = None
    invalid_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'uuid': self.uuid,
            'name': self.name,
            'fact': self.fact,
            'source_node_uuid': self.source_node_uuid,
            'target_node_uuid': self.target_node_uuid,
            'episodes': self.episodes,
            'attributes': self.attributes,
            'group_id': self.group_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'valid_at': self.valid_at.isoformat() if self.valid_at else None,
            'invalid_at': self.invalid_at.isoformat() if self.invalid_at else None,
            'expired_at': self.expired_at.isoformat() if self.expired_at else None,
        }


@dataclass
class SearchResult:
    """Search result container, compatible with Zep's search results."""
    edges: List[EdgeInfo] = field(default_factory=list)
    nodes: List[NodeInfo] = field(default_factory=list)
    facts: List[str] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return len(self.edges) + len(self.nodes)


# --- Main Client ---

class GraphitiClient:
    """
    Self-hosted graph client using Graphiti-core + Neo4j.

    Replaces Zep Cloud SDK. Uses:
    - Neo4j (local) for graph storage
    - Graphiti-core for entity extraction, temporal facts, and hybrid search
    - Local abliterated LLM via LiteLLM for entity extraction
    - Local Ollama embeddings for semantic search

    Usage:
        client = GraphitiClient()
        graph_id = client.create_graph("my-project")
        client.add_episodes_batch(graph_id, ["text1", "text2"])
        results = client.search(graph_id, "query")
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """Singleton pattern - reuse the same Graphiti instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._graphiti = None
        self._init_lock = threading.Lock()
        logger.info("GraphitiClient initialized (lazy connection)")

    def _ensure_graphiti(self):
        """Lazy-initialize Graphiti connection on first use."""
        if self._graphiti is not None:
            return self._graphiti

        with self._init_lock:
            if self._graphiti is not None:
                return self._graphiti

            try:
                from graphiti_core import Graphiti
                from graphiti_core.llm_client import OpenAIClient, LLMConfig
                from graphiti_core.embedder import OpenAIEmbedder, OpenAIEmbedderConfig

                # Configure LLM for entity extraction (abliterated model)
                llm_config = LLMConfig(
                    api_key=Config.GRAPHITI_LLM_API_KEY,
                    model=Config.GRAPHITI_LLM_MODEL,
                    base_url=Config.GRAPHITI_LLM_BASE_URL,
                )
                llm_client = OpenAIClient(config=llm_config)

                # Configure embedder for semantic search (local Ollama)
                embedder_config = OpenAIEmbedderConfig(
                    api_key='ollama',  # Ollama doesn't need real key
                    embedding_model=Config.GRAPHITI_EMBEDDING_MODEL,
                    base_url=f"{Config.GRAPHITI_EMBEDDING_BASE_URL}/v1",
                    embedding_dim=Config.GRAPHITI_EMBEDDING_DIM,
                )
                embedder = OpenAIEmbedder(config=embedder_config)

                # Initialize Graphiti with Neo4j backend
                self._graphiti = Graphiti(
                    uri=Config.NEO4J_URI,
                    user=Config.NEO4J_USERNAME,
                    password=Config.NEO4J_PASSWORD,
                    llm_client=llm_client,
                    embedder=embedder,
                    store_raw_episode_content=True,
                )

                # Build indices and constraints
                _run_async(self._graphiti.build_indices_and_constraints())

                logger.info(
                    f"Graphiti connected to Neo4j at {Config.NEO4J_URI}, "
                    f"LLM={Config.GRAPHITI_LLM_MODEL}, "
                    f"Embedder={Config.GRAPHITI_EMBEDDING_MODEL}"
                )
                return self._graphiti

            except Exception as e:
                logger.error(f"Failed to initialize Graphiti: {e}")
                self._graphiti = None
                raise

    # --- Neo4j Driver ---

    async def _get_neo4j_driver(self):
        """Create an async Neo4j driver for direct Cypher queries."""
        from neo4j import AsyncGraphDatabase
        return AsyncGraphDatabase.driver(
            Config.NEO4J_URI,
            auth=(Config.NEO4J_USERNAME, Config.NEO4J_PASSWORD),
            connection_acquisition_timeout=30,
        )

    def _neo4j_query(self, query: str, **params) -> list:
        """Run a Cypher query and return records. Handles driver lifecycle."""
        async def _run():
            driver = await self._get_neo4j_driver()
            try:
                async with driver.session() as session:
                    result = await session.run(query, **params)
                    return await result.data()
            finally:
                await driver.close()
        return _run_async(_run())

    # --- Health Check ---

    def health(self) -> Dict[str, Any]:
        """Check connection health."""
        try:
            g = self._ensure_graphiti()
            return {
                'status': 'ok',
                'neo4j_uri': Config.NEO4J_URI,
                'llm_model': Config.GRAPHITI_LLM_MODEL,
                'embedding_model': Config.GRAPHITI_EMBEDDING_MODEL,
            }
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
            }

    # --- Graph Lifecycle ---

    def create_graph(self, name: str, description: str = '') -> str:
        """
        Create a new graph namespace.

        In Graphiti, graphs are isolated by group_id.
        Returns a unique graph_id (group_id in Graphiti terms).
        """
        graph_id = f"mirofish_{uuid.uuid4().hex[:12]}"
        logger.info(f"Created graph namespace: {graph_id} (name={name})")
        return graph_id

    def delete_graph(self, graph_id: str) -> bool:
        """
        Delete all nodes and edges belonging to a graph.
        Uses direct Neo4j Cypher to clean up the namespace.
        """
        try:
            async def _delete():
                driver = await self._get_neo4j_driver()
                try:
                    async with driver.session() as session:
                        await session.run(
                            "MATCH (n) WHERE n.group_id = $gid DETACH DELETE n",
                            gid=graph_id,
                        )
                finally:
                    await driver.close()

            _run_async(_delete())
            logger.info(f"Deleted graph namespace: {graph_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting graph {graph_id}: {e}")
            return False

    # --- Ontology ---

    def set_ontology(
        self,
        graph_id: str,
        entity_types: Dict[str, Dict[str, Any]],
        edge_types: Dict[str, Dict[str, Any]],
    ) -> bool:
        """
        Store ontology definition for a graph.

        Graphiti supports custom entity_types and edge_types via Pydantic models
        passed to add_episode(). We store the ontology definition and convert
        them to Pydantic models when adding episodes.

        Args:
            graph_id: The graph namespace
            entity_types: Dict of entity type name -> {attributes: {...}}
            edge_types: Dict of edge type name -> {attributes: {...}}
        """
        # Store ontology in memory (will be passed to add_episode calls)
        if not hasattr(self, '_ontologies'):
            self._ontologies = {}
        self._ontologies[graph_id] = {
            'entity_types': entity_types,
            'edge_types': edge_types,
        }
        logger.info(
            f"Set ontology for {graph_id}: "
            f"{len(entity_types)} entity types, {len(edge_types)} edge types"
        )
        return True

    def _get_pydantic_types(self, graph_id: str) -> Tuple[Optional[dict], Optional[dict]]:
        """Convert stored ontology to Pydantic models for Graphiti."""
        if not hasattr(self, '_ontologies') or graph_id not in self._ontologies:
            return None, None

        from pydantic import BaseModel, Field

        ontology = self._ontologies[graph_id]
        entity_models = {}
        edge_models = {}

        # Build entity type models
        for type_name, type_def in ontology.get('entity_types', {}).items():
            attrs = {}
            for attr_name, attr_info in type_def.get('attributes', {}).items():
                safe_name = attr_name
                # Handle reserved names
                if safe_name in ('uuid', 'name', 'summary', 'labels', 'group_id'):
                    safe_name = f'{safe_name}_attr'
                desc = attr_info if isinstance(attr_info, str) else str(attr_info)
                attrs[safe_name] = (Optional[str], Field(default=None, description=desc))

            if attrs:
                model = type(type_name, (BaseModel,), {
                    '__annotations__': {k: v[0] for k, v in attrs.items()},
                    **{k: v[1] for k, v in attrs.items()},
                })
                entity_models[type_name] = model

        # Build edge type models
        for type_name, type_def in ontology.get('edge_types', {}).items():
            attrs = {}
            for attr_name, attr_info in type_def.get('attributes', {}).items():
                desc = attr_info if isinstance(attr_info, str) else str(attr_info)
                attrs[attr_name] = (Optional[str], Field(default=None, description=desc))

            if attrs:
                model = type(type_name, (BaseModel,), {
                    '__annotations__': {k: v[0] for k, v in attrs.items()},
                    **{k: v[1] for k, v in attrs.items()},
                })
                edge_models[type_name] = model

        return (entity_models or None, edge_models or None)

    # --- Episode Ingestion ---

    def add_episodes_batch(
        self,
        graph_id: str,
        episodes: List[str],
        source_description: str = 'document',
        progress_callback=None,
    ) -> List[str]:
        """
        Add a batch of text episodes to the graph.

        Graphiti processes episodes synchronously (entity extraction happens
        during add_episode), so no polling is needed. Each episode is processed
        with the local abliterated LLM for entity extraction.

        Args:
            graph_id: The graph namespace (group_id)
            episodes: List of text strings to ingest
            source_description: Description of the data source
            progress_callback: Optional callback(current, total) for progress updates

        Returns:
            List of episode UUIDs
        """
        g = self._ensure_graphiti()
        entity_types, edge_types = self._get_pydantic_types(graph_id)

        episode_uuids = []
        total = len(episodes)

        for i, text in enumerate(episodes):
            try:
                ep_name = f"episode_{i+1}_of_{total}"
                result = _run_async(g.add_episode(
                    name=ep_name,
                    episode_body=text,
                    source_description=source_description,
                    reference_time=datetime.now(),
                    source=_get_episode_type().text,
                    group_id=graph_id,
                    entity_types=entity_types,
                    edge_types=edge_types,
                ))
                # Result is AddEpisodeResults with episode_uuid
                ep_uuid = getattr(getattr(result, 'episode', None), 'uuid', None) or str(uuid.uuid4())
                episode_uuids.append(ep_uuid)

                if progress_callback:
                    progress_callback(i + 1, total)

                logger.debug(f"Added episode {i+1}/{total} to {graph_id}")

            except Exception as e:
                logger.error(f"Error adding episode {i+1}/{total} to {graph_id}: {e}")
                # Continue with remaining episodes
                episode_uuids.append(None)

        logger.info(f"Added {len([u for u in episode_uuids if u])} of {total} episodes to {graph_id}")
        return episode_uuids

    def add_episode(
        self,
        graph_id: str,
        text: str,
        source: str = 'simulation',
    ) -> Optional[str]:
        """
        Add a single text episode (used for streaming simulation activities).

        Args:
            graph_id: The graph namespace
            text: The text content
            source: Description of the source

        Returns:
            Episode UUID or None on failure
        """
        try:
            g = self._ensure_graphiti()
            result = _run_async(g.add_episode(
                name=f"activity_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                episode_body=text,
                source_description=source,
                reference_time=datetime.now(),
                source=_get_episode_type().text,
                group_id=graph_id,
            ))
            ep_uuid = getattr(getattr(result, 'episode', None), 'uuid', None) or str(uuid.uuid4())
            return ep_uuid
        except Exception as e:
            logger.error(f"Error adding episode to {graph_id}: {e}")
            return None

    # --- Search ---

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = 'edges',
    ) -> SearchResult:
        """
        Search the graph using Graphiti's hybrid search (semantic + BM25 + graph traversal).

        Args:
            graph_id: The graph namespace
            query: Search query string
            limit: Maximum results
            scope: 'edges', 'nodes', or 'all'

        Returns:
            SearchResult with matching edges and/or nodes
        """
        try:
            g = self._ensure_graphiti()

            # Use the advanced search_ method for full control
            from graphiti_core.search.search_config import (
                SearchConfig, EdgeSearchConfig, NodeSearchConfig,
                EpisodeSearchConfig, CommunitySearchConfig,
            )
            from graphiti_core.search.search_config import (
                EdgeSearchMethod, NodeSearchMethod,
                EdgeReranker, NodeReranker,
            )

            config = SearchConfig(
                edge_config=EdgeSearchConfig(
                    search_methods=[
                        EdgeSearchMethod.bm25,
                        EdgeSearchMethod.cosine_similarity,
                    ],
                    reranker=EdgeReranker.cross_encoder,
                ),
                node_config=NodeSearchConfig(
                    search_methods=[
                        NodeSearchMethod.bm25,
                        NodeSearchMethod.cosine_similarity,
                    ],
                    reranker=NodeReranker.cross_encoder,
                ),
                limit=limit,
            )

            raw_results = _run_async(g.search_(
                query=query,
                config=config,
                group_ids=[graph_id],
            ))

            # Convert to our data classes
            result = SearchResult()

            if scope in ('edges', 'all') and raw_results.edges:
                for edge in raw_results.edges[:limit]:
                    result.edges.append(EdgeInfo(
                        uuid=edge.uuid,
                        name=edge.name,
                        fact=edge.fact,
                        source_node_uuid=edge.source_node_uuid,
                        target_node_uuid=edge.target_node_uuid,
                        episodes=edge.episodes or [],
                        attributes=edge.attributes or {},
                        group_id=edge.group_id,
                        created_at=edge.created_at,
                        valid_at=edge.valid_at,
                        invalid_at=edge.invalid_at,
                        expired_at=edge.expired_at,
                    ))
                    result.facts.append(edge.fact)

            if scope in ('nodes', 'all') and raw_results.nodes:
                for node in raw_results.nodes[:limit]:
                    result.nodes.append(NodeInfo(
                        uuid=node.uuid,
                        name=node.name,
                        labels=node.labels or [],
                        summary=node.summary,
                        attributes=node.attributes or {},
                        group_id=node.group_id,
                        created_at=node.created_at,
                    ))

            return result

        except Exception as e:
            logger.error(f"Search error in {graph_id}: {e}")
            # Fallback to local keyword search
            return self._local_search(graph_id, query, limit, scope)

    def _local_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = 'edges',
    ) -> SearchResult:
        """Fallback keyword-based search when semantic search fails."""
        result = SearchResult()
        keywords = query.lower().split()

        try:
            if scope in ('edges', 'all'):
                all_edges = self.get_all_edges(graph_id)
                scored = []
                for edge in all_edges:
                    text = f"{edge.name} {edge.fact}".lower()
                    score = sum(1 for kw in keywords if kw in text)
                    if score > 0:
                        scored.append((score, edge))
                scored.sort(key=lambda x: x[0], reverse=True)
                result.edges = [e for _, e in scored[:limit]]
                result.facts = [e.fact for e in result.edges]

            if scope in ('nodes', 'all'):
                all_nodes = self.get_all_nodes(graph_id)
                scored = []
                for node in all_nodes:
                    text = f"{node.name} {node.summary}".lower()
                    score = sum(1 for kw in keywords if kw in text)
                    if score > 0:
                        scored.append((score, node))
                scored.sort(key=lambda x: x[0], reverse=True)
                result.nodes = [n for _, n in scored[:limit]]

        except Exception as e:
            logger.error(f"Local search error in {graph_id}: {e}")

        return result

    # --- Node/Edge Retrieval ---

    def get_all_nodes(
        self,
        graph_id: str,
        max_nodes: int = 2000,
    ) -> List[NodeInfo]:
        """
        Retrieve all entity nodes for a graph.

        Uses direct Neo4j Cypher query filtered by group_id.
        """
        try:
            records = self._neo4j_query(
                """
                MATCH (n:Entity)
                WHERE n.group_id = $gid
                RETURN n
                ORDER BY n.created_at DESC
                LIMIT $limit
                """,
                gid=graph_id,
                limit=max_nodes,
            )
            nodes = []
            for rec in records:
                n = rec['n']
                nodes.append(NodeInfo(
                    uuid=n.get('uuid', ''),
                    name=n.get('name', ''),
                    labels=list(n.labels) if hasattr(n, 'labels') else n.get('labels', []),
                    summary=n.get('summary', ''),
                    attributes={k: v for k, v in n.items()
                                if k not in ('uuid', 'name', 'labels', 'summary',
                                             'group_id', 'created_at', 'name_embedding')},
                    group_id=n.get('group_id', ''),
                    created_at=n.get('created_at'),
                ))
            return nodes

        except Exception as e:
            logger.error(f"Error getting nodes for {graph_id}: {e}")
            return []

    def get_all_edges(
        self,
        graph_id: str,
        max_edges: int = 5000,
        include_temporal: bool = True,
    ) -> List[EdgeInfo]:
        """
        Retrieve all relationship edges for a graph.

        Uses direct Neo4j Cypher query filtered by group_id.
        """
        try:
            records = self._neo4j_query(
                """
                MATCH (s:Entity)-[r]->(t:Entity)
                WHERE r.group_id = $gid
                RETURN r, s.uuid AS source_uuid, t.uuid AS target_uuid,
                       type(r) AS rel_type
                ORDER BY r.created_at DESC
                LIMIT $limit
                """,
                gid=graph_id,
                limit=max_edges,
            )
            edges = []
            for rec in records:
                r = rec['r']
                edges.append(EdgeInfo(
                    uuid=r.get('uuid', ''),
                    name=r.get('name', ''),
                    fact=r.get('fact', ''),
                    source_node_uuid=rec.get('source_uuid', ''),
                    target_node_uuid=rec.get('target_uuid', ''),
                    episodes=r.get('episodes', []),
                    attributes={k: v for k, v in r.items()
                                if k not in ('uuid', 'name', 'fact', 'group_id',
                                             'created_at', 'valid_at', 'invalid_at',
                                             'expired_at', 'episodes', 'fact_embedding',
                                             'source_node_uuid', 'target_node_uuid')},
                    group_id=r.get('group_id', ''),
                    created_at=r.get('created_at'),
                    valid_at=r.get('valid_at') if include_temporal else None,
                    invalid_at=r.get('invalid_at') if include_temporal else None,
                    expired_at=r.get('expired_at') if include_temporal else None,
                ))
            return edges

        except Exception as e:
            logger.error(f"Error getting edges for {graph_id}: {e}")
            return []

    def get_node(self, node_uuid: str) -> Optional[NodeInfo]:
        """Get a single node by UUID."""
        try:
            records = self._neo4j_query(
                "MATCH (n:Entity {uuid: $uuid}) RETURN n",
                uuid=node_uuid,
            )
            record = records[0] if records else None
            if not record:
                return None

            n = record['n']
            return NodeInfo(
                uuid=n.get('uuid', ''),
                name=n.get('name', ''),
                labels=list(n.labels) if hasattr(n, 'labels') else n.get('labels', []),
                summary=n.get('summary', ''),
                attributes={k: v for k, v in n.items()
                            if k not in ('uuid', 'name', 'labels', 'summary',
                                         'group_id', 'created_at', 'name_embedding')},
                group_id=n.get('group_id', ''),
                created_at=n.get('created_at'),
            )

        except Exception as e:
            logger.error(f"Error getting node {node_uuid}: {e}")
            return None

    def get_node_edges(
        self,
        graph_id: str,
        node_uuid: str,
    ) -> List[EdgeInfo]:
        """Get all edges connected to a specific node."""
        try:
            records = self._neo4j_query(
                """
                MATCH (n:Entity {uuid: $uuid})-[r]-(m:Entity)
                WHERE r.group_id = $gid
                RETURN r,
                       CASE WHEN startNode(r) = n THEN n.uuid ELSE m.uuid END AS source_uuid,
                       CASE WHEN endNode(r) = n THEN n.uuid ELSE m.uuid END AS target_uuid,
                       CASE WHEN startNode(r) = n THEN 'outgoing' ELSE 'incoming' END AS direction
                """,
                uuid=node_uuid,
                gid=graph_id,
            )
            edges = []
            for rec in records:
                r = rec['r']
                edges.append(EdgeInfo(
                    uuid=r.get('uuid', ''),
                    name=r.get('name', ''),
                    fact=r.get('fact', ''),
                    source_node_uuid=rec.get('source_uuid', ''),
                    target_node_uuid=rec.get('target_uuid', ''),
                    episodes=r.get('episodes', []),
                    attributes={
                        **{k: v for k, v in r.items()
                           if k not in ('uuid', 'name', 'fact', 'group_id',
                                        'created_at', 'valid_at', 'invalid_at',
                                        'expired_at', 'episodes', 'fact_embedding',
                                        'source_node_uuid', 'target_node_uuid')},
                        'direction': rec.get('direction', 'unknown'),
                    },
                    group_id=r.get('group_id', ''),
                    created_at=r.get('created_at'),
                    valid_at=r.get('valid_at'),
                    invalid_at=r.get('invalid_at'),
                    expired_at=r.get('expired_at'),
                ))
            return edges

        except Exception as e:
            logger.error(f"Error getting edges for node {node_uuid}: {e}")
            return []

    # --- Utilities ---

    def get_graph_stats(self, graph_id: str) -> Dict[str, int]:
        """Get node/edge counts for a graph."""
        try:
            node_records = self._neo4j_query(
                "MATCH (n:Entity {group_id: $gid}) RETURN count(n) AS cnt",
                gid=graph_id,
            )
            edge_records = self._neo4j_query(
                "MATCH ()-[r {group_id: $gid}]->() RETURN count(r) AS cnt",
                gid=graph_id,
            )
            return {
                'nodes': node_records[0]['cnt'] if node_records else 0,
                'edges': edge_records[0]['cnt'] if edge_records else 0,
            }
        except Exception as e:
            logger.error(f"Error getting stats for {graph_id}: {e}")
            return {'nodes': 0, 'edges': 0}

    def close(self):
        """Close the Graphiti connection."""
        if self._graphiti:
            try:
                _run_async(self._graphiti.close())
            except Exception:
                pass
            self._graphiti = None
            self._initialized = False
            GraphitiClient._instance = None
            logger.info("GraphitiClient connection closed")
