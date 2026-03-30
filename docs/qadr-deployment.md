# Gantor MiroFish on QADR

This fork is adapted for deployment on `miro.gantor.ir` behind the QADR Caddy ingress.

## What changed

- Persian-first multilingual shell with `fa`, `en`, and `zh` UI modes
- relative `/api` frontend wiring for reverse-proxied deployment
- production frontend and backend Dockerfiles
- `compose.qadr.yaml` for Docker Compose deployment on QADR
- degraded-mode backend startup when `ZEP_API_KEY` is unavailable
- `/api/health` and `/health` backend health endpoints

## Environment

Use `.env.example` as the starting point and set:

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL_NAME`
- `SECRET_KEY`
- optional `ZEP_API_KEY`
- `ALLOW_DEGRADED_MODE=true` if you want ontology generation without ZEP-backed graph memory

Recommended QADR integration:

- `LLM_BASE_URL=http://qadr-ai-gateway-litellm:4000/v1`
- `LLM_MODEL_NAME=oa-gpt-4o-mini`

## Compose

```bash
docker compose -f compose.qadr.yaml up -d --build
```

Frontend container:

- `qadr-mirofish-frontend`

Backend container:

- `qadr-mirofish-backend`

The frontend is expected to be routed publicly via Caddy on `miro.gantor.ir`.
