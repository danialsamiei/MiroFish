"""
EnsembleVoter - Multi-model LLM voting for higher prediction accuracy.

Runs the same analysis prompt against multiple LLM models in parallel,
then computes consensus via majority voting with confidence scoring.
Divergences between models are explicitly surfaced in the final result.

Architecture:
  - Each model receives identical system+user prompts
  - Responses are collected in parallel (ThreadPoolExecutor)
  - Consensus: numeric fields averaged, strings longest-wins, lists merged
  - Confidence: ratio of fields where models agree (within 20% for numbers)
  - Divergences: fields where models disagree by >30%
"""

import concurrent.futures
import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from collections import Counter

from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger

logger = get_logger('mirofish.ensemble')


@dataclass
class ModelResult:
    """Result from a single model in the ensemble."""
    model: str
    response: Dict[str, Any]
    latency_ms: float
    success: bool
    error: Optional[str] = None


@dataclass
class EnsembleResult:
    """Combined result from ensemble voting."""
    consensus: Dict[str, Any]
    confidence: float  # 0.0 - 1.0 agreement ratio
    divergences: List[Dict[str, Any]]  # points where models disagree
    individual_results: Dict[str, ModelResult] = field(default_factory=dict)
    voting_method: str = "majority"


# Default ensemble: use models verified as working on QADR
DEFAULT_ENSEMBLE_MODELS = {
    "claude_sonnet": "cl-claude-sonnet-4-6",
    "claude_haiku": "cl-claude-haiku-4-5-20251001",
    "claude_opus": "cl-claude-opus-4-6",
}


class EnsembleVoter:
    """Multi-model voting for prediction accuracy improvement."""

    def __init__(self, models: Optional[Dict[str, str]] = None):
        """
        Initialize with a dict of {name: model_id}.
        Defaults to 3 Claude variants if not specified.
        """
        self.model_configs = models or DEFAULT_ENSEMBLE_MODELS
        self.clients = {
            name: LLMClient(model=model_id)
            for name, model_id in self.model_configs.items()
        }

    def ensemble_analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        min_models: int = 2,
    ) -> EnsembleResult:
        """
        Run analysis across all models and compute consensus.

        Args:
            system_prompt: System instruction for the analysis
            user_prompt: User query with context data
            temperature: LLM temperature (lower = more deterministic)
            max_tokens: Max tokens per model response
            min_models: Minimum models that must succeed for valid result

        Returns:
            EnsembleResult with consensus, confidence score, and divergences
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Run all models in parallel
        individual_results = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(self.clients)
        ) as executor:
            futures = {}
            for name, client in self.clients.items():
                future = executor.submit(
                    self._call_model, name, client, messages,
                    temperature, max_tokens
                )
                futures[future] = name

            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    individual_results[name] = future.result()
                except Exception as e:
                    individual_results[name] = ModelResult(
                        model=self.model_configs[name],
                        response={}, latency_ms=0,
                        success=False, error=str(e)
                    )

        # Filter successful results
        successful = {k: v for k, v in individual_results.items() if v.success}

        if len(successful) < min_models:
            logger.error(
                f"Only {len(successful)}/{len(self.clients)} models succeeded"
            )
            if successful:
                best = next(iter(successful.values()))
                return EnsembleResult(
                    consensus=best.response,
                    confidence=0.0,
                    divergences=[{"note": "insufficient models for voting"}],
                    individual_results=individual_results,
                    voting_method="fallback",
                )
            raise RuntimeError("All models failed in ensemble voting")

        # Compute consensus, confidence, and divergences
        consensus = self._compute_consensus(successful)
        confidence = self._compute_confidence(successful)
        divergences = self._find_divergences(successful)

        logger.info(
            f"Ensemble: {len(successful)}/{len(self.clients)} models, "
            f"confidence={confidence:.2f}, divergences={len(divergences)}"
        )

        return EnsembleResult(
            consensus=consensus,
            confidence=confidence,
            divergences=divergences,
            individual_results=individual_results,
            voting_method="majority",
        )

    def _call_model(
        self, name: str, client: LLMClient,
        messages: list, temperature: float, max_tokens: int
    ) -> ModelResult:
        """Call a single model and return structured result."""
        start = time.time()
        try:
            response = client.chat_json(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            latency = (time.time() - start) * 1000
            logger.info(f"Model {name} responded in {latency:.0f}ms")
            return ModelResult(
                model=self.model_configs[name],
                response=response,
                latency_ms=latency,
                success=True,
            )
        except Exception as e:
            latency = (time.time() - start) * 1000
            logger.warning(f"Model {name} failed ({latency:.0f}ms): {e}")
            return ModelResult(
                model=self.model_configs[name],
                response={}, latency_ms=latency,
                success=False, error=str(e)[:200],
            )

    def _compute_consensus(
        self, results: Dict[str, ModelResult]
    ) -> Dict[str, Any]:
        """Merge results using field-level majority voting."""
        resps = [r.response for r in results.values()]
        if len(resps) == 1:
            return resps[0]

        # Collect all keys
        all_keys = set()
        for r in resps:
            if isinstance(r, dict):
                all_keys.update(r.keys())

        consensus = {}
        for key in all_keys:
            vals = [
                r.get(key) for r in resps
                if isinstance(r, dict) and key in r
            ]
            if not vals:
                continue

            # Lists: merge unique items from all models
            if all(isinstance(v, list) for v in vals):
                merged, seen = [], set()
                for v_list in vals:
                    for item in v_list:
                        item_key = (
                            json.dumps(item, sort_keys=True, default=str)
                            if isinstance(item, dict) else str(item)
                        )
                        if item_key not in seen:
                            seen.add(item_key)
                            merged.append(item)
                consensus[key] = merged

            # Numbers: average
            elif all(isinstance(v, (int, float)) for v in vals):
                consensus[key] = sum(vals) / len(vals)

            # Strings: longest (most detailed)
            elif all(isinstance(v, str) for v in vals):
                consensus[key] = max(vals, key=len)

            else:
                consensus[key] = vals[0]

        return consensus

    def _compute_confidence(
        self, results: Dict[str, ModelResult]
    ) -> float:
        """Compute agreement ratio between models (0.0-1.0)."""
        resps = [r.response for r in results.values()]
        if len(resps) <= 1:
            return 0.5

        all_keys = set()
        for r in resps:
            if isinstance(r, dict):
                all_keys.update(r.keys())

        if not all_keys:
            return 0.0

        agreements, total = 0, 0
        for key in all_keys:
            vals = [
                r.get(key) for r in resps
                if isinstance(r, dict) and key in r
            ]
            if len(vals) < 2:
                continue
            total += 1

            # Numeric: agree if within 20%
            if all(isinstance(v, (int, float)) for v in vals):
                avg = sum(vals) / len(vals)
                spread = max(
                    abs(v - avg) / max(abs(avg), 0.01)
                    for v in vals
                )
                if spread < 0.2:
                    agreements += 1

            # String: majority vote
            elif all(isinstance(v, str) for v in vals):
                counts = Counter(vals)
                if counts.most_common(1)[0][1] > len(vals) / 2:
                    agreements += 1

            # List: overlap ratio
            elif all(isinstance(v, list) for v in vals):
                sets = [
                    set(json.dumps(i, default=str) for i in v)
                    for v in vals if isinstance(v, list)
                ]
                if len(sets) >= 2:
                    overlap = (
                        len(sets[0] & sets[1])
                        / max(len(sets[0] | sets[1]), 1)
                    )
                    if overlap > 0.5:
                        agreements += 1

        return agreements / max(total, 1)

    def _find_divergences(
        self, results: Dict[str, ModelResult]
    ) -> List[Dict[str, Any]]:
        """Find specific points where models disagree significantly."""
        if len(results) <= 1:
            return []

        divergences = []
        responses = {name: r.response for name, r in results.items()}
        all_keys = set()
        for r in responses.values():
            if isinstance(r, dict):
                all_keys.update(r.keys())

        for key in all_keys:
            vals = {
                name: r.get(key)
                for name, r in responses.items()
                if isinstance(r, dict) and key in r
            }
            if len(vals) < 2:
                continue

            # Numeric divergence > 30%
            if all(isinstance(v, (int, float)) for v in vals.values()):
                vl = list(vals.values())
                avg = sum(vl) / len(vl)
                spread = max(
                    abs(v - avg) / max(abs(avg), 0.01)
                    for v in vl
                )
                if spread > 0.3:
                    divergences.append({
                        "field": key,
                        "type": "numeric_divergence",
                        "values": vals,
                        "spread": round(spread, 2),
                    })

            # Text divergence
            elif all(isinstance(v, str) for v in vals.values()):
                unique = set(vals.values())
                if len(unique) > 1 and len(list(vals.values())[0]) > 20:
                    divergences.append({
                        "field": key,
                        "type": "text_divergence",
                        "values": {
                            k: v[:100] for k, v in vals.items()
                        },
                    })

        return divergences

    def test_voting(self) -> Dict[str, Any]:
        """Quick self-test of ensemble voting capability."""
        result = self.ensemble_analyze(
            system_prompt="You are an analyst. Output JSON only.",
            user_prompt=(
                'Analyze: "Oil prices rose 5% due to Hormuz tensions". '
                'Return JSON with fields: '
                'impact (string), severity (integer 1-10), '
                'confidence (float 0.0-1.0).'
            ),
            max_tokens=200,
        )
        return {
            "status": "ok",
            "models_used": len([
                r for r in result.individual_results.values()
                if r.success
            ]),
            "confidence": round(result.confidence, 2),
            "divergences": len(result.divergences),
            "consensus_keys": list(result.consensus.keys()),
            "voting_method": result.voting_method,
        }
