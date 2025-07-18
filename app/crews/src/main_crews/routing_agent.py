import json
from crewai import Crew, Process
import time
from celery import group, chain

from app.services.celery_service import celery_app
from app.core.logger import get_logger
from app.crews.agents_definitions.obj_declarations.agent_declaration import get_routing_agent
from app.crews.agents_definitions.obj_declarations.tasks_declaration import create_strategy_agent_task
from app.models.data_models import ConversationState
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.funcs import parse_json_from_string
from app.services.redis_service import get_redis
from app.crews.src.main_crews.refine_strategy import refine_strategy_task
from app.crews.src.main_crews.strategy import strategy_task
from app.crews.src.main_crews.backend_routing import backend_routing_task

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

@celery_app.task(name='main_crews.pre_routing', bind=True)
def pre_routing_orchestrator(self, contact_id: str):
    """
    Orchestrates the parallel execution of context analysis and incremental
    strategy refinement, then routes to the next step.
    """
    logger.info(f"[{contact_id}] - Orchestrating parallel backend_routing tasks and refinement.")
    state, _ = state_manager.get_state(contact_id)

    strategy_agent_task = None
    if state.strategic_plan:
        strategy_agent_task = refine_strategy_task.s(contact_id)
    else:
        strategy_agent_task = strategy_task.s(contact_id)
    
    if strategy_agent_task:
        strategy_agent_task.apply_async()

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

        messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
        history_summary_json = redis_client.get(f"history:{contact_id}")
        history_summary = json.loads(history_summary_json) if history_summary_json else {}
        history_messages = "\n\n".join(
            [f"Topic: {topic.get('title', 'N/A')}\nSummary: {topic.get('summary', 'N/A')}" for topic in history_summary.get("topic_details", [])]
        )

        while redis_client.keys(f"transcribing:*:{contact_id}"):
            logger.info(f"[{contact_id}] - Waiting for transcription to complete.")
            time.sleep(1)

        conversation_state_dict = state.model_dump()
        conversation_state_dict.pop("disclosure_checklist", {})

        inputs = {
            "client_message": "\n".join(messages),
            "conversation_state": json.dumps(conversation_state_dict),
            "history": history_messages,
        }

        result = crew.kickoff(inputs=inputs)
        json_response = parse_json_from_string(result.raw, update=False)

        if json_response:
            # Lock to prevent race conditions with the parallel refine_strategy task
            with redis_client.lock(f"lock:state:{contact_id}", timeout=10):
                current_state, _ = state_manager.get_state(contact_id)
                updated_state = ConversationState(**{**current_state.model_dump(), **json_response})
                state_manager.save_state(contact_id, updated_state)

        logger.info(f"[{contact_id}] - Internal context analysis crew finished.")
        return contact_id
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in _run_routing_agent_crew: {e}", exc_info=True)
        raise e