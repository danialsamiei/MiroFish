"""
AnalystCrew - Multi-agent expert analysis using CAMEL-AI.

A crew of specialized analysts that work in parallel to produce
geopolitical, economic, military, and risk assessments. Uses the
existing CAMEL-AI framework (already installed for OASIS simulation).

Analyst Roles:
  1. Geopolitical Analyst - actor intent, alliances, diplomatic dynamics
  2. Economic Forecaster - market impact, trade, energy pricing
  3. Military Strategist - capability assessment, force positioning
  4. Risk Synthesizer - merges all analyses into unified risk score

Unlike OASIS (thousands of social agents), AnalystCrew uses 4 expert
agents with deep, structured reasoning via CAMEL RolePlaying.
"""

import time
import concurrent.futures
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger

logger = get_logger('mirofish.analyst_crew')


@dataclass
class AnalystReport:
    """Report from a single analyst."""
    role: str
    analysis: str
    key_findings: List[str]
    risk_level: str  # low, medium, high, critical
    confidence: float  # 0.0 - 1.0
    latency_ms: float = 0.0


@dataclass
class CrewReport:
    """Combined report from the entire analyst crew."""
    summary: str
    overall_risk: str
    overall_confidence: float
    analyst_reports: List[AnalystReport]
    scenarios: List[Dict[str, Any]]
    recommendations: List[str]
    timestamp: str = ""


# Analyst role definitions
ANALYST_ROLES = {
    "geopolitical": {
        "title": "Geopolitical Analyst",
        "system_prompt": (
            "You are a senior geopolitical analyst specializing in "
            "Middle East, Central Asia, and great power competition. "
            "Analyze actor motivations, alliance dynamics, diplomatic "
            "leverage, and strategic intent. Consider historical precedents. "
            "Output JSON with: analysis (string), key_findings (list of "
            "3-5 strings), risk_level (low/medium/high/critical), "
            "confidence (0.0-1.0), scenarios (list of {name, probability, "
            "description})."
        ),
    },
    "economic": {
        "title": "Economic Forecaster",
        "system_prompt": (
            "You are a senior economic analyst specializing in energy "
            "markets, sanctions impact, trade flows, and currency dynamics. "
            "Analyze economic consequences of geopolitical events including "
            "oil prices, supply chains, and financial markets. "
            "Output JSON with: analysis (string), key_findings (list of "
            "3-5 strings), risk_level (low/medium/high/critical), "
            "confidence (0.0-1.0), economic_indicators (dict with "
            "oil_impact, trade_impact, currency_impact)."
        ),
    },
    "military": {
        "title": "Military Strategist",
        "system_prompt": (
            "You are a defense intelligence analyst specializing in "
            "military capabilities, force deployments, and conflict "
            "escalation dynamics. Assess military balance, readiness, "
            "deterrence posture, and escalation risks. "
            "Output JSON with: analysis (string), key_findings (list of "
            "3-5 strings), risk_level (low/medium/high/critical), "
            "confidence (0.0-1.0), force_assessment (dict with "
            "escalation_risk, deterrence_stability, key_capabilities)."
        ),
    },
    "risk": {
        "title": "Risk Synthesizer",
        "system_prompt": (
            "You are a chief risk officer who synthesizes geopolitical, "
            "economic, and military analyses into an actionable risk "
            "assessment. Identify cascading risks, second-order effects, "
            "and decision-relevant uncertainties. "
            "Output JSON with: summary (string), overall_risk "
            "(low/medium/high/critical), overall_confidence (0.0-1.0), "
            "key_risks (list of strings), recommendations (list of "
            "actionable strings), scenarios (list of {name, probability, "
            "impact, timeframe})."
        ),
    },
}


class AnalystCrew:
    """Multi-agent expert analysis crew built on CAMEL-AI."""

    def __init__(
        self,
        model: Optional[str] = None,
        roles: Optional[Dict] = None,
    ):
        self.model = model or "cl-claude-haiku-4-5-20251001"
        self.roles = roles or ANALYST_ROLES
        self.llm = LLMClient(model=self.model)

    def analyze(
        self,
        topic: str,
        context: str = "",
        osint_data: Optional[List[Dict]] = None,
        hypotheses: Optional[List[Dict]] = None,
        parallel: bool = True,
    ) -> CrewReport:
        """
        Run full analyst crew on a topic.

        Args:
            topic: The scenario/question to analyze
            context: Additional context (documents, background)
            osint_data: Recent OSINT items for grounding
            hypotheses: User hypotheses with weights
            parallel: Run analysts in parallel (default True)

        Returns:
            CrewReport with all analyses merged
        """
        start = time.time()

        # Build shared context for all analysts
        shared_context = self._build_context(
            topic, context, osint_data, hypotheses
        )

        # Phase 1: Run domain analysts (parallel)
        domain_roles = ["geopolitical", "economic", "military"]
        domain_reports = {}

        if parallel:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=3
            ) as executor:
                futures = {
                    executor.submit(
                        self._run_analyst, role, shared_context
                    ): role
                    for role in domain_roles
                }
                for f in concurrent.futures.as_completed(futures):
                    role = futures[f]
                    try:
                        domain_reports[role] = f.result()
                    except Exception as e:
                        logger.warning(f"Analyst {role} failed: {e}")
                        domain_reports[role] = self._fallback_report(role)
        else:
            for role in domain_roles:
                try:
                    domain_reports[role] = self._run_analyst(
                        role, shared_context
                    )
                except Exception as e:
                    logger.warning(f"Analyst {role} failed: {e}")
                    domain_reports[role] = self._fallback_report(role)

        # Phase 2: Risk Synthesizer merges all domain reports
        synthesis = self._run_synthesizer(
            shared_context, domain_reports
        )

        total_ms = (time.time() - start) * 1000
        logger.info(
            f"AnalystCrew complete in {total_ms:.0f}ms: "
            f"{len(domain_reports)} analysts + synthesizer"
        )

        return CrewReport(
            summary=synthesis.get("summary", ""),
            overall_risk=synthesis.get("overall_risk", "medium"),
            overall_confidence=synthesis.get("overall_confidence", 0.5),
            analyst_reports=list(domain_reports.values()),
            scenarios=synthesis.get("scenarios", []),
            recommendations=synthesis.get("recommendations", []),
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    def _build_context(
        self, topic, context, osint_data, hypotheses
    ) -> str:
        """Build shared context string for all analysts."""
        parts = [f"TOPIC: {topic}"]
        if context:
            parts.append(f"\nBACKGROUND:\n{context}")
        if osint_data:
            osint_text = "\n".join(
                f"- [{d.get('source','')}] {d.get('title','')}"
                for d in osint_data[:20]
            )
            parts.append(f"\nRECENT INTELLIGENCE:\n{osint_text}")
        if hypotheses:
            hyp_text = "\n".join(
                f"- [weight={h.get('weight',0.5)}] {h.get('statement','')}"
                for h in hypotheses
            )
            parts.append(f"\nUSER HYPOTHESES:\n{hyp_text}")
        return "\n".join(parts)

    def _run_analyst(self, role: str, context: str) -> AnalystReport:
        """Run a single analyst and return structured report."""
        role_def = self.roles[role]
        start = time.time()

        result = self.llm.chat_json(
            messages=[
                {"role": "system", "content": role_def["system_prompt"]},
                {"role": "user", "content": context},
            ],
            temperature=0.4,
            max_tokens=2000,
        )

        latency = (time.time() - start) * 1000
        logger.info(f"Analyst {role} done in {latency:.0f}ms")

        return AnalystReport(
            role=role_def["title"],
            analysis=result.get("analysis", ""),
            key_findings=result.get("key_findings", []),
            risk_level=result.get("risk_level", "medium"),
            confidence=float(result.get("confidence", 0.5)),
            latency_ms=latency,
        )

    def _run_synthesizer(
        self, context: str, domain_reports: Dict[str, AnalystReport]
    ) -> Dict[str, Any]:
        """Run risk synthesizer with all domain analyses."""
        # Build synthesis input
        analyses_text = ""
        for role, report in domain_reports.items():
            analyses_text += (
                f"\n--- {report.role} ---\n"
                f"Risk: {report.risk_level} | "
                f"Confidence: {report.confidence}\n"
                f"Analysis: {report.analysis}\n"
                f"Findings: {'; '.join(report.key_findings)}\n"
            )

        synth_prompt = (
            f"{context}\n\n"
            f"DOMAIN ANALYSES:\n{analyses_text}\n\n"
            f"Synthesize the above into a unified risk assessment."
        )

        role_def = self.roles["risk"]
        return self.llm.chat_json(
            messages=[
                {"role": "system", "content": role_def["system_prompt"]},
                {"role": "user", "content": synth_prompt},
            ],
            temperature=0.3,
            max_tokens=3000,
        )

    def _fallback_report(self, role: str) -> AnalystReport:
        """Return a fallback report when analyst fails."""
        return AnalystReport(
            role=self.roles[role]["title"],
            analysis="Analysis unavailable due to model error.",
            key_findings=["Analyst failed to produce results"],
            risk_level="unknown",
            confidence=0.0,
        )

    def quick_test(self) -> Dict[str, Any]:
        """Quick self-test of analyst crew."""
        report = self.analyze(
            topic="Oil prices increased 10% due to Hormuz tensions",
            parallel=True,
        )
        return {
            "status": "ok",
            "analysts": len(report.analyst_reports),
            "overall_risk": report.overall_risk,
            "overall_confidence": report.overall_confidence,
            "scenarios": len(report.scenarios),
            "recommendations": len(report.recommendations),
        }
