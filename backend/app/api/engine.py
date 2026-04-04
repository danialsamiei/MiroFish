"""
QADR-Engine Dashboard API.
Notebook management, AI wizard, and authentication for engin.gantor.ir.
"""

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from flask import request, jsonify, send_from_directory
from . import engine_bp
from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.engine')

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


def _list_notebooks():
    nbs = []
    if os.path.isdir(NOTEBOOKS_DIR):
        for f in os.listdir(NOTEBOOKS_DIR):
            if f.endswith('.json'):
                try:
                    with open(os.path.join(NOTEBOOKS_DIR, f)) as fh:
                        nb = json.load(fh)
                        nbs.append({
                            "id": nb["id"],
                            "title": nb.get("title", "Untitled"),
                            "status": nb.get("status", "draft"),
                            "created": nb.get("created"),
                            "updated": nb.get("updated"),
                            "topic": nb.get("config", {}).get("topic", ""),
                        })
                except Exception:
                    pass
    nbs.sort(key=lambda x: x.get("updated", ""), reverse=True)
    return nbs


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
        "config": data.get("config", {}),
        "steps": [],
        "results": {},
    }
    with open(_nb_path(nb_id), 'w') as f:
        json.dump(notebook, f, ensure_ascii=False, indent=2)
    return jsonify(notebook), 201


@engine_bp.route('/notebooks/<nb_id>', methods=['GET'])
@require_auth
def get_notebook(nb_id):
    path = _nb_path(nb_id)
    if not os.path.exists(path):
        return jsonify({"error": "Not found"}), 404
    with open(path) as f:
        return jsonify(json.load(f))


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


# ─── AI Wizard ─────────────────────────────────────────────────────────
@engine_bp.route('/wizard/suggest', methods=['POST'])
@require_auth
def wizard_suggest():
    """AI-powered configuration wizard. Suggests settings based on topic."""
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "")
    if not topic:
        return jsonify({"error": "topic required"}), 400

    from ..utils.llm_client import LLMClient
    llm = LLMClient()

    prompt = f"""You are QADR-Engine configuration wizard. The user wants to create a prediction notebook about:

Topic: {topic}

Suggest a complete configuration as JSON:
{{
  "title": "Professional title for this prediction notebook (in the language of the topic)",
  "topic": "Concise topic description",
  "languages": ["list of relevant languages for data collection, e.g. en, fa, ar, he"],
  "actors": ["list of key actors/entities to track"],
  "hypotheses": [
    {{"statement": "hypothesis text", "weight": 0.5, "category": "military|economic|diplomatic|energy"}}
  ],
  "osint_queries": ["suggested search queries for OSINT data collection"],
  "timeframe": "prediction timeframe (e.g. 3 months)",
  "engines": ["mirofish", "analyst_crew", "ensemble"],
  "risk_categories": ["relevant risk categories"]
}}

Be specific to the topic. Use the same language as the topic for title and descriptions."""

    try:
        result = llm.chat_json([
            {"role": "system", "content": "You are a geopolitical intelligence configuration assistant. Output JSON only."},
            {"role": "user", "content": prompt},
        ], max_tokens=2000)
        return jsonify({"suggestion": result})
    except Exception as e:
        logger.warning(f"Wizard suggest failed: {e}")
        return jsonify({"error": str(e)}), 500


@engine_bp.route('/wizard/quick-notebook', methods=['POST'])
@require_auth
def wizard_quick_notebook():
    """One-click: enter topic -> get fully configured notebook."""
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "")
    if not topic:
        return jsonify({"error": "topic required"}), 400

    # Step 1: Get AI suggestion
    from ..utils.llm_client import LLMClient
    llm = LLMClient()
    try:
        suggestion = llm.chat_json([
            {"role": "system", "content": "You are a geopolitical prediction configurator. Output JSON only with keys: title, topic, languages, actors, hypotheses, osint_queries, timeframe, engines."},
            {"role": "user", "content": f"Configure prediction for: {topic}"},
        ], max_tokens=1500)
    except Exception:
        suggestion = {"title": topic, "topic": topic, "languages": ["en"], "actors": [], "hypotheses": [], "osint_queries": [topic], "timeframe": "3 months", "engines": ["mirofish"]}

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
        "config": suggestion,
        "steps": [],
        "results": {},
    }
    with open(_nb_path(nb_id), 'w') as f:
        json.dump(notebook, f, ensure_ascii=False, indent=2)

    return jsonify({"notebook": notebook, "suggestion": suggestion}), 201


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
