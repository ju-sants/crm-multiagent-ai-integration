import json
from crewai import Crew, Process
import time
from celery import chain

from app.services.celery_service import celery_app
from app.core.logger import get_logger
from app.crews.agents_definitions.obj_declarations.agent_declaration import get_routing_agent
from app.crews.agents_definitions.obj_declarations.tasks_declaration import create_strategy_agent_task
from app.crews.src.main_crews.system_operations import system_operations_task
from app.crews.src.main_crews.registration import registration_task
from app.models.data_models import ConversationState
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.parse_llm_output import parse_json_from_string
from app.services.redis_service import get_redis
from app.crews.src.main_crews.refine_strategy import refine_strategy_task
from app.crews.src.main_crews.strategy import strategy_task
from app.crews.src.main_crews.verify_system_action import verify_system_action_task
from app.crews.src.main_crews.backend_routing import backend_routing_task
from app.utils.funcs.funcs import distill_conversation_state, safe_inject, merge_state_fields, build_longterm_context, refresh_shorterm_history
from app.utils.static import default_strategic_plan


logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

LONGTERM_TOKEN_BUDGET = 1500

@celery_app.task(name='main_crews.pre_routing')
def pre_routing_orchestrator(contact_id: str):
    """
    Orchestrates the parallel execution of context analysis and incremental
    strategy refinement, then routes to the next step.
    """
    logger.info(f"[{contact_id}] - Orchestrating parallel backend_routing tasks and refinement.")
    state, _ = state_manager.get_state(contact_id)

    # P3: Pre-enrichment lite — ensure shorterm_history includes current messages
    refresh_shorterm_history(contact_id)

    if state.pending_system_operation:
        logger.info(f"[{contact_id}] - Continuing system operations flow. Routing to: system_operations_task")
        with redis_client.lock(f"lock:state:{contact_id}", timeout=30):
            
            state, _ = state_manager.get_state(contact_id)
            state.system_action_request = state.pending_system_operation
            state_manager.save_state(contact_id, state)

        system_operations_task.apply_async(args=[contact_id])

        return contact_id

    elif redis_client.get(f"{contact_id}:getting_data_from_user"):
        logger.info(f"[{contact_id}] - Continuing registration flow. Routing to: registration_task")
        registration_task.apply_async(args=[contact_id])
        
        return contact_id

    strategy_agent_task = None
    if state.strategic_plan and state.strategic_plan == default_strategic_plan:
        strategy_agent_task = strategy_task.s(contact_id)
    else:
        strategy_agent_task = refine_strategy_task.s(contact_id)
    
    if strategy_agent_task:
        strategy_agent_task.apply_async()

    verify_system_action_task.apply_async(args=[contact_id,])

    workflow = chain(_run_routing_agent_crew.si(contact_id), backend_routing_task.si(contact_id))
    workflow.apply_async()

    logger.info(f"[{contact_id}] - Parallel workflow initiated. Orchestrator task finished.")
    return contact_id

@celery_app.task(name='main_crews._internal_routing_agent_crew')
def _run_routing_agent_crew(contact_id: str):
    """
    The actual logic for the context analysis crew.
    This is now an internal task called by the orchestrator.
    """
    logger.info(f"[{contact_id}] - Starting internal context analysis crew.")
    state, _ = state_manager.get_state(contact_id)

    try:
        agent = get_routing_agent()
        task = create_strategy_agent_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

        shorterm_history = safe_inject(redis_client.get(f"shorterm_history:{contact_id}"), "")

        messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
        longterm_history_json = redis_client.get(f"longterm_history:{contact_id}")
        longterm_history_raw = json.loads(longterm_history_json) if longterm_history_json else {}
        history_messages = build_longterm_context(longterm_history_raw, max_tokens=LONGTERM_TOKEN_BUDGET)

        waited = 0
        while (redis_client.exists(f"transcribing:audio:{contact_id}") or redis_client.exists(f"transcribing:image:{contact_id}")) and waited < 120:
            logger.info(f"[{contact_id}] - Waiting for transcription to complete.")
            time.sleep(2)
            waited += 2
        if waited >= 120:
            logger.warning(f"[{contact_id}] - Transcription wait timed out after 120s. Proceeding.")

        conversation_state_distilled = distill_conversation_state(state, "RoutingAgent")

        inputs = {
            "client_message": "\n".join(messages),
            "conversation_state": json.dumps(conversation_state_distilled),
            "longterm_history": history_messages,
            "shorterm_history": shorterm_history,
        }

        result = crew.kickoff(inputs=inputs)
        json_response = parse_json_from_string(result.raw, update=False)

        if json_response:
            with redis_client.lock(f"lock:state:{contact_id}", timeout=30):
                current_state, _ = state_manager.get_state(contact_id)
                merged = merge_state_fields(current_state.model_dump(), json_response)
                updated_state = ConversationState(**merged)
                state_manager.save_state(contact_id, updated_state)

        logger.info(f"[{contact_id}] - Internal context analysis crew finished.")
        return contact_id
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in _run_routing_agent_crew: {e}", exc_info=True)
        raise e