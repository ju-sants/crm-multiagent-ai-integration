"""
Dev Chat Benchmarks — Model comparison engine.

Run the same agent/context through different LLMs and compare quality + speed.
Supports isolated execution (no side effects on state) for controlled comparison.
"""

import json
import os
import random
import threading
import time
import uuid
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from crewai import Crew, Process, Agent

from app.config.llm_config import AVAILABLE_MODELS, DEFAULT_AGENT_MODELS, create_llm, create_crewai_llm
from app.services.redis_service import get_redis
from app.services.state_manager_service import StateManagerService
from app.core.logger import get_logger
from app.utils.funcs.funcs import distill_conversation_state

logger = get_logger(__name__)
redis_client = get_redis()
state_manager = StateManagerService()


def _publish_progress(run_id: str, event_type: str, data: dict):
    """Publish a benchmark progress event to Redis Pub/Sub."""
    payload = json.dumps({"type": event_type, "run_id": run_id, **data})
    redis_client.publish(f"bench:progress:{run_id}", payload)


# ── Checkpoint system ──

def _save_checkpoint(run_id: str, checkpoint: dict):
    """Save benchmark checkpoint to Redis (expires after 24h)."""
    redis_client.set(f"bench:checkpoint:{run_id}", json.dumps(checkpoint), ex=86400)


def _load_checkpoint(run_id: str) -> dict | None:
    """Load a benchmark checkpoint from Redis."""
    raw = redis_client.get(f"bench:checkpoint:{run_id}")
    return json.loads(raw) if raw else None


def _delete_checkpoint(run_id: str):
    """Remove checkpoint after successful completion."""
    redis_client.delete(f"bench:checkpoint:{run_id}")


def get_checkpoint(run_id: str) -> dict | None:
    """Public accessor for checkpoint data."""
    return _load_checkpoint(run_id)


def list_checkpoints() -> list:
    """List all active benchmark checkpoints."""
    keys = redis_client.keys("bench:checkpoint:*")
    result = []
    for key in keys:
        rid = key.split(":")[-1]
        cp = _load_checkpoint(rid)
        if cp:
            result.append({
                "run_id": rid,
                "mode": cp.get("mode"),
                "total": cp.get("total", 0),
                "completed": len(cp.get("completed_results", [])),
                "errors": sum(1 for r in cp.get("completed_results", []) if r.get("status") == "error"),
                "remaining": len(cp.get("remaining_items", [])),
                "config": cp.get("config", {}),
                "timestamp": cp.get("timestamp"),
            })
    return result


BENCHMARKABLE_AGENTS = {
    "CommunicationAgent": {
        "description": "Generates the final response to the customer",
        "uses_tools": True,
        "tool_names": ["drill_down_topic_tool"],
    },
    "StrategicAdvisor": {
        "description": "Develops sales/support strategy",
        "uses_tools": True,
        "tool_names": ["knowledge_service_tool", "drill_down_topic_tool"],
    },
    "IncrementalStrategicPlannerAgent": {
        "description": "Refines existing strategy incrementally",
        "uses_tools": True,
        "tool_names": ["knowledge_service_tool", "drill_down_topic_tool"],
    },
    "RoutingAgent": {
        "description": "Routes and classifies incoming messages",
        "uses_tools": False,
    },
}


def _expand_model_params(models: list, model_params: dict | None) -> list:
    """Expand per-model parameter configs (with ranges) into flat list of (model, params) tuples.

    If a parameter value is a list, it creates one variant per value (cartesian product).
    Example:
        models = ["xai/grok-3-mini-fast"]
        model_params = {"xai/grok-3-mini-fast": {"temperature": [0.1, 0.5], "top_p": 0.9}}
    Returns:
        [("xai/grok-3-mini-fast", {"temperature": 0.1, "top_p": 0.9}),
         ("xai/grok-3-mini-fast", {"temperature": 0.5, "top_p": 0.9})]
    """
    if not model_params:
        return [(m, {}) for m in models]

    from itertools import product

    result = []
    for model_key in models:
        params = model_params.get(model_key, {})
        if not params:
            result.append((model_key, {}))
            continue

        # Separate range params (list values) from scalar params
        range_keys = []
        range_values = []
        scalar_params = {}
        for k, v in params.items():
            if isinstance(v, list) and len(v) > 0:
                range_keys.append(k)
                range_values.append(v)
            elif v is not None:
                scalar_params[k] = v

        if not range_keys:
            result.append((model_key, scalar_params))
        else:
            for combo in product(*range_values):
                resolved = dict(scalar_params)
                for i, k in enumerate(range_keys):
                    resolved[k] = combo[i]
                result.append((model_key, resolved))

    return result


def _resolve_llm_params(work_item: dict, fallback_temp=None, fallback_top_p=None, fallback_max_tokens=None) -> dict:
    """Extract LLM params from a work item, with optional global fallbacks."""
    item_params = work_item.get("llm_params", {})
    return {
        "temperature": item_params.get("temperature", fallback_temp),
        "top_p": item_params.get("top_p", fallback_top_p),
        "max_tokens": item_params.get("max_tokens", fallback_max_tokens),
    }


def _get_tools(tool_names: list):
    """Load tool instances by name."""
    tools = []
    if "knowledge_service_tool" in tool_names:
        from app.tools.knowledge_tools import knowledge_service_tool
        tools.append(knowledge_service_tool)
    if "drill_down_topic_tool" in tool_names:
        from app.tools.knowledge_tools import drill_down_topic_tool
        tools.append(drill_down_topic_tool)
    return tools


def _build_inputs(agent_name: str, contact_id: str) -> dict:
    """Build the input dict for an agent, replicating crew file logic.

    NOTE: This mirrors the input-building in strategy.py, communication.py, etc.
    If crew inputs change, this must be updated to match.
    """
    state, _ = state_manager.get_state(contact_id)

    profile = redis_client.get(f"{contact_id}:customer_profile")
    shorterm_history = redis_client.get(f"shorterm_history:{contact_id}")

    longterm_history_json = redis_client.get(f"longterm_history:{contact_id}")
    longterm_history = json.loads(longterm_history_json) if longterm_history_json else {}
    topic_details = longterm_history.get("topic_details", [])[-10:]
    longterm_str = "\n\n".join([
        f"Topic: {t.get('title', 'N/A')}\nSummary: {t.get('summary', 'N/A')}"
        for t in topic_details
    ])

    client_messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)

    conversation_state_distilled = distill_conversation_state(state, agent_name)

    if agent_name == "CommunicationAgent":
        strategic_plan = conversation_state_distilled.pop("strategic_plan", None)
        disclosure_checklist = conversation_state_distilled.pop("disclosure_checklist", None)
        system_op_output = redis_client.get(f"{contact_id}:last_system_operation_output")
        recently_sent = redis_client.lrange(f"{contact_id}:sended_catalogs", 0, -1)

        return {
            "contact_id": contact_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategic_plan": json.dumps(strategic_plan),
            "last_system_operation": system_op_output or "{}",
            "customer_profile": str(profile),
            "conversation_state": str(conversation_state_distilled),
            "longterm_history": longterm_str,
            "shorterm_history": str(shorterm_history),
            "recently_sent_catalogs": ", ".join(recently_sent),
            "disclosure_checklist": json.dumps(disclosure_checklist),
            "client_message": "\n".join(client_messages),
            "operational_context": state.operational_context or "",
            "identified_topic": state.identified_topic or "",
            "turn": state.metadata.current_turn_number,
            "_benchmark": True,
        }

    elif agent_name in ("StrategicAdvisor", "IncrementalStrategicPlannerAgent"):
        return {
            "contact_id": contact_id,
            "longterm_history": longterm_str,
            "shorterm_history": str(shorterm_history),
            "conversation_state": json.dumps(conversation_state_distilled),
            "profile_customer_task_output": str(profile),
            "client_message": "\n".join(client_messages),
            "operational_context": state.operational_context or "",
            "identified_topic": state.identified_topic or "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "turn": state.metadata.current_turn_number,
            "_benchmark": True,
        }

    elif agent_name == "RoutingAgent":
        return {
            "contact_id": contact_id,
            "client_message": "\n".join(client_messages),
            "conversation_state": json.dumps(conversation_state_distilled),
            "longterm_history": longterm_str,
            "shorterm_history": str(shorterm_history),
            "_benchmark": True,
        }

    return {"contact_id": contact_id, "_benchmark": True}


def _create_agent_and_task(agent_name: str, llm):
    """Create agent + task for a given agent name and LLM."""
    from app.crews.agents_definitions.obj_declarations.agent_declaration import (
        get_strategic_advisor_agent,
        get_communication_agent,
        get_incremental_strategic_planner_agent,
    )
    from app.crews.agents_definitions.obj_declarations.tasks_declaration import (
        create_develop_strategy_task,
        create_communication_task,
        create_refine_strategy_task,
        create_strategy_agent_task,
    )

    agent_cfg = BENCHMARKABLE_AGENTS.get(agent_name, {})
    tools = _get_tools(agent_cfg.get("tool_names", []))

    mapping = {
        "CommunicationAgent": (get_communication_agent, create_communication_task),
        "StrategicAdvisor": (get_strategic_advisor_agent, create_develop_strategy_task),
        "IncrementalStrategicPlannerAgent": (get_incremental_strategic_planner_agent, create_refine_strategy_task),
    }

    if agent_name in mapping:
        get_agent_fn, create_task_fn = mapping[agent_name]
        agent = get_agent_fn(llm)
        task = create_task_fn(agent)
        return agent, task

    if agent_name == "RoutingAgent":
        # RoutingAgent doesn't accept LLM override. Create directly with YAML prompts.
        prompts_path = os.environ.get('AGENTS_PROMPT_FILE') or os.path.join(
            os.path.dirname(__file__), '..', 'app', 'crews',
            'agents_definitions', 'prompts', 'agents.yaml'
        )
        tasks_path = os.environ.get('TASKS_PROMPT_FILE') or os.path.join(
            os.path.dirname(__file__), '..', 'app', 'crews',
            'agents_definitions', 'prompts', 'tasks.yaml'
        )
        with open(prompts_path, 'r', encoding='utf-8') as f:
            agent_prompts = yaml.safe_load(f)
        with open(tasks_path, 'r', encoding='utf-8') as f:
            task_prompts = yaml.safe_load(f)

        ra = agent_prompts.get('RoutingAgent', {})
        agent = Agent(
            role=ra.get('role', ''),
            goal=ra.get('goal', ''),
            backstory=ra.get('backstory', ''),
            llm=llm,
            verbose=True,
        )
        task = create_strategy_agent_task(agent)
        return agent, task

    raise ValueError(f"No factory for agent: {agent_name}")


def _capture_prompt(agent, task, inputs: dict) -> dict:
    """Capture the fully interpolated prompt as the LLM would see it.

    Returns the agent's system prompt (role+goal+backstory) and the task
    description with all {variables} filled in.
    """
    # Agent system context
    agent_prompt = {
        "role": agent.role or "",
        "goal": agent.goal or "",
        "backstory": (agent.backstory or "")[:2000],
    }

    # Task description with interpolated variables
    desc = task.description or ""
    expected = task.expected_output or ""
    for key, val in inputs.items():
        placeholder = "{" + key + "}"
        val_str = str(val) if val is not None else ""
        desc = desc.replace(placeholder, val_str[:500])
        expected = expected.replace(placeholder, val_str[:500])

    return {
        "agent": agent_prompt,
        "task_description": desc[:3000],
        "expected_output": expected[:1500],
        "input_keys": list(inputs.keys()),
    }


# ── Shared execution helpers ──

def _execute_work_item(
    agent_name: str,
    inputs: dict,
    work_item: dict,
    contact_id: str,
    temperature: float = None,
    top_p: float = None,
    max_tokens: int = None,
    run_discriminator: bool = True,
    capture_prompt: bool = False,
    scenario_name: str = None,
    extra_entry_fields: dict = None,
) -> dict:
    """Execute a single benchmark work item (create LLM -> run crew -> evaluate).

    Returns the result entry dict with status 'success' or 'error'.
    """
    model_key = work_item["model"]
    iteration = work_item["iteration"]

    base_entry = {"model": model_key, "iteration": iteration}
    if extra_entry_fields:
        base_entry.update(extra_entry_fields)

    try:
        params = _resolve_llm_params(work_item, temperature, top_p, max_tokens)
        llm = create_crewai_llm(model_key, **params)
        agent, task = _create_agent_and_task(agent_name, llm)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)

        run_inputs = dict(inputs)
        start = time.time()
        result = crew.kickoff(inputs=run_inputs)
        duration = time.time() - start

        entry = {
            **base_entry,
            "llm_params": params,
            "duration_s": round(duration, 3),
            "status": "success",
            "output_preview": (result.raw or "")[:2000],
        }

        if hasattr(result, 'token_usage') and result.token_usage:
            tu = result.token_usage
            entry["tokens"] = {
                "total": getattr(tu, 'total_tokens', None),
                "prompt": getattr(tu, 'prompt_tokens', None),
                "completion": getattr(tu, 'completion_tokens', None),
            }

        if capture_prompt:
            entry["interpolated_prompt"] = _capture_prompt(agent, task, run_inputs)

        if run_discriminator:
            try:
                from dev_chat.evaluators import evaluate_agent_output
                from dev_chat.synthetic_states import load_scenario_evaluation_focus
                state, _ = state_manager.get_state(contact_id)
                scenario_eval_focus = load_scenario_evaluation_focus(scenario_name) if scenario_name else None
                analysis = evaluate_agent_output(
                    agent_name=agent_name,
                    output=result.raw or "",
                    inputs=run_inputs,
                    conversation_state=state.model_dump(),
                    evaluation_focus=scenario_eval_focus,
                )
                entry["evaluation"] = analysis
            except Exception as e:
                entry["evaluation_error"] = str(e)[:200]

        return entry

    except Exception as e:
        logger.error(f"[BENCHMARK] {agent_name}/{model_key}/#{iteration} failed: {e}", exc_info=True)
        return {
            **base_entry,
            "duration_s": 0,
            "status": "error",
            "error": str(e)[:500],
        }


def _aggregate_single_results(models: list, all_run_entries: list) -> list:
    """Aggregate run entries into per-model summaries."""
    results = []
    for model_key in models:
        model_runs = [e for e in all_run_entries if e["model"] == model_key]
        successful = [r for r in model_runs if r["status"] == "success"]
        model_summary = {
            "model": model_key,
            "iterations": len(model_runs),
            "successes": len(successful),
            "errors": len(model_runs) - len(successful),
            "runs": model_runs,
        }
        if successful:
            times = sorted(r["duration_s"] for r in successful)
            scores = [
                r["evaluation"]["overall_score"]
                for r in successful
                if "evaluation" in r and isinstance(r["evaluation"].get("overall_score"), (int, float))
            ]
            model_summary["timing"] = {
                "avg": round(sum(times) / len(times), 3),
                "min": times[0],
                "max": times[-1],
                "p50": times[len(times) // 2],
            }
            if scores:
                model_summary["quality"] = {
                    "avg_score": round(sum(scores) / len(scores), 1),
                    "min_score": min(scores),
                    "max_score": max(scores),
                }
            # Token usage aggregation (agent tokens)
            all_tokens = [r["tokens"] for r in successful if r.get("tokens")]
            if all_tokens:
                model_summary["token_usage"] = {
                    "avg_total": round(sum(t.get("total", 0) or 0 for t in all_tokens) / len(all_tokens)),
                    "avg_prompt": round(sum(t.get("prompt", 0) or 0 for t in all_tokens) / len(all_tokens)),
                    "avg_completion": round(sum(t.get("completion", 0) or 0 for t in all_tokens) / len(all_tokens)),
                    "sum_total": sum(t.get("total", 0) or 0 for t in all_tokens),
                }
            # Evaluator token usage aggregation
            eval_tokens = [
                r["evaluation"]["_meta"]["eval_token_usage"]
                for r in successful
                if r.get("evaluation", {}).get("_meta", {}).get("eval_token_usage")
            ]
            if eval_tokens:
                model_summary["eval_token_usage"] = {
                    "sum_total": sum(t.get("total", 0) for t in eval_tokens),
                    "avg_total": round(sum(t.get("total", 0) for t in eval_tokens) / len(eval_tokens)),
                }
        results.append(model_summary)
    return results


def run_benchmark(
    agent_name: str,
    contact_id: str,
    models: list,
    temperature: float = None,
    top_p: float = None,
    max_tokens: int = None,
    model_params: dict = None,
    run_discriminator: bool = True,
    iterations: int = 1,
    synthetic_scenario: str = None,
    capture_prompt: bool = False,
    run_id: str = None,
    max_workers: int = None,
) -> dict:
    """
    Run the same agent with multiple models and compare.

    Args:
        agent_name: Which agent to benchmark
        contact_id: Session/contact with existing state (ignored if synthetic_scenario)
        models: List of model keys to test
        temperature: Optional global LLM temperature override (fallback)
        top_p: Optional global top_p (fallback)
        max_tokens: Optional global max_tokens (fallback)
        model_params: Per-model params dict, supporting ranges.
            e.g. {"xai/grok-3-mini-fast": {"temperature": [0.1, 0.5], "top_p": 0.9}}
        run_discriminator: Run per-agent quality evaluation
        iterations: How many times to run each model (for statistical significance)
        synthetic_scenario: Name of a synthetic state to inject (overrides contact_id)
        capture_prompt: Include the fully interpolated prompt in results

    Returns comparison dict with timing, output, and quality analysis per model.
    """
    if agent_name not in BENCHMARKABLE_AGENTS:
        return {"error": f"Agent '{agent_name}' not benchmarkable. Available: {list(BENCHMARKABLE_AGENTS.keys())}"}

    # Inject synthetic state if requested
    if synthetic_scenario:
        from dev_chat.synthetic_states import inject_synthetic_state
        contact_id = inject_synthetic_state(synthetic_scenario)

    inputs = _build_inputs(agent_name, contact_id)
    run_id = run_id or str(uuid.uuid4())[:8]
    results = []

    # Expand per-model params (with ranges) into flat work items
    expanded_models = _expand_model_params(models, model_params)

    # Build work items for single benchmark
    work_items = []
    for model_key, resolved_params in expanded_models:
        for iteration in range(1, iterations + 1):
            work_items.append({"model": model_key, "iteration": iteration, "llm_params": resolved_params})

    total_runs = len(work_items)
    successes = 0
    errors = 0

    # Save initial checkpoint
    _save_checkpoint(run_id, {
        "mode": "single",
        "config": {
            "agent": agent_name, "contact_id": contact_id,
            "models": models, "temperature": temperature,
            "top_p": top_p, "max_tokens": max_tokens,
            "model_params": model_params,
            "run_discriminator": run_discriminator, "iterations": iterations,
            "synthetic_scenario": synthetic_scenario, "capture_prompt": capture_prompt,
        },
        "total": total_runs,
        "remaining_items": work_items,
        "completed_results": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    _publish_progress(run_id, "started", {
        "mode": "single", "agent": agent_name, "total": total_runs,
        "models": models, "iterations": iterations,
        "scenario": synthetic_scenario,
    })

    all_run_entries = []
    workers = max_workers or int(os.environ.get("BENCHMARK_MAX_WORKERS", 4))

    if workers <= 1:
        # Sequential execution (original behaviour)
        current_run = 0
        for wi_idx, work_item in enumerate(work_items):
            model_key = work_item["model"]
            iteration = work_item["iteration"]
            current_run += 1
            iter_label = f"{run_id}/{model_key}/{iteration}" if iterations > 1 else f"{run_id}/{model_key}"
            logger.info(f"[BENCHMARK {iter_label}] {agent_name}")

            _publish_progress(run_id, "run_start", {
                "current": current_run, "total": total_runs,
                "agent": agent_name, "model": model_key,
                "iteration": iteration, "label": iter_label,
            })

            entry = _execute_work_item(
                agent_name=agent_name, inputs=inputs, work_item=work_item,
                contact_id=contact_id, temperature=temperature, top_p=top_p,
                max_tokens=max_tokens, run_discriminator=run_discriminator,
                capture_prompt=capture_prompt, scenario_name=synthetic_scenario,
            )
            all_run_entries.append(entry)

            if entry["status"] == "success":
                successes += 1
            else:
                errors += 1

            _publish_progress(run_id, "run_complete" if entry["status"] == "success" else "run_error", {
                "current": current_run, "total": total_runs,
                "agent": agent_name, "model": model_key,
                "iteration": iteration,
                "duration_s": entry.get("duration_s", 0),
                "score": entry.get("evaluation", {}).get("overall_score"),
                "successes": successes, "errors": errors,
            })

            _save_checkpoint(run_id, {
                "mode": "single",
                "config": {
                    "agent": agent_name, "contact_id": contact_id,
                    "models": models, "temperature": temperature,
                    "top_p": top_p, "max_tokens": max_tokens,
                    "model_params": model_params,
                    "run_discriminator": run_discriminator, "iterations": iterations,
                    "synthetic_scenario": synthetic_scenario, "capture_prompt": capture_prompt,
                },
                "total": total_runs,
                "remaining_items": work_items[wi_idx + 1:],
                "completed_results": all_run_entries,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    else:
        # Concurrent execution
        lock = threading.Lock()
        completed_indices = set()

        def _on_item_done(future, work_item, wi_idx):
            nonlocal successes, errors
            entry = future.result()
            model_key = work_item["model"]
            iteration = work_item["iteration"]

            with lock:
                all_run_entries.append(entry)
                completed_indices.add(wi_idx)
                if entry["status"] == "success":
                    successes += 1
                else:
                    errors += 1
                current = len(all_run_entries)
                remaining = [work_items[i] for i in range(len(work_items)) if i not in completed_indices]
                snapshot = list(all_run_entries)
                s_count, e_count = successes, errors

            _publish_progress(run_id, "run_complete" if entry["status"] == "success" else "run_error", {
                "current": current, "total": total_runs,
                "agent": agent_name, "model": model_key,
                "iteration": iteration,
                "duration_s": entry.get("duration_s", 0),
                "score": entry.get("evaluation", {}).get("overall_score"),
                "successes": s_count, "errors": e_count,
            })

            _save_checkpoint(run_id, {
                "mode": "single",
                "config": {
                    "agent": agent_name, "contact_id": contact_id,
                    "models": models, "temperature": temperature,
                    "top_p": top_p, "max_tokens": max_tokens,
                    "model_params": model_params,
                    "run_discriminator": run_discriminator, "iterations": iterations,
                    "synthetic_scenario": synthetic_scenario, "capture_prompt": capture_prompt,
                },
                "total": total_runs,
                "remaining_items": remaining,
                "completed_results": snapshot,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        logger.info(f"[BENCHMARK {run_id}] Running {total_runs} items concurrently (max_workers={workers})")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for wi_idx, work_item in enumerate(work_items):
                future = executor.submit(
                    _execute_work_item,
                    agent_name=agent_name, inputs=inputs, work_item=work_item,
                    contact_id=contact_id, temperature=temperature, top_p=top_p,
                    max_tokens=max_tokens, run_discriminator=run_discriminator,
                    capture_prompt=capture_prompt, scenario_name=synthetic_scenario,
                )
                futures[future] = (work_item, wi_idx)

            for future in as_completed(futures):
                work_item, wi_idx = futures[future]
                _on_item_done(future, work_item, wi_idx)

    # Aggregate into model summaries
    results = _aggregate_single_results(models, all_run_entries)

    benchmark_result = {
        "run_id": run_id,
        "agent": agent_name,
        "contact_id": contact_id,
        "synthetic_scenario": synthetic_scenario,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "models_tested": len(models),
        "iterations": iterations,
        "results": results,
    }

    redis_client.rpush("dev:benchmarks:results", json.dumps(benchmark_result))
    redis_client.ltrim("dev:benchmarks:results", -100, -1)
    _delete_checkpoint(run_id)

    _publish_progress(run_id, "finished", {
        "successes": successes, "errors": errors, "total": total_runs,
    })

    return benchmark_result


def resume_benchmark(run_id: str, new_run_id: str = None) -> dict:
    """Resume a benchmark from its last checkpoint.

    Loads remaining work items and completed results from the checkpoint,
    continues execution, and produces the same output format as the
    original run.
    """
    checkpoint = _load_checkpoint(run_id)
    if not checkpoint:
        return {"error": f"No checkpoint found for run_id '{run_id}'. It may have expired or already completed."}

    mode = checkpoint.get("mode")
    config = checkpoint.get("config", {})
    remaining = checkpoint.get("remaining_items", [])
    completed = checkpoint.get("completed_results", [])
    original_total = checkpoint.get("total", 0)

    if not remaining:
        _delete_checkpoint(run_id)
        return {"error": "Checkpoint has no remaining items — the benchmark already completed."}

    resume_id = new_run_id or str(uuid.uuid4())[:8]

    if mode == "single":
        return _resume_single(resume_id, run_id, config, remaining, completed, original_total)
    elif mode == "matrix":
        return _resume_matrix(resume_id, run_id, config, remaining, completed, original_total)
    else:
        return {"error": f"Unknown checkpoint mode: {mode}"}


def _resume_single(resume_id, original_run_id, config, remaining_items, completed_results, original_total):
    """Resume a single-agent benchmark from checkpoint."""
    agent_name = config["agent"]
    contact_id = config.get("contact_id")
    models = config["models"]
    temperature = config.get("temperature")
    top_p = config.get("top_p")
    max_tokens = config.get("max_tokens")
    run_discriminator = config.get("run_discriminator", True)
    iterations = config.get("iterations", 1)
    synthetic_scenario = config.get("synthetic_scenario")
    capture_prompt = config.get("capture_prompt", False)

    if synthetic_scenario:
        from dev_chat.synthetic_states import inject_synthetic_state
        contact_id = inject_synthetic_state(synthetic_scenario)

    inputs = _build_inputs(agent_name, contact_id)

    all_run_entries = list(completed_results)
    successes = sum(1 for r in all_run_entries if r.get("status") == "success")
    errors = sum(1 for r in all_run_entries if r.get("status") == "error")
    completed_so_far = len(all_run_entries)

    _publish_progress(resume_id, "started", {
        "mode": "single", "agent": agent_name, "total": original_total,
        "models": models, "iterations": iterations,
        "scenario": synthetic_scenario,
        "resumed_from": original_run_id,
        "already_completed": completed_so_far,
    })

    for wi_idx, work_item in enumerate(remaining_items):
        model_key = work_item["model"]
        iteration = work_item["iteration"]
        current_run = completed_so_far + wi_idx + 1
        iter_label = f"{resume_id}/{model_key}/{iteration}"
        logger.info(f"[BENCHMARK RESUME {iter_label}] {agent_name} ({current_run}/{original_total})")

        _publish_progress(resume_id, "run_start", {
            "current": current_run, "total": original_total,
            "agent": agent_name, "model": model_key,
            "iteration": iteration, "label": iter_label,
        })

        entry = _execute_work_item(
            agent_name=agent_name, inputs=inputs, work_item=work_item,
            contact_id=contact_id, temperature=temperature, top_p=top_p,
            max_tokens=max_tokens, run_discriminator=run_discriminator,
            capture_prompt=capture_prompt, scenario_name=synthetic_scenario,
        )
        all_run_entries.append(entry)

        if entry["status"] == "success":
            successes += 1
            _publish_progress(resume_id, "run_complete", {
                "current": current_run, "total": original_total,
                "agent": agent_name, "model": model_key,
                "iteration": iteration, "duration_s": entry["duration_s"],
                "score": entry.get("evaluation", {}).get("overall_score"),
                "successes": successes, "errors": errors,
            })
        else:
            errors += 1
            _publish_progress(resume_id, "run_error", {
                "current": current_run, "total": original_total,
                "agent": agent_name, "model": model_key,
                "iteration": iteration,
                "error": entry.get("error", "")[:200],
                "successes": successes, "errors": errors,
            })

        # Update checkpoint under original run_id so it can be resumed again
        _save_checkpoint(original_run_id, {
            "mode": "single",
            "config": config,
            "total": original_total,
            "remaining_items": remaining_items[wi_idx + 1:],
            "completed_results": all_run_entries,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # Aggregate into model summaries
    results = _aggregate_single_results(models, all_run_entries)

    benchmark_result = {
        "run_id": resume_id,
        "resumed_from": original_run_id,
        "agent": agent_name,
        "contact_id": contact_id,
        "synthetic_scenario": config.get("synthetic_scenario"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "models_tested": len(models),
        "iterations": iterations,
        "results": results,
    }

    redis_client.rpush("dev:benchmarks:results", json.dumps(benchmark_result))
    redis_client.ltrim("dev:benchmarks:results", -100, -1)
    _delete_checkpoint(original_run_id)

    _publish_progress(resume_id, "finished", {
        "successes": successes, "errors": errors, "total": original_total,
    })

    return benchmark_result


def _resume_matrix(resume_id, original_run_id, config, remaining_items, completed_results, original_total):
    """Resume a matrix benchmark from checkpoint."""
    from dev_chat.synthetic_states import inject_synthetic_state

    temperature = config.get("temperature")
    top_p = config.get("top_p")
    max_tokens = config.get("max_tokens")
    run_discriminator = config.get("run_discriminator", True)
    capture_prompt = config.get("capture_prompt", False)
    agents = config.get("agents", [])
    models = config.get("models", [])
    scenario_names = config.get("scenarios", [])
    iterations = config.get("iterations", 1)
    scenario_order = config.get("scenario_order", "sequential")

    matrix_results = list(completed_results)
    successes = sum(1 for r in matrix_results if r.get("status") == "success")
    errors = sum(1 for r in matrix_results if r.get("status") == "error")
    completed_so_far = len(matrix_results)

    _publish_progress(resume_id, "started", {
        "mode": "matrix", "total": original_total,
        "agents": agents, "models": models,
        "scenarios": scenario_names, "iterations": iterations,
        "resumed_from": original_run_id,
        "already_completed": completed_so_far,
    })

    for idx_offset, item in enumerate(remaining_items):
        agent_name = item["agent"]
        model_key = item["model"]
        scenario_name = item["scenario"]
        iteration = item["iteration"]
        idx = completed_so_far + idx_offset + 1
        label = f"{resume_id}/{agent_name}/{model_key}/{scenario_name}/#{iteration}"
        logger.info(f"[MATRIX RESUME {label}] ({idx}/{original_total})")

        _publish_progress(resume_id, "run_start", {
            "current": idx, "total": original_total,
            "agent": agent_name, "model": model_key,
            "scenario": scenario_name, "iteration": iteration,
            "label": label,
        })

        contact_id = inject_synthetic_state(scenario_name)
        inputs = _build_inputs(agent_name, contact_id)

        entry = _execute_work_item(
            agent_name=agent_name, inputs=inputs, work_item=item,
            contact_id=contact_id, temperature=temperature, top_p=top_p,
            max_tokens=max_tokens, run_discriminator=run_discriminator,
            capture_prompt=capture_prompt, scenario_name=scenario_name,
            extra_entry_fields={"agent": agent_name, "scenario": scenario_name},
        )
        matrix_results.append(entry)

        if entry["status"] == "success":
            successes += 1
            _publish_progress(resume_id, "run_complete", {
                "current": idx, "total": original_total,
                "agent": agent_name, "model": model_key,
                "scenario": scenario_name, "iteration": iteration,
                "duration_s": entry["duration_s"],
                "score": entry.get("evaluation", {}).get("overall_score"),
                "successes": successes, "errors": errors,
            })
        else:
            errors += 1
            _publish_progress(resume_id, "run_error", {
                "current": idx, "total": original_total,
                "agent": agent_name, "model": model_key,
                "scenario": scenario_name, "iteration": iteration,
                "error": entry.get("error", "")[:200],
                "successes": successes, "errors": errors,
            })

        # Update checkpoint under original run_id
        _save_checkpoint(original_run_id, {
            "mode": "matrix",
            "config": config,
            "total": original_total,
            "remaining_items": remaining_items[idx_offset + 1:],
            "completed_results": matrix_results,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # Aggregate rankings
    rankings = _aggregate_matrix_rankings(matrix_results)

    matrix_output = {
        "run_id": resume_id,
        "resumed_from": original_run_id,
        "type": "matrix",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "agents": agents,
            "models": models,
            "scenarios": scenario_names,
            "iterations": iterations,
            "scenario_order": scenario_order,
            "total_runs": original_total,
        },
        "runs": matrix_results,
        "rankings": rankings,
    }

    redis_client.rpush("dev:benchmarks:results", json.dumps(matrix_output))
    redis_client.ltrim("dev:benchmarks:results", -100, -1)
    _delete_checkpoint(original_run_id)

    _publish_progress(resume_id, "finished", {
        "successes": successes, "errors": errors, "total": original_total,
    })

    return matrix_output


def get_benchmark_results(limit: int = 50) -> list:
    raw = redis_client.lrange("dev:benchmarks:results", -limit, -1)
    return [json.loads(r) for r in raw]


def get_model_overrides(contact_id: str = None) -> dict:
    """Get active model overrides."""
    overrides = {}
    pattern = f"dev:model_override:{'global' if not contact_id else contact_id}:*"
    keys = redis_client.keys(pattern)
    for key in keys:
        agent = key.split(":")[-1]
        overrides[agent] = redis_client.get(key)
    return overrides


def set_model_override(agent_name: str, model_key: str, contact_id: str = None):
    """Set a model override for an agent (globally or per-session)."""
    if model_key not in AVAILABLE_MODELS:
        raise ValueError(f"Unknown model: {model_key}")
    scope = contact_id or "global"
    redis_client.set(f"dev:model_override:{scope}:{agent_name}", model_key)


def remove_model_override(agent_name: str, contact_id: str = None):
    """Remove a model override."""
    scope = contact_id or "global"
    redis_client.delete(f"dev:model_override:{scope}:{agent_name}")


def get_default_model_mapping() -> dict:
    """Return the default agent → model mapping."""
    return DEFAULT_AGENT_MODELS


def discover_models() -> dict:
    """Return the AVAILABLE_MODELS registry with provider info."""
    return AVAILABLE_MODELS


def discover_agents() -> dict:
    """Return benchmarkable agents with metadata."""
    return BENCHMARKABLE_AGENTS


def run_matrix_benchmark(
    agents: list,
    models: list,
    scenarios: list,
    iterations: int = 1,
    scenario_order: str = "sequential",
    temperature: float = None,
    top_p: float = None,
    max_tokens: int = None,
    model_params: dict = None,
    run_discriminator: bool = True,
    capture_prompt: bool = False,
    run_id: str = None,
    max_workers: int = None,
) -> dict:
    """Run a full matrix benchmark: agents × models × scenarios × iterations.

    Args:
        agents: List of agent names to benchmark.
        models: List of model keys to test.
        scenarios: List of synthetic scenario names (or ["all"] for all).
        iterations: Runs per (agent, model, scenario) combination.
        scenario_order: "sequential" or "random" — controls iteration order.
        temperature: Optional LLM temperature override.
        run_discriminator: Run per-agent quality evaluation.
        capture_prompt: Include interpolated prompt in results.

    Returns a structured result with per-combination breakdowns and
    aggregated cross-model/cross-agent rankings.
    """
    from dev_chat.synthetic_states import SYNTHETIC_SCENARIOS, inject_synthetic_state

    # Validate inputs
    invalid_agents = [a for a in agents if a not in BENCHMARKABLE_AGENTS]
    if invalid_agents:
        return {"error": f"Unknown agents: {invalid_agents}. Available: {list(BENCHMARKABLE_AGENTS.keys())}"}

    invalid_models = [m for m in models if m not in AVAILABLE_MODELS]
    if invalid_models:
        return {"error": f"Unknown models: {invalid_models}. Available: {list(AVAILABLE_MODELS.keys())}"}

    # Resolve scenarios
    if scenarios == ["all"] or scenarios == "all":
        scenario_names = list(SYNTHETIC_SCENARIOS.keys())
    else:
        scenario_names = scenarios
        invalid_scenarios = [s for s in scenario_names if s not in SYNTHETIC_SCENARIOS]
        if invalid_scenarios:
            return {"error": f"Unknown scenarios: {invalid_scenarios}. Available: {list(SYNTHETIC_SCENARIOS.keys())}"}

    run_id = run_id or str(uuid.uuid4())[:8]
    matrix_results = []

    # Expand per-model params (with ranges) into flat work items
    expanded_models = _expand_model_params(models, model_params)

    # Build the work queue — all (agent, model, scenario) combinations
    work_items = []
    for agent_name in agents:
        for model_key, resolved_params in expanded_models:
            for scenario_name in scenario_names:
                for i in range(1, iterations + 1):
                    work_items.append({
                        "agent": agent_name,
                        "model": model_key,
                        "scenario": scenario_name,
                        "iteration": i,
                        "llm_params": resolved_params,
                    })

    if scenario_order == "random":
        random.shuffle(work_items)

    total = len(work_items)
    successes = 0
    errors = 0
    logger.info(f"[MATRIX {run_id}] Starting {total} benchmark runs: "
                f"{len(agents)} agents × {len(models)} models × {len(scenario_names)} scenarios × {iterations} iter")

    # Save initial checkpoint
    _save_checkpoint(run_id, {
        "mode": "matrix",
        "config": {
            "agents": agents, "models": models, "scenarios": scenario_names,
            "iterations": iterations, "scenario_order": scenario_order,
            "temperature": temperature, "top_p": top_p, "max_tokens": max_tokens,
            "model_params": model_params,
            "run_discriminator": run_discriminator,
            "capture_prompt": capture_prompt,
        },
        "total": total,
        "remaining_items": work_items,
        "completed_results": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    _publish_progress(run_id, "started", {
        "mode": "matrix", "total": total,
        "agents": agents, "models": models,
        "scenarios": scenario_names, "iterations": iterations,
    })

    workers = max_workers or int(os.environ.get("BENCHMARK_MAX_WORKERS", 4))

    def _run_matrix_item(item):
        """Execute a single matrix work item (inject state -> build inputs -> run)."""
        cid = inject_synthetic_state(item["scenario"])
        inps = _build_inputs(item["agent"], cid)
        return _execute_work_item(
            agent_name=item["agent"], inputs=inps, work_item=item,
            contact_id=cid, temperature=temperature, top_p=top_p,
            max_tokens=max_tokens, run_discriminator=run_discriminator,
            capture_prompt=capture_prompt, scenario_name=item["scenario"],
            extra_entry_fields={"agent": item["agent"], "scenario": item["scenario"]},
        )

    if workers <= 1:
        # Sequential execution
        for idx, item in enumerate(work_items, 1):
            agent_name_i = item["agent"]
            model_key = item["model"]
            scenario_name = item["scenario"]
            iteration = item["iteration"]
            label = f"{run_id}/{agent_name_i}/{model_key}/{scenario_name}/#{iteration}"
            logger.info(f"[MATRIX {label}] ({idx}/{total})")

            _publish_progress(run_id, "run_start", {
                "current": idx, "total": total,
                "agent": agent_name_i, "model": model_key,
                "scenario": scenario_name, "iteration": iteration,
                "label": label,
            })

            entry = _run_matrix_item(item)
            matrix_results.append(entry)

            if entry["status"] == "success":
                successes += 1
            else:
                errors += 1

            _publish_progress(run_id, "run_complete" if entry["status"] == "success" else "run_error", {
                "current": idx, "total": total,
                "agent": agent_name_i, "model": model_key,
                "scenario": scenario_name, "iteration": iteration,
                "duration_s": entry.get("duration_s", 0),
                "score": entry.get("evaluation", {}).get("overall_score"),
                "successes": successes, "errors": errors,
            })

            _save_checkpoint(run_id, {
                "mode": "matrix",
                "config": {
                    "agents": agents, "models": models, "scenarios": scenario_names,
                    "iterations": iterations, "scenario_order": scenario_order,
                    "temperature": temperature, "top_p": top_p, "max_tokens": max_tokens,
                    "model_params": model_params,
                    "run_discriminator": run_discriminator,
                    "capture_prompt": capture_prompt,
                },
                "total": total,
                "remaining_items": work_items[idx:],
                "completed_results": matrix_results,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    else:
        # Concurrent execution
        lock = threading.Lock()
        completed_indices = set()

        logger.info(f"[MATRIX {run_id}] Running {total} items concurrently (max_workers={workers})")

        def _on_matrix_item_done(future, item, wi_idx):
            nonlocal successes, errors
            entry = future.result()

            with lock:
                matrix_results.append(entry)
                completed_indices.add(wi_idx)
                if entry["status"] == "success":
                    successes += 1
                else:
                    errors += 1
                current = len(matrix_results)
                remaining = [work_items[i] for i in range(len(work_items)) if i not in completed_indices]
                snapshot = list(matrix_results)
                s_count, e_count = successes, errors

            _publish_progress(run_id, "run_complete" if entry["status"] == "success" else "run_error", {
                "current": current, "total": total,
                "agent": item["agent"], "model": item["model"],
                "scenario": item["scenario"], "iteration": item["iteration"],
                "duration_s": entry.get("duration_s", 0),
                "score": entry.get("evaluation", {}).get("overall_score"),
                "successes": s_count, "errors": e_count,
            })

            _save_checkpoint(run_id, {
                "mode": "matrix",
                "config": {
                    "agents": agents, "models": models, "scenarios": scenario_names,
                    "iterations": iterations, "scenario_order": scenario_order,
                    "temperature": temperature, "top_p": top_p, "max_tokens": max_tokens,
                    "model_params": model_params,
                    "run_discriminator": run_discriminator,
                    "capture_prompt": capture_prompt,
                },
                "total": total,
                "remaining_items": remaining,
                "completed_results": snapshot,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for wi_idx, item in enumerate(work_items):
                future = executor.submit(_run_matrix_item, item)
                futures[future] = (item, wi_idx)

            for future in as_completed(futures):
                item, wi_idx = futures[future]
                _on_matrix_item_done(future, item, wi_idx)

    # ── Aggregate rankings ──
    rankings = _aggregate_matrix_rankings(matrix_results)

    matrix_output = {
        "run_id": run_id,
        "type": "matrix",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "agents": agents,
            "models": models,
            "scenarios": scenario_names,
            "iterations": iterations,
            "scenario_order": scenario_order,
            "model_params": model_params,
            "total_runs": total,
        },
        "runs": matrix_results,
        "rankings": rankings,
    }

    redis_client.rpush("dev:benchmarks:results", json.dumps(matrix_output))
    redis_client.ltrim("dev:benchmarks:results", -100, -1)
    _delete_checkpoint(run_id)

    _publish_progress(run_id, "finished", {
        "successes": successes, "errors": errors, "total": total,
    })

    return matrix_output


def _aggregate_matrix_rankings(results: list) -> dict:
    """Compute aggregated rankings from matrix benchmark results.

    Groups by (model), (agent), and (model+agent) to produce:
    - per-model avg score + avg time
    - per-agent avg score + avg time
    - best combo overall
    """
    from collections import defaultdict

    model_stats = defaultdict(lambda: {"scores": [], "times": [], "count": 0, "errors": 0, "agent_tokens": [], "eval_tokens": []})
    agent_stats = defaultdict(lambda: {"scores": [], "times": [], "count": 0, "errors": 0, "agent_tokens": [], "eval_tokens": []})
    combo_stats = defaultdict(lambda: {"scores": [], "times": [], "count": 0, "errors": 0, "agent_tokens": [], "eval_tokens": []})
    scenario_stats = defaultdict(lambda: {"scores": [], "times": [], "count": 0, "errors": 0, "agent_tokens": [], "eval_tokens": []})

    for r in results:
        model = r["model"]
        agent = r["agent"]
        scenario = r["scenario"]
        combo = f"{agent}|{model}"

        for bucket in [model_stats[model], agent_stats[agent], combo_stats[combo], scenario_stats[scenario]]:
            bucket["count"] += 1
            if r["status"] == "success":
                bucket["times"].append(r["duration_s"])
                score = (r.get("evaluation") or {}).get("overall_score")
                if isinstance(score, (int, float)):
                    bucket["scores"].append(score)
                tokens = r.get("tokens", {})
                if tokens and tokens.get("total"):
                    bucket["agent_tokens"].append(tokens["total"])
                eval_t = (r.get("evaluation") or {}).get("_meta", {}).get("eval_token_usage", {})
                if eval_t and eval_t.get("total"):
                    bucket["eval_tokens"].append(eval_t["total"])
            else:
                bucket["errors"] += 1

    def _summarize(stats_dict):
        summary = {}
        for key, s in stats_dict.items():
            entry = {"runs": s["count"], "errors": s["errors"]}
            if s["times"]:
                entry["avg_time"] = round(sum(s["times"]) / len(s["times"]), 3)
            if s["scores"]:
                entry["avg_score"] = round(sum(s["scores"]) / len(s["scores"]), 1)
                entry["min_score"] = min(s["scores"])
                entry["max_score"] = max(s["scores"])
            if s["agent_tokens"]:
                entry["avg_agent_tokens"] = round(sum(s["agent_tokens"]) / len(s["agent_tokens"]))
                entry["total_agent_tokens"] = sum(s["agent_tokens"])
            if s["eval_tokens"]:
                entry["avg_eval_tokens"] = round(sum(s["eval_tokens"]) / len(s["eval_tokens"]))
                entry["total_eval_tokens"] = sum(s["eval_tokens"])
            summary[key] = entry
        # Sort by avg_score desc, then avg_time asc
        return dict(sorted(
            summary.items(),
            key=lambda kv: (-kv[1].get("avg_score", 0), kv[1].get("avg_time", 9999))
        ))

    return {
        "by_model": _summarize(model_stats),
        "by_agent": _summarize(agent_stats),
        "by_combo": _summarize(combo_stats),
        "by_scenario": _summarize(scenario_stats),
    }
