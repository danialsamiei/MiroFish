# Gantor MiroFish / QEngin on QADR

This fork is adapted for deployment on:

- `https://miro.gantor.ir/` for the public MiroFish surface behind QADR basic auth
- `https://miro.gantor.ir/engine/` for the embedded QEngin dashboard
- `https://engin.gantor.ir/engine/` for the direct QEngin operator surface

## What changed

- Persian-first multilingual shell with `fa`, `en`, and `zh` UI modes
- relative `/api` frontend wiring for reverse-proxied deployment
- production frontend and backend Dockerfiles
- `compose.qadr.yaml` for Docker Compose deployment on QADR
- degraded-mode backend startup when `ZEP_API_KEY` is unavailable
- `/api/health` and `/health` backend health endpoints
- QEngin notebook runtime with:
  - run / rerun
  - live status polling
  - stage-by-stage logs
  - diagnostics view
  - HTML / Markdown / JSON exports
  - operator stop / cancel support

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

## QEngin operational smoke tests

Internal smoke from the Docker network:

```bash
docker run --rm --network fgpt_ingress \
  -v /home/saman/workspaces/gantor-mirofish/backend/scripts:/scripts \
  python:3.11-slim \
  python /scripts/smoke_test_qengin_notebook.py \
    --base-url http://qadr-mirofish-backend:5001/engine \
    --username admin \
    --password 'QADREngine@2026!' \
    --topic 'Hormuz operational smoke test' \
    --exercise-cancel
```

What this verifies:

- admin login
- quick notebook creation
- notebook run lifecycle
- log polling
- diagnostics payload
- result exports
- operator cancel / stop path

## Notes on public validation

`engin.gantor.ir` is served through the shared QADR Caddy ingress. In some operator environments,
direct egress to `5.235.208.128:443` or DNS resolution for `engin.gantor.ir` may be unreliable.
When that happens, use the internal Docker-network smoke test above to validate the runtime and
then separately confirm the public route from a browser that can reach the QADR ingress.
