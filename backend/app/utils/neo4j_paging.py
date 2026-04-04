"""
Neo4j Pagination Utilities

Replaces zep_paging.py with direct Neo4j Cypher queries.
Provides paginated node and edge retrieval for MiroFish graphs.
"""

import time
from typing import List, Optional
from ..utils.logger import get_logger
from ..services.graph_client import GraphitiClient, NodeInfo, EdgeInfo

logger = get_logger('mirofish.neo4j_paging')


def get_all_nodes_paginated(
    graph_id: str,
    page_size: int = 100,
    max_nodes: int = 2000,
) -> List[NodeInfo]:
    """
    Retrieve all entity nodes for a graph.

    Unlike Zep's cursor-based pagination, we use Graphiti/Neo4j direct query
    which returns all results at once (with a max limit).

    Args:
        graph_id: The graph namespace (group_id)
        page_size: Not used (kept for interface compatibility)
        max_nodes: Maximum number of nodes to retrieve

    Returns:
        List of NodeInfo objects
    """
    client = GraphitiClient()
    try:
        nodes = client.get_all_nodes(graph_id, max_nodes=max_nodes)
        logger.info(f"Retrieved {len(nodes)} nodes for graph {graph_id}")
        return nodes
    except Exception as e:
        logger.error(f"Error retrieving nodes for {graph_id}: {e}")
        return []


def get_all_edges_paginated(
    graph_id: str,
    page_size: int = 100,
    max_edges: int = 5000,
) -> List[EdgeInfo]:
    """
    Retrieve all relationship edges for a graph.

    Args:
        graph_id: The graph namespace (group_id)
        page_size: Not used (kept for interface compatibility)
        max_edges: Maximum number of edges to retrieve

    Returns:
        List of EdgeInfo objects
    """
    client = GraphitiClient()
    try:
        edges = client.get_all_edges(graph_id, max_edges=max_edges)
        logger.info(f"Retrieved {len(edges)} edges for graph {graph_id}")
        return edges
    except Exception as e:
        logger.error(f"Error retrieving edges for {graph_id}: {e}")
        return []
