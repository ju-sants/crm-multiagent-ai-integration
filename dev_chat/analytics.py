"""
Dev Chat Analytics — Runtime instrumentation for crew/agent performance tracking.

Monkey-patches CrewAI's Crew.kickoff() to capture timing, model used, and errors.
Stores metrics in Redis for retrieval via API.
"""

import json
import time
from datetime import datetime, timezone
from app.services.redis_service import get_redis
from app.core.logger import get_logger

logger = get_logger(__name__)
redis_client = get_redis()

_installed = False
_original_kickoff = None


def install_analytics():
    """Install the Crew.kickoff() monkey-patch for analytics tracking."""
    global _installed, _original_kickoff
    if _installed:
        return

    from crewai import Crew
    _original_kickoff = Crew.kickoff
    Crew.kickoff = _patched_kickoff
    _installed = True
    logger.info("[DEV ANALYTICS] Crew.kickoff() instrumentation installed")


def _patched_kickoff(self, inputs=None):
    """Instrumented Crew.kickoff() — captures timing and stores analytics."""
    contact_id = (inputs or {}).get('contact_id', 'unknown')
    is_benchmark = (inputs or {}).pop('_benchmark', False)

    agent_name = 'unknown'
    model_name = 'unknown'

    if self.agents:
        agent_name = (self.agents[0].role or 'unknown')[:80]
        try:
            llm = self.agents[0].llm
            if hasattr(llm, 'model'):
                model_name = llm.model
            elif hasattr(llm, 'model_name'):
                model_name = llm.model_name
        except Exception:
            pass

    start = time.time()
    error_msg = None
    result = None
    status = 'success'

    try:
        result = _original_kickoff(self, inputs=inputs)
    except Exception as e:
        status = 'error'
        error_msg = str(e)[:300]
        raise
    finally:
        duration = time.time() - start

        metric = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "contact_id": contact_id,
            "agent": agent_name,
            "model": model_name,
            "duration_s": round(duration, 3),
            "status": status,
        }

        if is_benchmark:
            metric["benchmark"] = True

        if error_msg:
            metric["error"] = error_msg

        if result and hasattr(result, 'token_usage') and result.token_usage:
            tu = result.token_usage
            metric["tokens"] = {
                "total": getattr(tu, 'total_tokens', None),
                "prompt": getattr(tu, 'prompt_tokens', None),
                "completion": getattr(tu, 'completion_tokens', None),
            }

        _store_metric(contact_id, metric)

    return result


def _store_metric(contact_id: str, metric: dict):
    """Store a metric in Redis lists."""
    metric_json = json.dumps(metric)
    pipe = redis_client.pipeline()
    pipe.rpush(f"dev:analytics:{contact_id}", metric_json)
    pipe.rpush("dev:analytics:global", metric_json)
    # Keep last 5000 entries globally
    pipe.ltrim("dev:analytics:global", -5000, -1)
    pipe.execute()

    logger.info(f"[ANALYTICS] {metric['agent'][:40]} | {metric['model']} | "
                f"{metric['duration_s']}s | {metric['status']}")


# --- Query Functions ---

def get_session_analytics(contact_id: str) -> list:
    """Get all analytics for a specific session/contact."""
    raw = redis_client.lrange(f"dev:analytics:{contact_id}", 0, -1)
    return [json.loads(m) for m in raw]


def get_global_analytics(limit: int = 500) -> list:
    """Get recent global analytics."""
    raw = redis_client.lrange("dev:analytics:global", -limit, -1)
    return [json.loads(m) for m in raw]


def get_analytics_summary() -> dict:
    """Compute aggregate summary of all analytics."""
    metrics = get_global_analytics(limit=10000)

    by_agent = {}
    by_model = {}

    for m in metrics:
        if m.get('benchmark'):
            continue  # Exclude benchmark runs from summary

        agent = m.get('agent', 'unknown')
        model = m.get('model', 'unknown')
        duration = m.get('duration_s', 0)
        status = m.get('status', 'unknown')

        for key, store in [(agent, by_agent), (model, by_model)]:
            if key not in store:
                store[key] = {"count": 0, "total_time": 0, "errors": 0, "times": []}
            store[key]["count"] += 1
            store[key]["total_time"] += duration
            store[key]["times"].append(duration)
            if status == 'error':
                store[key]["errors"] += 1

    def _compute_stats(store):
        for val in store.values():
            times = sorted(val.pop("times"))
            n = len(times)
            val["avg_time"] = round(val["total_time"] / val["count"], 3) if val["count"] else 0
            val["total_time"] = round(val["total_time"], 3)
            val["min_time"] = round(times[0], 3) if times else 0
            val["max_time"] = round(times[-1], 3) if times else 0
            val["p50_time"] = round(times[n // 2], 3) if times else 0
            val["p95_time"] = round(times[int(n * 0.95)], 3) if n > 1 else val["max_time"]

    _compute_stats(by_agent)
    _compute_stats(by_model)

    return {
        "total_executions": len(metrics),
        "by_agent": by_agent,
        "by_model": by_model,
    }


def clear_session_analytics(contact_id: str):
    redis_client.delete(f"dev:analytics:{contact_id}")


def clear_all_analytics():
    keys = redis_client.keys("dev:analytics:*")
    if keys:
        redis_client.delete(*keys)
