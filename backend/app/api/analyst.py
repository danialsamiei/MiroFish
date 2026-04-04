"""Analyst Crew API endpoints for expert multi-agent analysis."""

import threading
from flask import request, jsonify
from . import analyst_bp
from ..services.analyst_crew import AnalystCrew
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.analyst')


@analyst_bp.route('/analyst/analyze', methods=['POST'])
def analyst_analyze():
    """
    Run analyst crew on a topic.

    JSON body:
        topic: str - scenario/question to analyze (required)
        context: str - background information
        osint_data: list - recent OSINT items
        hypotheses: list - user hypotheses with weights
        model: str - LLM model override
    """
    data = request.get_json(silent=True) or {}
    topic = data.get('topic')
    if not topic:
        return jsonify({"error": "topic is required"}), 400

    crew = AnalystCrew(model=data.get('model'))
    report = crew.analyze(
        topic=topic,
        context=data.get('context', ''),
        osint_data=data.get('osint_data'),
        hypotheses=data.get('hypotheses'),
    )

    return jsonify({
        "summary": report.summary,
        "overall_risk": report.overall_risk,
        "overall_confidence": report.overall_confidence,
        "scenarios": report.scenarios,
        "recommendations": report.recommendations,
        "analysts": [
            {
                "role": r.role,
                "risk_level": r.risk_level,
                "confidence": r.confidence,
                "key_findings": r.key_findings,
                "analysis": r.analysis[:500],
                "latency_ms": round(r.latency_ms),
            }
            for r in report.analyst_reports
        ],
        "timestamp": report.timestamp,
    })


@analyst_bp.route('/analyst/quick-test', methods=['GET'])
def analyst_quick_test():
    """Quick self-test of analyst crew."""
    crew = AnalystCrew()
    result = crew.quick_test()
    return jsonify(result)
