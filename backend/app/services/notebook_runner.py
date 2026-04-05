"""
Notebook execution service for QEngin.

Runs notebook analyses asynchronously, persists progress into notebook JSON,
and generates Markdown / HTML / JSON result artifacts.
"""

from __future__ import annotations

import html
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .osint_fetcher import OSINTFetcher, OSINTItem

logger = get_logger("mirofish.notebook_runner")


NOTEBOOK_RUNNER_LOCK = threading.Lock()
NOTEBOOK_THREADS: Dict[str, threading.Thread] = {}


class NotebookCancelled(Exception):
    """Raised when an execution is cancelled by the operator."""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def notebook_path(notebooks_dir: str, notebook_id: str) -> str:
    return os.path.join(notebooks_dir, f"{notebook_id}.json")


def load_notebook(notebooks_dir: str, notebook_id: str) -> Dict[str, Any]:
    path = notebook_path(notebooks_dir, notebook_id)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _merge_execution_state(latest: Dict[str, Any], notebook: Dict[str, Any]) -> None:
    latest_execution = latest.get("execution", {})
    execution = notebook.setdefault("execution", {})

    if latest_execution.get("cancel_requested"):
        execution["cancel_requested"] = True

    latest_logs = latest_execution.get("logs", [])
    local_logs = execution.get("logs", [])
    if latest_logs:
        merged_logs: List[Dict[str, Any]] = []
        seen = set()
        for item in latest_logs + local_logs:
            key = (
                item.get("timestamp"),
                item.get("stage"),
                item.get("message"),
            )
            if key in seen:
                continue
            merged_logs.append(item)
            seen.add(key)
        execution["logs"] = merged_logs

    if latest_execution.get("current_stage") == "cancel_pending" and execution.get("current_stage") not in {
        "complete",
        "failed",
        "cancelled",
    }:
        execution["current_stage"] = "cancel_pending"


def save_notebook(notebooks_dir: str, notebook: Dict[str, Any]) -> Dict[str, Any]:
    path = notebook_path(notebooks_dir, notebook["id"])
    if os.path.exists(path):
        try:
            latest = load_notebook(notebooks_dir, notebook["id"])
            _merge_execution_state(latest, notebook)
        except Exception:
            logger.debug("Unable to merge notebook execution state before save", exc_info=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(notebook, handle, ensure_ascii=False, indent=2)
    return notebook


def append_execution_log(
    notebook: Dict[str, Any],
    stage: str,
    message: str,
    *,
    level: str = "info",
    details: Optional[Dict[str, Any]] = None,
    progress: Optional[int] = None,
) -> None:
    execution = notebook.setdefault("execution", {})
    logs = execution.setdefault("logs", [])
    entry = {
        "timestamp": utcnow_iso(),
        "stage": stage,
        "level": level,
        "message": message,
        "details": details or {},
    }
    if progress is not None:
        entry["progress"] = progress
        execution["progress"] = progress
    execution["current_stage"] = stage
    execution["updated"] = entry["timestamp"]
    logs.append(entry)


def _mark_stage_started(notebook: Dict[str, Any], stage: str) -> None:
    execution = notebook.setdefault("execution", {})
    timings = execution.setdefault("stage_timings", {})
    state = timings.setdefault(stage, {})
    state["started_at"] = utcnow_iso()


def _mark_stage_finished(notebook: Dict[str, Any], stage: str) -> None:
    execution = notebook.setdefault("execution", {})
    timings = execution.setdefault("stage_timings", {})
    state = timings.setdefault(stage, {})
    state["completed_at"] = utcnow_iso()


def set_execution_state(
    notebook: Dict[str, Any],
    *,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    stage: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    execution = notebook.setdefault("execution", {})
    if status is not None:
        notebook["status"] = status
        execution["status"] = status
    if progress is not None:
        execution["progress"] = progress
    if stage is not None:
        execution["current_stage"] = stage
    if error is not None:
        execution["error"] = error
    notebook["updated"] = utcnow_iso()
    execution["updated"] = notebook["updated"]


def _check_cancelled(notebooks_dir: str, notebook_id: str, notebook: Optional[Dict[str, Any]] = None) -> None:
    latest = load_notebook(notebooks_dir, notebook_id)
    if notebook is not None:
        _merge_execution_state(latest, notebook)
    execution = latest.get("execution", {})
    if execution.get("cancel_requested"):
        raise NotebookCancelled("Notebook execution was cancelled by operator.")


def _ensure_serializable_osint(items: List[OSINTItem]) -> List[Dict[str, Any]]:
    return [
        {
            "title": item.title,
            "content": item.content,
            "url": item.url,
            "source": item.source,
            "language": item.language,
            "published": item.published,
            "category": item.category,
            "relevance_score": item.relevance_score,
        }
        for item in items
    ]


def _build_source_brief(items: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    brief = []
    for item in items[:limit]:
        brief.append(
            {
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "language": item.get("language", ""),
                "published": item.get("published"),
                "url": item.get("url", ""),
                "category": item.get("category", "general"),
            }
        )
    return brief


def _fallback_result(notebook: Dict[str, Any], sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = notebook.get("config", {})
    topic = cfg.get("topic") or notebook.get("title") or "Notebook analysis"
    hypotheses = cfg.get("hypotheses") or []
    findings = [
        f"تمرکز اصلی این notebook روی موضوع «{topic}» است و برای شروع آماده‌ی تحلیل ساخت‌یافته شد.",
        f"{len(sources)} منبع OSINT برای این notebook جمع‌آوری شد.",
    ]
    if hypotheses:
        findings.append("فرضیه‌های اولیه برای پایش و مقایسه در خروجی ثبت شدند.")

    scenarios = []
    for idx, hypothesis in enumerate(hypotheses[:3], start=1):
        scenarios.append(
            {
                "name": f"Scenario {idx}",
                "probability": hypothesis.get("weight", 0.33),
                "summary": hypothesis.get("statement", ""),
                "signals": [hypothesis.get("category", "general")],
            }
        )
    if not scenarios:
        scenarios = [
            {
                "name": "Baseline",
                "probability": 0.5,
                "summary": f"The current baseline view for {topic} remains fluid and requires ongoing monitoring.",
                "signals": cfg.get("risk_categories", ["general"]),
            }
        ]

    return {
        "title": notebook.get("title", topic),
        "topic": topic,
        "executive_summary": (
            f"Notebook «{topic}» اجرا شد. خروجی با fallback محلی تولید شده و برای جمع‌بندی انسانی آماده است."
        ),
        "key_findings": findings,
        "scenarios": scenarios,
        "recommended_actions": [
            "فرضیه‌های اصلی را با منابع تازه‌تر validate کنید.",
            "روی بازیگران کلیدی و تغییرات سریع محیطی alert بگذارید.",
            "در صورت اهمیت عملیاتی، اجرای بعدی notebook را با دامنه زمانی محدودتر تکرار کنید.",
        ],
        "indicators": [
            {
                "indicator": query,
                "why_it_matters": "برای پایش سریع تغییرات narrative و رخدادهای تازه مفید است.",
            }
            for query in (cfg.get("osint_queries") or [])[:5]
        ],
        "source_brief": _build_source_brief(sources),
        "source_count": len(sources),
        "languages": cfg.get("languages", []),
        "actors": cfg.get("actors", []),
        "hypotheses": hypotheses,
        "generated_with": "fallback",
    }


def _result_schema_prompt(notebook: Dict[str, Any], sources: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    cfg = notebook.get("config", {})
    compact_sources = _build_source_brief(sources, limit=8)
    schema = {
        "title": notebook.get("title", ""),
        "topic": cfg.get("topic", ""),
        "executive_summary": "1 paragraph",
        "key_findings": ["finding 1", "finding 2"],
        "scenarios": [
            {
                "name": "Base case",
                "probability": 0.45,
                "summary": "short scenario summary",
                "signals": ["signal 1", "signal 2"],
            }
        ],
        "recommended_actions": ["action 1", "action 2"],
        "indicators": [
            {
                "indicator": "signal to monitor",
                "why_it_matters": "why it matters",
            }
        ],
        "source_brief": compact_sources,
    }
    return [
        {
            "role": "system",
            "content": (
                "You are QEngin, a strategic notebook execution engine. "
                "Return compact JSON only. Be precise, operational, and concise. "
                "Use the provided sources and notebook configuration. "
                "Do not invent unseen sources."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Notebook title: {notebook.get('title', '')}\n"
                f"Notebook config JSON:\n{json.dumps(cfg, ensure_ascii=False)}\n\n"
                f"Recent OSINT sources:\n{json.dumps(compact_sources, ensure_ascii=False)}\n\n"
                f"Return JSON with exactly this structure:\n{json.dumps(schema, ensure_ascii=False)}"
            ),
        },
    ]


def _normalize_result(notebook: Dict[str, Any], raw: Dict[str, Any], sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    fallback = _fallback_result(notebook, sources)
    if not isinstance(raw, dict):
        return fallback

    result = {}
    for key, value in fallback.items():
        incoming = raw.get(key)
        result[key] = incoming if incoming not in (None, "", []) else value

    if not isinstance(result.get("key_findings"), list):
        result["key_findings"] = fallback["key_findings"]
    if not isinstance(result.get("scenarios"), list):
        result["scenarios"] = fallback["scenarios"]
    if not isinstance(result.get("recommended_actions"), list):
        result["recommended_actions"] = fallback["recommended_actions"]
    if not isinstance(result.get("indicators"), list):
        result["indicators"] = fallback["indicators"]
    if not isinstance(result.get("source_brief"), list):
        result["source_brief"] = fallback["source_brief"]

    result["source_count"] = len(sources)
    result.setdefault("languages", notebook.get("config", {}).get("languages", []))
    result.setdefault("actors", notebook.get("config", {}).get("actors", []))
    result.setdefault("hypotheses", notebook.get("config", {}).get("hypotheses", []))
    if "generated_with" not in result:
        result["generated_with"] = "llm"
    return result


def _render_markdown(notebook: Dict[str, Any], result: Dict[str, Any]) -> str:
    lines = [
        f"# {result.get('title') or notebook.get('title', 'Notebook Result')}",
        "",
        f"**Topic:** {result.get('topic', '')}",
        f"**Generated at:** {utcnow_iso()}",
        "",
        "## Executive Summary",
        "",
        result.get("executive_summary", ""),
        "",
        "## Key Findings",
        "",
    ]
    for item in result.get("key_findings", []):
        lines.append(f"- {item}")
    lines.extend(["", "## Scenarios", ""])
    for scenario in result.get("scenarios", []):
        lines.append(f"### {scenario.get('name', 'Scenario')} ({scenario.get('probability', 0)})")
        lines.append("")
        lines.append(scenario.get("summary", ""))
        signals = scenario.get("signals") or []
        if signals:
            lines.append("")
            lines.append("Signals:")
            for signal in signals:
                lines.append(f"- {signal}")
        lines.append("")

    lines.extend(["## Recommended Actions", ""])
    for action in result.get("recommended_actions", []):
        lines.append(f"- {action}")

    lines.extend(["", "## Indicators", ""])
    for indicator in result.get("indicators", []):
        lines.append(f"- **{indicator.get('indicator', '')}**: {indicator.get('why_it_matters', '')}")

    lines.extend(["", "## Sources", ""])
    for source in result.get("source_brief", []):
        title = source.get("title", "Untitled source")
        url = source.get("url", "")
        source_name = source.get("source", "")
        lines.append(f"- [{title}]({url}) — {source_name}")
    return "\n".join(lines).strip() + "\n"


def _render_html(notebook: Dict[str, Any], result: Dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value or ""))

    findings = "".join(f"<li>{esc(item)}</li>" for item in result.get("key_findings", []))
    scenarios = ""
    for scenario in result.get("scenarios", []):
        signals = "".join(f"<li>{esc(sig)}</li>" for sig in scenario.get("signals", []))
        scenarios += (
            "<section class='scenario'>"
            f"<h3>{esc(scenario.get('name', 'Scenario'))} <span>{esc(scenario.get('probability', 0))}</span></h3>"
            f"<p>{esc(scenario.get('summary', ''))}</p>"
            f"<ul>{signals}</ul>"
            "</section>"
        )
    actions = "".join(f"<li>{esc(item)}</li>" for item in result.get("recommended_actions", []))
    indicators = "".join(
        f"<li><strong>{esc(item.get('indicator', ''))}</strong> — {esc(item.get('why_it_matters', ''))}</li>"
        for item in result.get("indicators", [])
    )
    sources = "".join(
        f"<li><a href='{esc(item.get('url', '#'))}' target='_blank' rel='noopener'>{esc(item.get('title', 'Untitled source'))}</a> — {esc(item.get('source', ''))}</li>"
        for item in result.get("source_brief", [])
    )

    return f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(result.get('title') or notebook.get('title', 'QEngin Result'))}</title>
  <style>
    body{{font-family:Segoe UI,Tahoma,sans-serif;background:#0b1020;color:#e5ecf6;margin:0;padding:32px;line-height:1.9}}
    .wrap{{max-width:1024px;margin:0 auto}}
    .hero,.panel{{background:#121a2c;border:1px solid #24314d;border-radius:18px;padding:24px;margin-bottom:18px}}
    h1,h2,h3{{margin-top:0;color:#7fb0ff}}
    ul{{padding-right:22px}}
    a{{color:#8ab4ff}}
    .meta{{color:#97a8c7;font-size:14px}}
    .scenario{{padding:14px 0;border-top:1px solid #22314b}}
    .scenario:first-child{{border-top:none}}
    .scenario h3 span{{font-size:14px;color:#9ac6a5;margin-right:8px}}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>{esc(result.get('title') or notebook.get('title', 'QEngin Result'))}</h1>
      <p class="meta">Topic: {esc(result.get('topic', ''))}</p>
      <p>{esc(result.get('executive_summary', ''))}</p>
    </section>
    <section class="panel">
      <h2>Key Findings</h2>
      <ul>{findings}</ul>
    </section>
    <section class="panel">
      <h2>Scenarios</h2>
      {scenarios}
    </section>
    <section class="panel">
      <h2>Recommended Actions</h2>
      <ul>{actions}</ul>
    </section>
    <section class="panel">
      <h2>Indicators</h2>
      <ul>{indicators}</ul>
    </section>
    <section class="panel">
      <h2>Sources</h2>
      <ul>{sources}</ul>
    </section>
  </div>
</body>
</html>"""


def _artifact_dir() -> str:
    path = os.path.join(Config.UPLOAD_FOLDER, "notebook_results")
    os.makedirs(path, exist_ok=True)
    return path


def _artifact_paths(notebook_id: str) -> Dict[str, str]:
    base = os.path.join(_artifact_dir(), notebook_id)
    return {
        "json": f"{base}.json",
        "markdown": f"{base}.md",
        "html": f"{base}.html",
    }


def write_result_artifacts(notebook: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, str]:
    paths = _artifact_paths(notebook["id"])
    markdown = _render_markdown(notebook, result)
    html_output = _render_html(notebook, result)
    with open(paths["json"], "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    with open(paths["markdown"], "w", encoding="utf-8") as handle:
        handle.write(markdown)
    with open(paths["html"], "w", encoding="utf-8") as handle:
        handle.write(html_output)
    return paths


def load_artifact_text(notebook_id: str, fmt: str) -> str:
    paths = _artifact_paths(notebook_id)
    with open(paths[fmt], "r", encoding="utf-8") as handle:
        return handle.read()


def build_status_payload(notebook: Dict[str, Any]) -> Dict[str, Any]:
    execution = notebook.get("execution", {})
    return {
        "id": notebook["id"],
        "title": notebook.get("title"),
        "status": notebook.get("status", "draft"),
        "progress": execution.get("progress", 0),
        "current_stage": execution.get("current_stage"),
        "updated": notebook.get("updated"),
        "started_at": execution.get("started_at"),
        "completed_at": execution.get("completed_at"),
        "error": execution.get("error"),
        "logs_count": len(execution.get("logs", [])),
        "results_ready": bool(notebook.get("results")),
        "exports": notebook.get("exports", {}),
        "run_id": execution.get("run_id"),
        "cancel_requested": execution.get("cancel_requested", False),
        "can_cancel": notebook.get("status") == "running",
        "source_count": len(execution.get("sources", [])),
        "llm_model": notebook.get("config", {}).get("llm_model") or Config.QENGIN_WIZARD_MODEL,
        "analysis_mode": notebook.get("config", {}).get("analysis_mode", "strategic-brief"),
    }


def get_notebook_logs(notebook: Dict[str, Any], from_index: int = 0) -> Dict[str, Any]:
    logs = notebook.get("execution", {}).get("logs", [])
    sliced = logs[from_index:]
    return {
        "logs": sliced,
        "from_index": from_index,
        "next_index": from_index + len(sliced),
        "total": len(logs),
        "has_more": False,
    }


def build_diagnostics_payload(notebook: Dict[str, Any]) -> Dict[str, Any]:
    execution = notebook.get("execution", {})
    sources = execution.get("sources", [])
    artifact_paths = execution.get("artifact_paths", {})
    diagnostics = {
        "notebook": {
            "id": notebook.get("id"),
            "title": notebook.get("title"),
            "status": notebook.get("status"),
            "owner": notebook.get("owner"),
            "created": notebook.get("created"),
            "updated": notebook.get("updated"),
        },
        "config": notebook.get("config", {}),
        "execution": execution,
        "pipeline": [
            {
                "name": "osint_fetcher",
                "role": "Collects candidate sources from the configured topic and queries.",
                "status": "complete" if sources else ("running" if notebook.get("status") == "running" else "idle"),
            },
            {
                "name": "llm_synthesis",
                "role": "Builds strategic findings, scenarios, and recommended actions.",
                "status": "complete" if notebook.get("results") else ("running" if notebook.get("status") == "running" else "idle"),
                "model": notebook.get("config", {}).get("llm_model") or Config.QENGIN_WIZARD_MODEL,
            },
            {
                "name": "artifact_writer",
                "role": "Generates HTML, Markdown, and JSON exports.",
                "status": "complete" if artifact_paths else ("running" if notebook.get("status") == "running" else "idle"),
                "artifacts": artifact_paths,
            },
        ],
        "source_summary": {
            "count": len(sources),
            "items": _build_source_brief(sources, limit=10),
        },
        "result_summary": {
            "ready": bool(notebook.get("results")),
            "generated_with": notebook.get("results", {}).get("generated_with"),
            "key_findings_count": len(notebook.get("results", {}).get("key_findings", [])),
            "scenario_count": len(notebook.get("results", {}).get("scenarios", [])),
        },
        "exports": notebook.get("exports", {}),
    }
    return diagnostics


def execute_notebook_sync(notebooks_dir: str, notebook_id: str) -> Dict[str, Any]:
    with NOTEBOOK_RUNNER_LOCK:
        notebook = load_notebook(notebooks_dir, notebook_id)
        execution = notebook.setdefault("execution", {})
        if not execution.get("run_id"):
            execution["run_id"] = uuid.uuid4().hex[:12]
        execution["started_at"] = utcnow_iso()
        execution["logs"] = []
        execution["error"] = None
        execution["cancel_requested"] = False
        execution["stage_timings"] = {}
        set_execution_state(notebook, status="running", progress=0, stage="queued")
        append_execution_log(notebook, "queued", "Notebook execution queued.", progress=0)
        save_notebook(notebooks_dir, notebook)

    cfg = notebook.get("config", {})
    topic = cfg.get("topic") or notebook.get("title") or "Notebook analysis"
    llm_model = cfg.get("llm_model") or Config.QENGIN_WIZARD_MODEL
    source_limit = int(cfg.get("source_limit") or 9)

    try:
        _check_cancelled(notebooks_dir, notebook_id, notebook)
        _mark_stage_started(notebook, "collecting_sources")
        append_execution_log(notebook, "collecting_sources", "Collecting OSINT sources.", progress=10)
        save_notebook(notebooks_dir, notebook)

        fetcher = OSINTFetcher(timeout=15, max_workers=6)
        queries = [q for q in (cfg.get("osint_queries") or []) if q]
        primary_query = queries[0] if queries else topic
        languages = cfg.get("languages") or None
        items = fetcher.fetch_all(query=primary_query, languages=languages, max_per_source=3)
        serialized_sources = _ensure_serializable_osint(items)[:source_limit]
        notebook.setdefault("execution", {})["sources"] = serialized_sources
        _mark_stage_finished(notebook, "collecting_sources")
        append_execution_log(
            notebook,
            "collecting_sources",
            f"Collected {len(serialized_sources)} source items.",
            progress=35,
            details={"query": primary_query, "source_count": len(serialized_sources)},
        )
        save_notebook(notebooks_dir, notebook)

        _check_cancelled(notebooks_dir, notebook_id, notebook)
        _mark_stage_started(notebook, "synthesis")
        append_execution_log(notebook, "synthesis", "Generating strategic synthesis.", progress=55)
        save_notebook(notebooks_dir, notebook)

        result: Dict[str, Any]
        try:
            llm = LLMClient(model=llm_model)
            raw_result = llm.chat_json(
                _result_schema_prompt(notebook, serialized_sources),
                temperature=0.2,
                max_tokens=max(800, Config.QENGIN_WIZARD_MAX_TOKENS),
                max_retries=max(1, Config.QENGIN_WIZARD_MAX_RETRIES),
            )
            result = _normalize_result(notebook, raw_result, serialized_sources)
            result["generated_with"] = raw_result.get("generated_with", "llm") if isinstance(raw_result, dict) else "llm"
            append_execution_log(
                notebook,
                "synthesis",
                "LLM synthesis completed.",
                progress=78,
                details={"mode": "llm", "model": llm_model},
            )
        except Exception as exc:
            logger.warning("Notebook %s fallback synthesis: %s", notebook_id, exc)
            result = _fallback_result(notebook, serialized_sources)
            append_execution_log(
                notebook,
                "synthesis",
                "LLM unavailable, fallback synthesis generated.",
                progress=78,
                level="warning",
                details={"mode": "fallback", "error": str(exc)},
            )
        _mark_stage_finished(notebook, "synthesis")
        save_notebook(notebooks_dir, notebook)

        _check_cancelled(notebooks_dir, notebook_id, notebook)
        _mark_stage_started(notebook, "rendering")
        append_execution_log(notebook, "rendering", "Rendering result exports.", progress=90)
        exports = write_result_artifacts(notebook, result)
        notebook["results"] = result
        notebook["exports"] = {
            "json": f"/engine/notebooks/{notebook_id}/export?format=json",
            "markdown": f"/engine/notebooks/{notebook_id}/export?format=markdown",
            "html": f"/engine/notebooks/{notebook_id}/export?format=html",
        }
        execution = notebook.setdefault("execution", {})
        execution["completed_at"] = utcnow_iso()
        execution["artifact_paths"] = exports
        _mark_stage_finished(notebook, "rendering")
        append_execution_log(
            notebook,
            "complete",
            "Notebook execution completed successfully.",
            progress=100,
            details={"artifacts": exports},
        )
        set_execution_state(notebook, status="complete", progress=100, stage="complete")
        save_notebook(notebooks_dir, notebook)
        return notebook
    except NotebookCancelled as exc:
        append_execution_log(
            notebook,
            "cancelled",
            "Notebook execution cancelled by operator.",
            progress=100,
            level="warning",
            details={"reason": str(exc)},
        )
        set_execution_state(notebook, status="cancelled", progress=100, stage="cancelled", error=str(exc))
        notebook.setdefault("execution", {})["completed_at"] = utcnow_iso()
        save_notebook(notebooks_dir, notebook)
        return notebook
    except Exception as exc:
        logger.exception("Notebook %s failed", notebook_id)
        append_execution_log(
            notebook,
            "failed",
            "Notebook execution failed.",
            progress=100,
            level="error",
            details={"error": str(exc)},
        )
        set_execution_state(notebook, status="failed", progress=100, stage="failed", error=str(exc))
        notebook.setdefault("execution", {})["completed_at"] = utcnow_iso()
        save_notebook(notebooks_dir, notebook)
        return notebook


def start_notebook_run(notebooks_dir: str, notebook_id: str) -> Tuple[Dict[str, Any], bool]:
    notebook = load_notebook(notebooks_dir, notebook_id)
    existing = NOTEBOOK_THREADS.get(notebook_id)
    if existing and existing.is_alive():
        return notebook, False

    thread = threading.Thread(
        target=execute_notebook_sync,
        args=(notebooks_dir, notebook_id),
        daemon=True,
        name=f"qengin-nb-{notebook_id}",
    )
    NOTEBOOK_THREADS[notebook_id] = thread
    thread.start()
    time.sleep(0.05)
    notebook = load_notebook(notebooks_dir, notebook_id)
    return notebook, True


def request_notebook_cancel(notebooks_dir: str, notebook_id: str) -> Tuple[Dict[str, Any], bool]:
    notebook = load_notebook(notebooks_dir, notebook_id)
    if notebook.get("status") != "running":
        return notebook, False

    execution = notebook.setdefault("execution", {})
    if execution.get("cancel_requested"):
        return notebook, False

    execution["cancel_requested"] = True
    append_execution_log(
        notebook,
        "cancel_pending",
        "Cancellation requested. Execution will stop at the next safe checkpoint.",
        level="warning",
        progress=execution.get("progress", 0),
    )
    save_notebook(notebooks_dir, notebook)
    return notebook, True


def export_payload(notebook: Dict[str, Any], fmt: str) -> Tuple[str, str]:
    result = notebook.get("results")
    if not result:
        raise FileNotFoundError("Notebook results are not ready")

    if fmt == "json":
        return json.dumps(result, ensure_ascii=False, indent=2), "application/json; charset=utf-8"
    if fmt == "markdown":
        return load_artifact_text(notebook["id"], "markdown"), "text/markdown; charset=utf-8"
    if fmt == "html":
        return load_artifact_text(notebook["id"], "html"), "text/html; charset=utf-8"
    raise ValueError(f"Unsupported export format: {fmt}")
