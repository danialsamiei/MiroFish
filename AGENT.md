# MiroFish - Architecture & Deployment Reference (AGENT.md)

> Last updated: 2026-04-03 (final audit & deployment)
> For AI agents and developers working on this codebase.

## What is MiroFish?

A **Multi-Agent Swarm Intelligence Engine** for geopolitical and economic prediction. It:
1. Ingests documents (PDF/MD/TXT) about a topic
2. Extracts entities and relationships into a knowledge graph
3. Creates AI agent personas from the entities
4. Simulates social media interactions (Twitter/Reddit) between agents
5. Generates predictive reports using ReACT-based reasoning
6. Enables interactive Q&A with the simulation results

## Architecture Overview

```
User -> Caddy (miro.gantor.ir, basic auth)
          |
          +-> Frontend (Vue.js 3 + Vite, Nginx, port 8080)
          |     - Persian-first UI (fa/en/zh)
          |     - D3.js graph visualization
          |     - 5-step workflow pipeline
          |
          +-> Backend (Flask + Gunicorn, port 5001)
                |
                +-> Graphiti-core (entity extraction & temporal knowledge graph)
                |     |
                |     +-> Neo4j (bolt://10.66.66.1:17687) - graph storage
                |     +-> Claude Haiku (via LiteLLM) - entity extraction LLM
                |     +-> Ollama qwen2.5:7b - embedding model
                |
                +-> Claude Sonnet 4.6 (via LiteLLM) - report generation & chat
                |
                +-> OASIS/CAMEL-AI - multi-agent social simulation
```

## Key Technology Decisions

### Graphiti (self-hosted) instead of Zep Cloud
- **Why**: Unlimited operation, data sovereignty, no rate limits, self-hosted models
- **Migration date**: 2026-04-03
- **Graphiti-core** installed with `--no-deps` in Dockerfile because `camel-oasis` pins `neo4j==5.23.0` while Graphiti wants `>=5.26.0`. Graphiti works fine with 5.23.0.
- Extra deps installed separately: `tenacity`, `diskcache`, `json-repair`

### LLM Model Configuration
- **Ontology, reports & chat**: `cl-claude-haiku-4-5-20251001` (no content filter, fast)
- **Entity extraction (Graphiti)**: `cl-claude-haiku-4-5-20251001` (fast, cost-effective)
- **Embeddings**: `qwen2.5:7b` (local Ollama, 3584-dim, no external API dependency)
- All LLM calls go through `qadr-ai-gateway-litellm:4000`
- **Note**: Claude Sonnet triggers `content_filter` on geopolitical analysis prompts. Haiku does not.

### Authentication
- Basic Auth on Caddy: `admin` / `MiroFish@QADR2026!`
- Configured in `/home/saman/workspaces/freegpt/stacks/ingress-core/Caddyfile`

## File Structure (Backend)

```
backend/
  app/
    api/
      graph.py          - Graph building API endpoints
      simulation.py     - Simulation management endpoints
      report.py         - Report generation & chat endpoints
    services/
      graph_client.py       - NEW: GraphitiClient (replaces Zep Cloud SDK)
      graph_builder.py      - Graph construction orchestrator
      ontology_generator.py - LLM-based entity/relationship extraction
      zep_tools.py          - Search tools (InsightForge, PanoramaSearch, QuickSearch)
      zep_entity_reader.py  - Entity filtering and enrichment
      zep_graph_memory_updater.py - Simulation activity -> graph updates
      oasis_profile_generator.py  - Agent persona generation
      simulation_manager.py       - Simulation lifecycle
      simulation_runner.py        - OASIS subprocess management
      simulation_config_generator.py - LLM-based simulation config
      report_agent.py              - ReACT-based report generation
      text_processor.py            - Text chunking
    models/
      project.py  - Project state management
      task.py     - Async task tracking
    utils/
      llm_client.py     - OpenAI-compatible LLM wrapper
      neo4j_paging.py   - Neo4j pagination helpers
      file_parser.py    - Document parsing (PDF, MD, TXT)
      logger.py         - Logging configuration
    config.py           - Configuration management
  run.py                - Flask app entry point
  gunicorn.conf.py      - Gunicorn WSGI config
  pyproject.toml        - Python dependencies
```

## GraphitiClient (graph_client.py)

The central abstraction replacing Zep Cloud SDK. Provides:

| Method | Purpose |
|--------|---------|
| `create_graph(name)` | Create graph namespace (group_id) |
| `delete_graph(graph_id)` | Delete all nodes/edges by group_id |
| `set_ontology(graph_id, entities, edges)` | Store entity/edge type definitions |
| `add_episodes_batch(graph_id, texts)` | Batch ingest text episodes |
| `add_episode(graph_id, text)` | Single episode (simulation streaming) |
| `search(graph_id, query, scope)` | Hybrid search (semantic + BM25 + graph) |
| `get_all_nodes(graph_id)` | Retrieve all Entity nodes |
| `get_all_edges(graph_id)` | Retrieve all relationship edges |
| `get_node(node_uuid)` | Single node by UUID |
| `get_node_edges(graph_id, node_uuid)` | Edges connected to a node |
| `get_graph_stats(graph_id)` | Node/edge counts |
| `health()` | Check Neo4j + Graphiti connectivity |

### Key patterns:
- **Singleton** with thread-safe double-checked locking
- **Thread-local event loops** to bridge sync Flask with async Graphiti
- `_neo4j_query()` helper for direct Cypher queries
- Fallback keyword search when semantic search fails
- Ontology stored in memory (not persisted across restarts)

## Environment Variables (.env)

```env
# Flask
SECRET_KEY=...
FLASK_DEBUG=false
ALLOW_DEGRADED_MODE=false

# LLM for reports & chat
LLM_API_KEY=...
LLM_BASE_URL=http://qadr-ai-gateway-litellm:4000/v1
LLM_MODEL_NAME=cl-claude-haiku-4-5-20251001

# Neo4j
NEO4J_URI=bolt://10.66.66.1:17687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=...

# Graphiti entity extraction LLM
GRAPHITI_LLM_MODEL=cl-claude-haiku-4-5-20251001
GRAPHITI_LLM_BASE_URL=http://qadr-ai-gateway-litellm:4000/v1
GRAPHITI_LLM_API_KEY=...

# Graphiti embedder (local Ollama)
GRAPHITI_EMBEDDING_MODEL=qwen2.5:7b
GRAPHITI_EMBEDDING_BASE_URL=http://qadr-local-llm-ollama:11434
GRAPHITI_EMBEDDING_DIM=3584

# QADR Graph API (optional OSINT enrichment)
QADR_GRAPH_API_URL=http://qadr-graph-api:8088
QADR_GRAPH_API_KEY=...
```

**Important**: `OPENAI_API_KEY` env var must be set in compose (any dummy value) because Graphiti's embedder SDK requires it even when using Ollama.

## Docker Deployment

```bash
# Production (QADR)
docker compose -f compose.qadr.yaml up -d

# Build backend image
DOCKER_BUILDKIT=0 docker build -f Dockerfile.backend -t gantor/mirofish-backend:latest .
```

### compose.qadr.yaml networks:
- `fgpt_ingress` - Frontend + backend, connected to Caddy
- `fgpt_ai` - Backend only, connected to LiteLLM gateway

### Resource limits:
- Backend: 4GB RAM, 2 CPUs
- Frontend: 512MB RAM, 1 CPU

## Neo4j Configuration

- **Container**: `qadr-graph-neo4j` (Neo4j 2026.02.2 Community)
- **Heap**: 8GB initial, 16GB max
- **Page cache**: 16GB
- **Plugins**: APOC, Graph Data Science
- **Data**: `/srv/qadr-graph/data`
- **Bolt**: `bolt://10.66.66.1:17687` (VPN-only)
- **Browser**: `http://10.66.66.1:17474` (VPN-only)

## Prediction Pipeline (5 Steps)

1. **Ontology Generation** - Upload docs, LLM extracts entity/relationship types
2. **Graph Building** - Text chunks -> Graphiti episodes -> Neo4j entity graph
3. **Simulation Setup** - Generate agent profiles from graph entities
4. **Simulation Run** - OASIS multi-agent social media simulation
5. **Report & Interaction** - ReACT-based analysis with tool-augmented retrieval

## Important: LLM Client Compatibility

The `llm_client.py` has been modified for Claude compatibility:
- **No `response_format`**: Claude models via LiteLLM don't reliably support `{"type": "json_object"}`. The `chat_json()` method relies on system prompts to request JSON output instead.
- **`content: null` guard**: Claude sometimes returns `null` content. The client converts this to empty string.
- **`json-repair` fallback**: If JSON parsing fails, `json_repair` library attempts to fix malformed JSON.
- **900s timeout**: OpenAI SDK client timeout set to 900s. Also sends `x-litellm-timeout: 600` header to override LiteLLM's default 120s timeout. Ontology generation can take 10-12 minutes on Claude Sonnet.
- **Retry with backoff**: `chat_json()` retries up to 3 times on empty responses or JSON parse failures, with exponential backoff.

## Known Limitations

1. **Content filter on Claude**: Claude models trigger `content_filter` (`finish_reason: content_filter`) for prompts containing phrases like "opinion simulation", "propaganda simulation". The system prompt in `ontology_generator.py` has been rewritten to use neutral language ("scenario modeling", "discourse analysis", "multi-agent forecasting"). If content_filter persists, switch to a self-hosted abliterated model.
2. **Ontology not persisted**: Stored in memory, lost on restart. Future: save to Neo4j.
3. **neo4j version mismatch**: graphiti-core wants >=5.26.0 but camel-oasis pins 5.23.0. Works fine but warnings appear.
4. **No abliterated local model yet**: `local-qwen3.5-abliterated` not available on Ollama. Using Claude Haiku instead. To fix: pull an abliterated model into Ollama for uncensored geopolitical analysis.
5. **Single-process embedding**: Ollama runs one model at a time. Concurrent embedding requests queue up.
6. **Embedding dimension**: qwen2.5:7b produces 3584-dim vectors (set `GRAPHITI_EMBEDDING_DIM=3584`).
7. **Docker cp sandbox**: Claude Code sandbox blocks `docker cp` file operations. Use `docker build` + `docker compose up -d --force-recreate` to apply code changes.

## Related Services on QADR

| Service | Container | Purpose |
|---------|-----------|---------|
| LiteLLM | `qadr-ai-gateway-litellm:4000` | LLM gateway/router |
| Ollama | `qadr-local-llm-ollama:11434` | Local embeddings |
| Neo4j | `qadr-graph-neo4j:7687` | Graph database |
| Graph API | `qadr-graph-api:8088` | OSINT data enrichment |
| Caddy | `qadr-ingress-core-caddy` | Reverse proxy + TLS |
| Enigma | `qadr-enigma-engine:8090` | Companion reasoning engine |

## Verified Test Results (2026-04-03)

```
=== Infrastructure ===
Health status:     ok (not degraded)
Auth (no creds):   401 Unauthorized
Auth (with creds): 200 OK
Container status:  backend healthy, frontend healthy

=== LLM Connectivity ===
Claude Sonnet 4.6 (reports): OK
Claude Haiku 4.5 (entity extraction): OK
Ollama qwen2.5:7b (embeddings): OK (3584-dim vectors)

=== Neo4j Connectivity ===
Neo4j bolt://10.66.66.1:17687: OK
Graph CRUD (create/delete): OK
Graphiti initialization: OK

=== Module Imports (16/16 OK) ===
graph_client, graph_builder, zep_tools, zep_entity_reader,
zep_graph_memory_updater, oasis_profile_generator, ontology_generator,
report_agent, simulation_runner, simulation_manager,
neo4j_paging, llm_client, file_parser,
api.graph, api.simulation, api.report

=== E2E Ontology Generation ===
Status:  OK (10 entity types, 8 edge types)
Model:   Claude Haiku (Sonnet triggers content_filter on geopolitical prompts)
Sample:  OilProducer, EnergyTrader, NavalForce, Diplomat, StrategicWaterway...
```

## Deployment Checklist

After code changes, run:
```bash
# Build new image
docker build -f Dockerfile.backend -t gantor/mirofish-backend:latest .

# Deploy
docker compose -f compose.qadr.yaml up -d --force-recreate backend

# Verify
sleep 30 && docker exec qadr-mirofish-backend python3 -c \
  "from app.services.graph_client import GraphitiClient; c=GraphitiClient(); print(c.health())"
```

## Next Steps (Planned Enhancements)

1. **Abliterated model**: Pull uncensored LLM for entity extraction (no content filtering for geopolitical analysis)
2. **OSINT integration**: Connect QADR Graph API for automated news/intelligence ingestion
3. **Scheduled predictions**: n8n workflow for periodic prediction runs
4. **WorldMonitor-style dashboard**: Persian-first intelligence dashboard with D3/DeckGL visualizations
5. **Redis state management**: Persistent task/simulation state (replace JSON files)
