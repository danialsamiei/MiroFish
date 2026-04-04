"""OSINT API endpoints for intelligence data collection."""

import threading
from flask import request, jsonify
from . import osint_bp
from ..services.osint_fetcher import OSINTFetcher
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.osint')


@osint_bp.route('/osint/status', methods=['GET'])
def osint_status():
    """Check status of all OSINT sources."""
    fetcher = OSINTFetcher()
    return jsonify(fetcher.fetch_status())


@osint_bp.route('/osint/fetch', methods=['POST'])
def osint_fetch():
    """
    Fetch OSINT data from multiple sources.

    JSON body:
        query: str - search query (required for GDELT/SearxNG)
        languages: list[str] - filter languages (default: all)
        max_per_source: int - max items per source (default: 10)
        sources: list[str] - which sources to use (default: all)
        graph_id: str - if provided, ingest results into Graphiti
    """
    data = request.get_json(silent=True) or {}
    query = data.get('query')
    languages = data.get('languages')
    max_per_source = data.get('max_per_source', 10)
    sources = data.get('sources')
    graph_id = data.get('graph_id')

    fetcher = OSINTFetcher()
    items = fetcher.fetch_all(
        query=query,
        languages=languages,
        max_per_source=max_per_source,
        sources=sources,
    )

    result = {
        "items": [
            {
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "language": item.language,
                "category": item.category,
                "published": item.published,
            }
            for item in items
        ],
        "total": len(items),
    }

    # Optionally ingest into Graphiti
    if graph_id and items:
        ingest_result = fetcher.ingest_to_graphiti(items, graph_id)
        result["ingest"] = ingest_result

    return jsonify(result)


@osint_bp.route('/osint/fetch-async', methods=['POST'])
def osint_fetch_async():
    """Start async OSINT fetch (for large queries)."""
    data = request.get_json(silent=True) or {}
    query = data.get('query', 'Iran Israel')
    graph_id = data.get('graph_id')

    def _run():
        fetcher = OSINTFetcher(timeout=30)
        items = fetcher.fetch_all(query=query, max_per_source=20)
        if graph_id and items:
            fetcher.ingest_to_graphiti(items, graph_id)
        logger.info(f"Async OSINT complete: {len(items)} items")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return jsonify({"status": "started", "query": query})
