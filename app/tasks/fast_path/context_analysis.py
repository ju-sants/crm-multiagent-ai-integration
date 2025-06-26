import json
from crewai import Crew, Process
from app.services.celery_Service import celery_app
from app.core.logger import get_logger
from app.agents.agent_declaration import get_context_analysis_agent
from app.tasks.tasks_declaration import create_context_analysis_task
from app.models.data_models import ConversationState
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.funcs import parse_json_from_string
from app.services.redis_service import get_redis

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

@celery_app.task(name='fast_path.context_analysis', bind=True)
def context_analysis_task(self, contact_id: str):
    """
    First task in the state machine chain. Loads state, runs analysis,
    and passes contact_id to the next task.
    """
    logger.info(f"[{contact_id}] - Starting context analysis task.")
    state = state_manager.get_state(contact_id)

    try:
        agent = get_context_analysis_agent()
        task = create_context_analysis_task(agent)

        # This crew is now very lightweight
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential)

        # The inputs are now derived from the state model
        messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
        inputs = {
            "message_text": "\n".join(messages),
            "conversation_state": state.model_dump_json()
        }

        result = crew.kickoff(inputs=inputs)
        json_response, updated_state_dict = parse_json_from_string(result)

        if updated_state_dict:
            state = ConversationState(**{**state.model_dump(), **updated_state_dict})
        
        if json_response:
            state.identified_topic = json_response.get("identified_topic")
            state.operational_context = json_response.get("operational_context")
            state.is_plan_acceptable = json_response.get("is_plan_acceptable", False)

        state_manager.save_state(contact_id, state)
        
        # Pass the contact_id to the next task in the chain
        return contact_id
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in context_analysis_task: {e}", exc_info=True)
        # Dead letter queue logic can be added here
        raise e