"""
QEngin Dashboard API.
Notebook management, AI wizard, and authentication for the QEngin surface.
"""

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from flask import Response, request, jsonify, send_from_directory
from . import engine_bp
from ..config import Config
from ..utils.logger import get_logger
from ..services.notebook_runner import (
    build_diagnostics_payload,
    build_status_payload,
    export_payload,
    get_notebook_logs,
    load_notebook,
    notebook_path,
    request_notebook_cancel,
    start_notebook_run,
)

logger = get_logger('mirofish.engine')

ENGINE_BRAND = "QEngin"
ENGINE_EXPANSION = "Enhanced Network for Generative Intelligence & Navigation"
_WIZARD_CACHE = {}

# ─── Auth ──────────────────────────────────────────────────────────────
ENGINE_USERS = {
    "admin": {
        "password_hash": hashlib.sha256(b"QADREngine@2026!").hexdigest(),
        "role": "admin",
    },
}

# Use HMAC-signed tokens instead of server-side sessions (works across Gunicorn workers)
_TOKEN_SECRET = Config.SECRET_KEY or "mirofish-engine-secret"


def _make_token(username, role):
    """Create an HMAC-signed token."""
    expires = int(time.time()) + 86400 * 7
    payload = f"{username}:{role}:{expires}"
    sig = hashlib.sha256(f"{payload}:{_TOKEN_SECRET}".encode()).hexdigest()[:16]
    return f"{payload}:{sig}"


def _verify_token(token):
    """Verify HMAC-signed token."""
    try:
        parts = token.rsplit(":", 1)
        if len(parts) != 2:
            return None
        payload, sig = parts
        expected_sig = hashlib.sha256(f"{payload}:{_TOKEN_SECRET}".encode()).hexdigest()[:16]
        if sig != expected_sig:
            return None
        username, role, expires_str = payload.split(":")
        if int(expires_str) < time.time():
            return None
        return {"user": username, "role": role, "expires": int(expires_str)}
    except Exception:
        return None


def _check_auth():
    """Check Bearer token or session cookie."""
    token = None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    if not token:
        token = request.cookies.get("engine_token")
    if not token:
        return None
    return _verify_token(token)


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        sess = _check_auth()
        if not sess:
            return jsonify({"error": "Unauthorized"}), 401
        request.user = sess
        return f(*args, **kwargs)
    return decorated


@engine_bp.route('/auth/login', methods=['POST'])
def engine_login():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '')
    password = data.get('password', '')
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    user = ENGINE_USERS.get(username)
    if not user or user["password_hash"] != pw_hash:
        return jsonify({"error": "Invalid credentials"}), 401
    token = _make_token(username, user["role"])
    resp = jsonify({"token": token, "user": username, "role": user["role"]})
    resp.set_cookie("engine_token", token, max_age=86400 * 7, httponly=True, samesite="Lax")
    return resp


@engine_bp.route('/auth/me', methods=['GET'])
@require_auth
def engine_me():
    return jsonify(request.user)


# ─── Notebooks ─────────────────────────────────────────────────────────
NOTEBOOKS_DIR = os.path.join(os.path.dirname(__file__), '../../uploads/notebooks')
os.makedirs(NOTEBOOKS_DIR, exist_ok=True)


def _nb_path(nb_id):
    return os.path.join(NOTEBOOKS_DIR, f"{nb_id}.json")


def _load_notebook_or_404(nb_id):
    path = notebook_path(NOTEBOOKS_DIR, nb_id)
    if not os.path.exists(path):
        return None, (jsonify({"error": "Not found"}), 404)
    return load_notebook(NOTEBOOKS_DIR, nb_id), None


def _list_notebooks():
    nbs = []
    if os.path.isdir(NOTEBOOKS_DIR):
        for f in os.listdir(NOTEBOOKS_DIR):
            if f.endswith('.json'):
                try:
                    with open(os.path.join(NOTEBOOKS_DIR, f)) as fh:
                        nb = json.load(fh)
                        status_payload = build_status_payload(nb)
                        nbs.append({
                            "id": nb["id"],
                            "title": nb.get("title", "Untitled"),
                            "status": nb.get("status", "draft"),
                            "created": nb.get("created"),
                            "updated": nb.get("updated"),
                            "topic": nb.get("config", {}).get("topic", ""),
                            "progress": status_payload.get("progress", 0),
                            "current_stage": status_payload.get("current_stage"),
                            "results_ready": status_payload.get("results_ready", False),
                            "logs_count": status_payload.get("logs_count", 0),
                        })
                except Exception:
                    pass
    nbs.sort(key=lambda x: x.get("updated", ""), reverse=True)
    return nbs


def _deepcopy_json(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def _wizard_cache_key(topic):
    normalized = " ".join((topic or "").strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _wizard_cache_get(topic):
    cache_key = _wizard_cache_key(topic)
    cached = _WIZARD_CACHE.get(cache_key)
    if not cached:
        return None
    if cached["expires_at"] <= time.time():
        _WIZARD_CACHE.pop(cache_key, None)
        return None
    return _deepcopy_json(cached["value"])


def _wizard_cache_put(topic, suggestion):
    ttl = max(60, Config.QENGIN_WIZARD_CACHE_TTL_SECONDS)
    _WIZARD_CACHE[_wizard_cache_key(topic)] = {
        "expires_at": time.time() + ttl,
        "value": _deepcopy_json(suggestion),
    }
    return suggestion


def _detect_languages(topic):
    langs = []
    text = topic or ""
    if any('\u0600' <= ch <= '\u06ff' for ch in text):
        langs.append("fa")
    if any('\u0590' <= ch <= '\u05ff' for ch in text):
        langs.append("he")
    if any('\u4e00' <= ch <= '\u9fff' for ch in text):
        langs.append("zh")
    if any('\u0400' <= ch <= '\u04ff' for ch in text):
        langs.append("ru")
    if not langs or all(ord(ch) < 128 for ch in text if ch.isalpha()):
        langs.append("en")
    if "en" not in langs:
        langs.append("en")
    return langs[:4]


def _build_quick_notebook_fallback(topic):
    topic_text = (topic or "").strip() or "Strategic outlook"
    title = " ".join(part.capitalize() for part in topic_text.split()) or topic_text
    default_hypotheses = [
        {
            "statement": f"Policy and diplomatic shifts will materially influence {topic_text}.",
            "weight": 0.45,
            "category": "diplomatic",
        },
        {
            "statement": f"Economic and infrastructure signals will shape the near-term outlook for {topic_text}.",
            "weight": 0.35,
            "category": "economic",
        },
        {
            "statement": f"Security and operational disruptions could change the trajectory of {topic_text}.",
            "weight": 0.20,
            "category": "military",
        },
    ]
    return {
        "title": title,
        "topic": topic_text,
        "languages": _detect_languages(topic_text),
        "actors": [],
        "hypotheses": default_hypotheses,
        "osint_queries": [
            topic_text,
            f"{topic_text} forecast",
            f"{topic_text} risks",
        ],
        "timeframe": "3 months",
        "engines": ["mirofish", "ensemble"],
        "risk_categories": ["diplomatic", "economic", "military"],
    }


def _normalize_wizard_suggestion(topic, suggestion):
    normalized = _build_quick_notebook_fallback(topic)
    if not isinstance(suggestion, dict):
        return normalized

    for key, fallback_value in normalized.items():
        incoming = suggestion.get(key)
        if incoming in (None, "", []):
            continue
        normalized[key] = incoming

    if not isinstance(normalized.get("languages"), list) or not normalized["languages"]:
        normalized["languages"] = _detect_languages(topic)
    if not isinstance(normalized.get("actors"), list):
        normalized["actors"] = []
    if not isinstance(normalized.get("hypotheses"), list):
        normalized["hypotheses"] = _build_quick_notebook_fallback(topic)["hypotheses"]
    if not isinstance(normalized.get("osint_queries"), list) or not normalized["osint_queries"]:
        normalized["osint_queries"] = _build_quick_notebook_fallback(topic)["osint_queries"]
    if not isinstance(normalized.get("engines"), list) or not normalized["engines"]:
        normalized["engines"] = ["mirofish", "ensemble"]
    if not isinstance(normalized.get("risk_categories"), list) or not normalized["risk_categories"]:
        normalized["risk_categories"] = ["diplomatic", "economic", "military"]

    return normalized


def _apply_notebook_overrides(base_config, overrides):
    config = dict(base_config or {})
    data = overrides or {}

    for key in ("topic", "timeframe", "analysis_mode", "analysis_depth", "llm_model", "operator_notes"):
        value = data.get(key)
        if value not in (None, ""):
            config[key] = value

    source_limit = data.get("source_limit")
    if source_limit not in (None, ""):
        try:
            config["source_limit"] = max(3, min(20, int(source_limit)))
        except (TypeError, ValueError):
            pass

    export_formats = data.get("export_formats")
    if isinstance(export_formats, list) and export_formats:
        config["export_formats"] = [str(item).strip().lower() for item in export_formats if str(item).strip()]

    return config


def _wizard_prompt_messages(topic):
    compact_schema = {
        "title": "short notebook title",
        "topic": "refined topic",
        "languages": ["en", "fa"],
        "actors": ["actor 1", "actor 2"],
        "hypotheses": [
            {"statement": "hypothesis", "weight": 0.5, "category": "diplomatic"}
        ],
        "osint_queries": ["query 1", "query 2"],
        "timeframe": "3 months",
        "engines": ["mirofish", "ensemble"],
        "risk_categories": ["diplomatic", "economic"],
    }
    return [
        {
            "role": "system",
            "content": (
                f"You are the {ENGINE_BRAND} wizard for {ENGINE_EXPANSION}. "
                "Return compact JSON only. Keep output concise and production-ready. "
                "Prefer 2-4 hypotheses, 3-5 OSINT queries, and 2-6 actors."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Topic: {topic}\n"
                f"Return JSON with this shape only:\n{json.dumps(compact_schema, ensure_ascii=False)}"
            ),
        },
    ]


def _get_wizard_suggestion(topic):
    cached = _wizard_cache_get(topic)
    if cached:
        return cached, True, "cache"

    from ..utils.llm_client import LLMClient
    llm = LLMClient(model=Config.QENGIN_WIZARD_MODEL)

    try:
        suggestion = llm.chat_json(
            _wizard_prompt_messages(topic),
            temperature=0.2,
            max_tokens=Config.QENGIN_WIZARD_MAX_TOKENS,
            max_retries=Config.QENGIN_WIZARD_MAX_RETRIES,
        )
        suggestion = _normalize_wizard_suggestion(topic, suggestion)
        _wizard_cache_put(topic, suggestion)
        return suggestion, False, "llm"
    except Exception as exc:
        logger.warning(f"QEngin wizard fallback for topic '{topic}': {exc}")
        fallback = _build_quick_notebook_fallback(topic)
        _wizard_cache_put(topic, fallback)
        return fallback, False, "fallback"


@engine_bp.route('/notebooks', methods=['GET'])
@require_auth
def list_notebooks():
    return jsonify({"notebooks": _list_notebooks()})


@engine_bp.route('/notebooks', methods=['POST'])
@require_auth
def create_notebook():
    data = request.get_json(silent=True) or {}
    nb_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    notebook = {
        "id": nb_id,
        "title": data.get("title", "New Prediction"),
        "status": "draft",
        "created": now,
        "updated": now,
        "owner": request.user["user"],
        "config": _apply_notebook_overrides(data.get("config", {}), data),
        "steps": [],
        "results": {},
    }
    with open(_nb_path(nb_id), 'w') as f:
        json.dump(notebook, f, ensure_ascii=False, indent=2)
    return jsonify(notebook), 201


@engine_bp.route('/notebooks/<nb_id>', methods=['GET'])
@require_auth
def get_notebook(nb_id):
    notebook, error = _load_notebook_or_404(nb_id)
    if error:
        return error
    return jsonify(notebook)


@engine_bp.route('/notebooks/<nb_id>', methods=['PUT'])
@require_auth
def update_notebook(nb_id):
    path = _nb_path(nb_id)
    if not os.path.exists(path):
        return jsonify({"error": "Not found"}), 404
    with open(path) as f:
        nb = json.load(f)
    data = request.get_json(silent=True) or {}
    for key in ['title', 'config', 'steps', 'results', 'status']:
        if key in data:
            nb[key] = data[key]
    nb["updated"] = datetime.now(timezone.utc).isoformat()
    with open(path, 'w') as f:
        json.dump(nb, f, ensure_ascii=False, indent=2)
    return jsonify(nb)


@engine_bp.route('/notebooks/<nb_id>', methods=['DELETE'])
@require_auth
def delete_notebook(nb_id):
    path = _nb_path(nb_id)
    if os.path.exists(path):
        os.remove(path)
    return jsonify({"deleted": nb_id})


@engine_bp.route('/notebooks/<nb_id>/run', methods=['POST'])
@require_auth
def run_notebook(nb_id):
    notebook, error = _load_notebook_or_404(nb_id)
    if error:
        return error

    notebook, started = start_notebook_run(NOTEBOOKS_DIR, nb_id)
    payload = build_status_payload(notebook)
    payload["started"] = started
    payload["message"] = (
        "Notebook execution started."
        if started
        else "Notebook execution is already in progress."
    )
    return jsonify(payload), 202 if started else 200


@engine_bp.route('/notebooks/<nb_id>/cancel', methods=['POST'])
@require_auth
def cancel_notebook(nb_id):
    notebook, error = _load_notebook_or_404(nb_id)
    if error:
        return error

    notebook, cancelled = request_notebook_cancel(NOTEBOOKS_DIR, nb_id)
    payload = build_status_payload(notebook)
    payload["cancel_requested"] = notebook.get("execution", {}).get("cancel_requested", False)
    payload["cancelled"] = cancelled
    payload["message"] = (
        "Notebook cancellation requested."
        if cancelled
        else "Notebook is not running or cancellation was already requested."
    )
    return jsonify(payload), 202 if cancelled else 200


@engine_bp.route('/notebooks/<nb_id>/status', methods=['GET'])
@require_auth
def notebook_status(nb_id):
    notebook, error = _load_notebook_or_404(nb_id)
    if error:
        return error
    return jsonify(build_status_payload(notebook))


@engine_bp.route('/notebooks/<nb_id>/logs', methods=['GET'])
@require_auth
def notebook_logs(nb_id):
    notebook, error = _load_notebook_or_404(nb_id)
    if error:
        return error
    try:
        from_index = int(request.args.get("from", "0"))
    except ValueError:
        from_index = 0
    from_index = max(from_index, 0)
    payload = get_notebook_logs(notebook, from_index=from_index)
    payload["status"] = notebook.get("status", "draft")
    payload["current_stage"] = notebook.get("execution", {}).get("current_stage")
    payload["progress"] = notebook.get("execution", {}).get("progress", 0)
    return jsonify(payload)


@engine_bp.route('/notebooks/<nb_id>/results', methods=['GET'])
@require_auth
def notebook_results(nb_id):
    notebook, error = _load_notebook_or_404(nb_id)
    if error:
        return error
    if not notebook.get("results"):
        return jsonify({
            "status": notebook.get("status", "draft"),
            "results_ready": False,
            "message": "Results are not ready yet.",
            "execution": notebook.get("execution", {}),
        }), 202
    return jsonify({
        "status": notebook.get("status", "draft"),
        "results_ready": True,
        "result": notebook.get("results", {}),
        "exports": notebook.get("exports", {}),
        "execution": notebook.get("execution", {}),
    })


@engine_bp.route('/notebooks/<nb_id>/diagnostics', methods=['GET'])
@require_auth
def notebook_diagnostics(nb_id):
    notebook, error = _load_notebook_or_404(nb_id)
    if error:
        return error
    return jsonify(build_diagnostics_payload(notebook))


@engine_bp.route('/notebooks/<nb_id>/export', methods=['GET'])
@require_auth
def notebook_export(nb_id):
    notebook, error = _load_notebook_or_404(nb_id)
    if error:
        return error
    fmt = (request.args.get("format") or "json").strip().lower()
    try:
        body, content_type = export_payload(notebook, fmt)
    except FileNotFoundError:
        return jsonify({"error": "Results are not ready yet."}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    ext = {"json": "json", "markdown": "md", "html": "html"}.get(fmt, fmt)
    filename = f"{nb_id}-result.{ext}"
    return Response(
        body,
        content_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


# ─── AI Wizard ─────────────────────────────────────────────────────────
@engine_bp.route('/wizard/suggest', methods=['POST'])
@require_auth
def wizard_suggest():
    """AI-powered configuration wizard. Suggests settings based on topic."""
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "")
    if not topic:
        return jsonify({"error": "topic required"}), 400
    started_at = time.perf_counter()
    suggestion, cached, source = _get_wizard_suggestion(topic)
    latency_ms = round((time.perf_counter() - started_at) * 1000)
    logger.info(
        "QEngin wizard/suggest topic=%s source=%s cached=%s latency_ms=%s",
        topic[:80],
        source,
        cached,
        latency_ms,
    )
    return jsonify({
        "suggestion": suggestion,
        "cached": cached,
        "source": source,
        "latency_ms": latency_ms,
    })


@engine_bp.route('/wizard/quick-notebook', methods=['POST'])
@require_auth
def wizard_quick_notebook():
    """One-click: enter topic -> get fully configured notebook."""
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "")
    if not topic:
        return jsonify({"error": "topic required"}), 400
    started_at = time.perf_counter()
    suggestion, cached, source = _get_wizard_suggestion(topic)

    # Step 2: Create notebook with suggestion
    nb_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    notebook = {
        "id": nb_id,
        "title": suggestion.get("title", topic),
        "status": "configured",
        "created": now,
        "updated": now,
        "owner": request.user["user"],
        "config": _apply_notebook_overrides(suggestion, data),
        "steps": [],
        "results": {},
    }
    with open(_nb_path(nb_id), 'w') as f:
        json.dump(notebook, f, ensure_ascii=False, indent=2)

    latency_ms = round((time.perf_counter() - started_at) * 1000)
    logger.info(
        "QEngin wizard/quick-notebook topic=%s source=%s cached=%s latency_ms=%s notebook_id=%s",
        topic[:80],
        source,
        cached,
        latency_ms,
        nb_id,
    )
    return jsonify({
        "notebook": notebook,
        "suggestion": suggestion,
        "cached": cached,
        "source": source,
        "latency_ms": latency_ms,
    }), 201


# ─── System Status ─────────────────────────────────────────────────────
@engine_bp.route('/system/status', methods=['GET'])
@require_auth
def system_status():
    """Full system health check."""
    status = {"timestamp": datetime.now(timezone.utc).isoformat()}

    # Graphiti
    try:
        from ..services.graph_client import GraphitiClient
        h = GraphitiClient().health()
        status["graphiti"] = h
    except Exception as e:
        status["graphiti"] = {"status": "error", "error": str(e)[:100]}

    # LLM
    try:
        from ..utils.llm_client import LLMClient
        LLMClient().chat([{"role": "user", "content": "OK"}], max_tokens=3)
        status["llm"] = {"status": "ok", "model": Config.LLM_MODEL_NAME}
    except Exception as e:
        status["llm"] = {"status": "error", "error": str(e)[:100]}

    # OSINT
    try:
        from ..services.osint_fetcher import OSINTFetcher
        s = OSINTFetcher().fetch_status()
        status["osint"] = {"status": "ok", "feeds": s["total_rss_feeds"], "languages": len(s["languages"])}
    except Exception as e:
        status["osint"] = {"status": "error", "error": str(e)[:100]}

    # Ensemble
    try:
        from ..services.ensemble_voter import DEFAULT_ENSEMBLE_MODELS
        status["ensemble"] = {"status": "ok", "models": list(DEFAULT_ENSEMBLE_MODELS.keys())}
    except Exception as e:
        status["ensemble"] = {"status": "error", "error": str(e)[:100]}

    # AnalystCrew
    try:
        from ..services.analyst_crew import AnalystCrew
        c = AnalystCrew()
        status["analyst_crew"] = {"status": "ok", "roles": list(c.roles.keys())}
    except Exception as e:
        status["analyst_crew"] = {"status": "error", "error": str(e)[:100]}

    # Notebooks
    status["notebooks"] = {"count": len(_list_notebooks())}

    return jsonify(status)


# ─── Dashboard SPA ─────────────────────────────────────────────────────
DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), '../../dashboard')


@engine_bp.route('/', defaults={'path': ''})
@engine_bp.route('/<path:path>')
def serve_dashboard(path):
    """Serve the SPA dashboard. Falls back to index.html for client-side routing."""
    if path and os.path.exists(os.path.join(DASHBOARD_DIR, path)):
        return send_from_directory(DASHBOARD_DIR, path)
    return send_from_directory(DASHBOARD_DIR, 'index.html')
