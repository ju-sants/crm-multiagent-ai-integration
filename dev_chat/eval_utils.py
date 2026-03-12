"""
Evaluation utilities — Shared infrastructure for trustworthy LLM-as-Judge evaluation.

Provides:
  - Multi-model consensus evaluation (eliminates single-model bias)
  - Robust JSON extraction with multiple fallback strategies
  - Structured penalty parsing (no keyword matching)
  - Canary fixtures & validation for evaluator sanity checks
  - Prompt staleness detection (hash-based drift alerting)
"""

import hashlib
import json
import os
import statistics

from app.config.llm_config import create_llm
from app.core.logger import get_logger

logger = get_logger(__name__)

# Cross-provider models for consensus (different providers = less bias)
# Use mid-to-high tier models: evaluator quality > speed/cost here
DEFAULT_EVAL_MODELS = [
    "xai/grok-3",             # xAI heavyweight — high prompt adherence
    "gemini-2.5-pro-preview-05-06",  # Google frontier — strong reasoning
]

_BASE_DIR = os.path.join(os.path.dirname(__file__), '..')
_PROMPTS_DIR = os.path.join(_BASE_DIR, 'app', 'crews', 'agents_definitions', 'prompts')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ROBUST JSON EXTRACTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def extract_json_robust(text: str) -> dict | None:
    """Extract JSON from LLM output using multiple fallback strategies.

    Strategies (in order):
      1. Direct parse (text is pure JSON)
      2. Extract from ```json ... ``` markdown block
      3. Extract from ``` ... ``` generic code block
      4. Find first balanced { ... } braces
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: ```json block
    if '```json' in text:
        try:
            content = text.split('```json', 1)[1].split('```', 1)[0]
            return json.loads(content.strip())
        except (json.JSONDecodeError, IndexError):
            pass

    # Strategy 3: ``` block
    if '```' in text:
        try:
            content = text.split('```', 1)[1].split('```', 1)[0]
            return json.loads(content.strip())
        except (json.JSONDecodeError, IndexError):
            pass

    # Strategy 4: Balanced braces extraction
    start = text.find('{')
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break

    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STRUCTURED PENALTY HANDLING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PENALTY_SEVERITY = {
    "hallucination": 3,
    "prohibited_violation": 2,
    "total_rewrite": 2,
    "contradiction": 2,
    "incompatible_product": 2,
    "excessive_length": 1,
    "context_reaffirmation": 1,
    "lack_of_proactivity": 1,
    "generic_guidance": 1,
}


def compute_penalty_total(penalties: list) -> float:
    """Compute total penalty from structured or legacy penalty lists.

    Handles both formats:
    - Structured: [{"type": "hallucination", "severity": 3, "description": "..."}]
    - Legacy string: ["Alucinação: preço inventado"]
    """
    total = 0.0
    for p in penalties:
        if isinstance(p, dict):
            sev = p.get("severity")
            if isinstance(sev, (int, float)):
                total += sev
            else:
                total += PENALTY_SEVERITY.get(p.get("type", ""), 1)
        elif isinstance(p, str):
            total += _legacy_penalty_severity(p)
    return total


def _legacy_penalty_severity(text: str) -> float:
    """Map a legacy string penalty to severity (backward compat)."""
    tl = text.lower()
    for keyword, severity in [
        ("hallucin", 3), ("alucinaç", 3), ("inventado", 3), ("fabricat", 3),
        ("proibid", 2), ("prohibited", 2),
        ("reescrit", 2), ("rewrite", 2), ("contradiç", 2),
        ("incompatível", 2), ("incompatible", 2),
        ("excessiv", 1), ("reafirmaç", 1), ("proatividade", 1),
        ("genéric", 1), ("generic", 1),
    ]:
        if keyword in tl:
            return severity
    return 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  WEIGHTED SCORE COMPUTATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def compute_weighted_score(scores: dict, weights: dict, penalties: list = None) -> float:
    """Compute weighted average score with structured penalties applied.

    Args:
        scores: {dimension_key: score} where score is 0-10
        weights: {dimension_key: weight} where weights should sum to ~1.0
        penalties: list of penalty dicts or strings

    Returns:
        Final score (0.0-10.0), never negative.
    """
    weighted_sum = 0.0
    total_weight = 0.0
    for key, weight in weights.items():
        score = scores.get(key)
        if isinstance(score, (int, float)):
            weighted_sum += score * weight
            total_weight += weight

    if total_weight == 0:
        return 0.0

    base = weighted_sum / total_weight
    pen = compute_penalty_total(penalties or [])
    return max(0.0, round(base - pen, 1))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MULTI-MODEL CONSENSUS EVALUATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def multi_model_evaluate(
    system_prompt: str,
    user_prompt: str,
    models: list[str] = None,
    temperature: float = 0.1,
    weights: dict = None,
) -> dict:
    """Evaluate through multiple LLMs and aggregate via median for consensus.

    Uses cross-provider models to eliminate self-preference bias.
    Aggregation: median score per dimension, union of qualitative fields.

    Args:
        system_prompt: The evaluation system prompt
        user_prompt: The evaluation user prompt with dynamic data
        models: List of model keys. Defaults to DEFAULT_EVAL_MODELS.
        temperature: LLM temperature
        weights: Weight dict for computing overall_score from dimensions.

    Returns:
        Aggregated evaluation dict with per-dimension median scores,
        overall_score, and _meta with agreement metrics.
    """
    eval_models = models or DEFAULT_EVAL_MODELS
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    per_model = []
    for model_key in eval_models:
        try:
            llm = create_llm(model_key, temperature=temperature)
            response = llm.invoke(messages)
            parsed = extract_json_robust(response.content)
            if parsed:
                parsed["_model"] = model_key
                # Capture token usage from the evaluator LLM call
                token_usage = getattr(response, 'usage_metadata', None)
                if token_usage and isinstance(token_usage, dict):
                    parsed["_eval_tokens"] = {
                        "input": token_usage.get('input_tokens', 0),
                        "output": token_usage.get('output_tokens', 0),
                        "total": token_usage.get('total_tokens', 0),
                    }
                elif hasattr(response, 'response_metadata'):
                    rm = response.response_metadata or {}
                    tu = rm.get('token_usage') or rm.get('usage', {})
                    if tu:
                        parsed["_eval_tokens"] = {
                            "input": tu.get('prompt_tokens', tu.get('input_tokens', 0)),
                            "output": tu.get('completion_tokens', tu.get('output_tokens', 0)),
                            "total": tu.get('total_tokens', 0),
                        }
                per_model.append(parsed)
            else:
                logger.warning(f"Evaluator {model_key}: non-JSON response")
        except Exception as e:
            logger.warning(f"Evaluator {model_key} failed: {e}")

    if not per_model:
        return {
            "overall_score": "PARSE_ERROR",
            "_meta": {"models_attempted": eval_models, "models_succeeded": 0},
        }

    # Single model — recompute overall with our own math (don't trust LLM arithmetic)
    if len(per_model) == 1:
        result = per_model[0]
        _recompute_overall(result, weights)
        eval_tokens = result.pop("_eval_tokens", None)
        result["_meta"] = {
            "models_used": [result.pop("_model", eval_models[0])],
            "models_succeeded": 1,
            "consensus": "single_model",
        }
        if eval_tokens:
            result["_meta"]["eval_token_usage"] = eval_tokens
        return result

    # Multiple models — aggregate via median
    has_dimensions = any("dimensions" in r for r in per_model)
    if has_dimensions:
        return _agg_dimensions(per_model, weights)
    return _agg_scores(per_model, weights)


def _recompute_overall(result: dict, weights: dict = None):
    """Recompute overall_score from dimension/score data using structured penalties."""
    if not weights:
        return
    penalties = result.get("penalties_applied", [])

    if "dimensions" in result:
        dim_scores = {}
        for k, v in result["dimensions"].items():
            if isinstance(v, dict) and isinstance(v.get("score"), (int, float)):
                dim_scores[k] = v["score"]
        if dim_scores:
            result["overall_score"] = compute_weighted_score(dim_scores, weights, penalties)

    elif "scores" in result:
        result["overall_score"] = compute_weighted_score(result["scores"], weights, penalties)


def _collect_eval_tokens(results: list[dict]) -> dict:
    """Aggregate evaluation token usage across all evaluator models."""
    total_input = 0
    total_output = 0
    total = 0
    per_model = {}
    for r in results:
        tokens = r.get("_eval_tokens", {})
        if tokens:
            model = r.get("_model", "?")
            per_model[model] = tokens
            total_input += tokens.get("input", 0)
            total_output += tokens.get("output", 0)
            total += tokens.get("total", 0)
    if not per_model:
        return {}
    return {
        "total_input": total_input,
        "total_output": total_output,
        "total": total,
        "per_model": per_model,
    }


def _agg_dimensions(results: list[dict], weights: dict = None) -> dict:
    """Aggregate discriminator-style 'dimensions' results via median."""
    all_dims = set()
    for r in results:
        all_dims.update(r.get("dimensions", {}).keys())

    agg_dims = {}
    per_model_scores = {}

    for dim in all_dims:
        scores = []
        for r in results:
            d = r.get("dimensions", {}).get(dim, {})
            if isinstance(d, dict):
                s = d.get("score")
                if isinstance(s, (int, float)):
                    scores.append(s)
        if scores:
            median = round(statistics.median(scores), 1)
            per_model_scores[dim] = scores
            closest = min(results, key=lambda r, d=dim, m=median: abs(
                r.get("dimensions", {}).get(d, {}).get("score", 0) - m
            ))
            agg_dims[dim] = {
                **closest.get("dimensions", {}).get(dim, {}),
                "score": median,
            }

    all_h, all_p, all_s = [], [], []
    for r in results:
        all_h.extend(r.get("hallucinations", []))
        all_p.extend(r.get("penalties_applied", []))
        all_s.extend(r.get("suggestions", []))

    all_h = _dedup(all_h)
    all_s = _dedup(all_s)

    dim_scores = {k: v.get("score", 0) for k, v in agg_dims.items()}
    overall = compute_weighted_score(dim_scores, weights or {}, all_p) if weights else 0

    std_devs = [statistics.stdev(sl) for sl in per_model_scores.values() if len(sl) >= 2]
    avg_disagree = round(statistics.mean(std_devs), 2) if std_devs else 0

    eval_tokens = _collect_eval_tokens(results)

    meta = {
        "models_used": [r.get("_model", "?") for r in results],
        "models_succeeded": len(results),
        "consensus": "multi_model_median",
        "per_model_scores": per_model_scores,
        "avg_disagreement": avg_disagree,
        "agreement_level": "high" if avg_disagree < 1.0 else "medium" if avg_disagree < 2.0 else "low",
    }
    if eval_tokens:
        meta["eval_token_usage"] = eval_tokens

    return {
        "dimensions": agg_dims,
        "overall_score": overall,
        "penalties_applied": all_p,
        "hallucinations": all_h,
        "suggestions": all_s,
        "stages": agg_dims,
        "gaps": all_s,
        "_meta": meta,
    }


def _agg_scores(results: list[dict], weights: dict = None) -> dict:
    """Aggregate evaluator-style 'scores' results via median."""
    all_keys = set()
    for r in results:
        all_keys.update(r.get("scores", {}).keys())

    agg_scores = {}
    per_model_scores = {}

    for key in all_keys:
        scores = [r.get("scores", {}).get(key) for r in results
                  if isinstance(r.get("scores", {}).get(key), (int, float))]
        if scores:
            agg_scores[key] = round(statistics.median(scores), 1)
            per_model_scores[key] = scores

    all_p, all_h, all_s, all_i = [], [], [], []
    for r in results:
        all_p.extend(r.get("penalties_applied", []))
        all_h.extend(r.get("hallucinations", []))
        all_s.extend(r.get("suggestions", []))
        all_i.extend(r.get("issues", []))

    all_h = _dedup(all_h)
    all_s = _dedup(all_s)
    all_i = _dedup(all_i)

    overall = compute_weighted_score(agg_scores, weights, all_p) if weights else None
    reasoning = next((r.get("reasoning", "") for r in results if r.get("reasoning")), "")

    std_devs = [statistics.stdev(sl) for sl in per_model_scores.values() if len(sl) >= 2]
    avg_disagree = round(statistics.mean(std_devs), 2) if std_devs else 0

    eval_tokens = _collect_eval_tokens(results)

    meta = {
        "models_used": [r.get("_model", "?") for r in results],
        "models_succeeded": len(results),
        "consensus": "multi_model_median",
        "per_model_scores": per_model_scores,
        "avg_disagreement": avg_disagree,
        "agreement_level": "high" if avg_disagree < 1.0 else "medium" if avg_disagree < 2.0 else "low",
    }
    if eval_tokens:
        meta["eval_token_usage"] = eval_tokens

    result = {
        "scores": agg_scores,
        "reasoning": reasoning,
        "issues": all_i,
        "hallucinations": all_h,
        "penalties_applied": all_p,
        "suggestions": all_s,
        "_meta": meta,
    }
    if overall is not None:
        result["overall_score"] = overall
    return result


def _dedup(items: list) -> list:
    """Deduplicate list preserving order. Handles dicts via JSON serialization."""
    seen = set()
    out = []
    for item in items:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, dict) else str(item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CANARY FIXTURES & VALIDATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CANARY_STATE = {
    "strategic_plan": {
        "product_presentation_strategy": {
            "primary_offer": "PGS Moto",
            "secondary_offer": "GSM Básico",
        },
        "information_payload": {
            "adesao": "R$299,90",
            "mensalidade": "R$49,90",
            "tipo": "rastreamento com garantia de reembolso",
        },
        "key_talking_points": ["Rastreamento 24h", "Garantia de reembolso em roubo/furto"],
    },
    "operational_context": "BUDGET",
    "identified_topic": "Interesse em rastreador para moto",
    "is_sales_final_step": False,
    "is_plan_acceptable": True,
    "products_discussed": [],
    "entities_extracted": [],
    "unresolved_objections": [],
    "disclosure_checklist": [
        {"item": "Não é seguro, é rastreamento", "status": "pending"},
    ],
    "recently_sent_catalogs": [],
    "metadata": {"current_turn_number": 2},
}

CANARY_HISTORY = [
    {"status": "received", "text": "oi, quero um rastreador pra minha moto"},
]

# Good canary: factually correct, concise, proactive, WhatsApp-native
CANARY_GOOD_RESPONSE = [
    "Boa tarde! \U0001f3cd\ufe0f Pra moto, o melhor é o PGS Moto — rastreamento 24h com garantia de reembolso se roubar/furtar.",
    "Adesão R$299,90 e mensalidade R$49,90. Quer saber mais sobre como funciona? \U0001f60a",
]

# Bad canary: hallucinated prices, says "seguro", verbose, invented promos
CANARY_BAD_RESPONSE = [
    "Olá! Muito obrigado por entrar em contato com a Global System!",
    "Entendo que você está procurando um rastreador para sua moto. É muito importante proteger "
    "seu patrimônio nos dias de hoje, principalmente com os índices de criminalidade.",
    "Nós temos o nosso seguro completo PGS Premium por apenas R$29,90/mês, que oferece cobertura "
    "total contra roubo, furto e acidentes, incluindo assistência 24 horas com guincho ilimitado.",
    "Além disso, estamos com uma promoção especial de 3 meses grátis na primeira contratação!",
    "Também posso oferecer nosso plano Super Premium com rastreamento por satélite militar "
    "e seguro de vida incluso por R$59,90/mês.",
    "Posso te ajudar com mais alguma informação?",
]


def validate_canary_scores(
    good_score, bad_score,
    expected_good: tuple = (6.5, 10.0),
    expected_bad: tuple = (0, 4.0),
) -> dict:
    """Validate canary evaluation results meet expected ranges.

    Args:
        good_score: Score for the known-good canary response
        bad_score: Score for the known-bad canary response
        expected_good: (min, max) acceptable range for good canary
        expected_bad: (min, max) acceptable range for bad canary

    Returns:
        {"passed": bool, "good_score": ..., "bad_score": ..., "issues": [...]}
    """
    if not isinstance(good_score, (int, float)) or not isinstance(bad_score, (int, float)):
        return {
            "passed": False,
            "reason": "Non-numeric canary score",
            "good_score": good_score,
            "bad_score": bad_score,
        }

    good_ok = expected_good[0] <= good_score <= expected_good[1]
    bad_ok = expected_bad[0] <= bad_score <= expected_bad[1]
    order_ok = good_score > bad_score

    issues = []
    if not good_ok:
        issues.append(f"Good canary {good_score} outside expected {expected_good}")
    if not bad_ok:
        issues.append(f"Bad canary {bad_score} outside expected {expected_bad}")
    if not order_ok:
        issues.append(f"Good ({good_score}) should score higher than bad ({bad_score})")

    return {
        "passed": good_ok and bad_ok and order_ok,
        "good_score": good_score,
        "bad_score": bad_score,
        "expected_good": expected_good,
        "expected_bad": expected_bad,
        "ordering_correct": order_ok,
        "issues": issues,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PROMPT STALENESS DETECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _compute_prompt_hashes() -> dict[str, str]:
    """Compute SHA-256 hashes of agent prompt files."""
    hashes = {}
    for fname in ('agents.yaml', 'agents.refactored.yaml'):
        fpath = os.path.join(_PROMPTS_DIR, fname)
        if os.path.isfile(fpath):
            try:
                with open(fpath, 'rb') as f:
                    hashes[fname] = hashlib.sha256(f.read()).hexdigest()[:16]
            except Exception:
                pass
    return hashes


_PROMPT_HASHES = _compute_prompt_hashes()


def check_prompt_staleness() -> dict:
    """Check if agent prompts changed since module load (evaluator rules may be stale).

    Returns:
        {"stale": bool, "changed_files": [...], "warning": str | None}
    """
    current = _compute_prompt_hashes()
    changed = [f for f, h in _PROMPT_HASHES.items() if current.get(f) != h]
    return {
        "stale": len(changed) > 0,
        "changed_files": changed,
        "warning": (
            "Evaluator rules may be outdated — prompt files changed since load"
            if changed else None
        ),
    }
