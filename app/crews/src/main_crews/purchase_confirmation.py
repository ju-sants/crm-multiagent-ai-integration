import json
from crewai import Crew, Process

from app.core.logger import get_logger
from app.crews.agents_definitions.obj_declarations.agent_declaration import get_purchase_confirmation_agent
from app.crews.agents_definitions.obj_declarations.tasks_declaration import create_purchase_confirmation_task
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.parse_llm_output import parse_json_from_string
from app.services.redis_service import get_redis

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

def purchase_confirmation_task(contact_id: str):
    """
    A task that runs conditionally to check if the client has confirmed the purchase.
    """
    logger.info(f"[{contact_id}] - Starting purchase confirmation task.")
    
    try:
        agent = get_purchase_confirmation_agent()
        task = create_purchase_confirmation_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

        shorterm_history = redis_client.get(f"shorterm_history:{contact_id}")
        longterm_history_json = redis_client.get(f"longterm_history:{contact_id}")
        longterm_history = json.loads(longterm_history_json) if longterm_history_json else {}
        history_messages = "\n\n".join([
            f"Topic: {topic.get('title', 'N/A')}\nSummary: {topic.get('summary', 'N/A')}"
            for topic in longterm_history.get("topic_details", [])[-5:]
        ])

        inputs = {
            "client_message": "\n".join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
            "shorterm_history": str(shorterm_history),
            "longterm_history": history_messages,
        }

        result = crew.kickoff(inputs=inputs)
        parsed_result = parse_json_from_string(result.raw)

        if parsed_result and parsed_result.get("budget_accepted") is True:
            with redis_client.lock(f"lock:state:{contact_id}", timeout=10):
                current_state, _ = state_manager.get_state(contact_id)
                current_state.operational_context = "BUDGET_ACCEPTED"
                current_state.budget_accepted = True

                state_manager.save_state(contact_id, current_state)
                
            logger.info(f"[{contact_id}] - Purchase confirmed. Operational context set to BUDGET_ACCEPTED.")

    except Exception as e:
        logger.error(f"[{contact_id}] - Error in purchase_confirmation_task: {e}", exc_info=True)
        raise e

    return contact_id