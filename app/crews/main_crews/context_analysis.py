import json
from crewai import Crew, Process
import time

from app.services.celery_service import celery_app
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

@celery_app.task(name='main_crews.context_analysis', bind=True)
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
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

        # The inputs are now derived from the state model
        messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
        history_summary_json = redis_client.get(f"history:{contact_id}")
        history_summary = json.loads(history_summary_json) if history_summary_json else {}
        history_messages = "\n\n".join([
            f"Topic: {topic.get('title', 'N/A')}\nSummary: {topic.get('summary', 'N/A')}"
            for topic in history_summary.get("topic_details", [])
        ])


        while True:
            if redis_client.keys(f"transcribing:*:{contact_id}"):
                logger.info(f"[{contact_id}] - Waiting for transcription to complete.")
                time.sleep(1)
                continue
            break

        
        # Extract the conversation state from the state object
        conversation_state_dict = state.model_dump()
        
        #State Distillation
        conversation_state_dict.pop("disclosure_checklist", {})

        inputs = {
            "client_message": "\n".join(messages),
            "conversation_state": json.dumps(conversation_state_dict),
            "history": history_messages,
        }

        result = crew.kickoff(inputs=inputs)
        json_response = parse_json_from_string(result.raw, update=False)

        if json_response:
            state = ConversationState(**{**state.model_dump(), **json_response})
        
        state_manager.save_state(contact_id, state)
        
        # Pass the contact_id to the next task in the chain
        return contact_id
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in context_analysis_task: {e}", exc_info=True)
        # Dead letter queue logic can be added here
        raise e