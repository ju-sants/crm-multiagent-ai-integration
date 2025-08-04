import json
from crewai import Crew, Process
from datetime import datetime, timezone
import time

from app.services.celery_service import celery_app
from app.crews.src.enrichment_crew import trigger_post_processing
from app.core.logger import get_logger
from app.crews.agents_definitions.obj_declarations.agent_declaration import get_communication_agent
from app.config.llm_config import X_llm
from app.tools.knowledge_tools import drill_down_topic_tool
from app.crews.agents_definitions.obj_declarations.tasks_declaration import create_communication_task
from app.models.data_models import ConversationState
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.funcs import parse_json_from_string
from app.services.redis_service import get_redis
from app.utils.funcs.funcs import distill_conversation_state

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

AGENT_TOPIC_LIMIT = 10

# --- Main Communication Task ---
@celery_app.task(name='main_crews.communication', bind=True)
def communication_task(self, contact_id: str, is_follow_up: bool = False):
    """
    Third task in the state machine chain. Loads state, generates the final response,
    and dispatches messages to the user asynchronously.
    Can be triggered as a follow-up, which alters the agent's context.
    """
    logger.info(f"[{contact_id}] - Starting communication task.")
    state, _ = state_manager.get_state(contact_id)

    while redis_client.keys(f"transcribing:*:{contact_id}"):
        logger.info(f"[{contact_id}] - Waiting for transcription to complete.")
        time.sleep(1)

    try:
        llm_w_tools = X_llm.bind_tools([drill_down_topic_tool])
        agent = get_communication_agent(llm_w_tools)
        task = create_communication_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

        # Process inputs
        shorterm_history = redis_client.get(f"shorterm_history:{contact_id}")

        longterm_history_json = redis_client.get(f"longterm_history:{contact_id}")
        longterm_history = json.loads(longterm_history_json) if longterm_history_json else {}
        topic_details = longterm_history.get("topic_details", [])[-AGENT_TOPIC_LIMIT:]
        longterm_history = "\n\n".join([
            f"Topic: {topic.get('title', 'N/A')}\nSummary: {topic.get('summary', 'N/A')}"
            for topic in topic_details
        ])

        system_op_output = redis_client.get(f"{contact_id}:last_system_operation_output")

        last_processed_messages = redis_client.lrange(f"contacts_messages:waiting:{contact_id}", 0, -1)

        redis_client.set(f"{contact_id}:last_processed_messages", '\n'.join(last_processed_messages))
        
        # State Distillation
        conversation_state_distilled = distill_conversation_state(state, "CommunicationAgent")
        
        strategic_plan = conversation_state_distilled.pop("strategic_plan", None)
        disclosure_checklist = conversation_state_distilled.pop("disclosure_checklist", None)

        inputs = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategic_plan": json.dumps(strategic_plan),
            "last_system_operation": system_op_output if system_op_output else "{}",
            "customer_profile": str(redis_client.get(f"{contact_id}:customer_profile")),
            "conversation_state": str(conversation_state_distilled),
            "longterm_history": longterm_history,
            "shorterm_history": str(shorterm_history),
            "recently_sent_catalogs": ", ".join(redis_client.lrange(f"{contact_id}:sended_catalogs", 0, -1)),
            "disclosure_checklist": json.dumps([item.model_dump() for item in state.disclosure_checklist]) if not disclosure_checklist else str(disclosure_checklist),
            "client_message": "\n".join(last_processed_messages) if not is_follow_up else "",
            "is_follow_up": is_follow_up,
        }

        result = crew.kickoff(inputs=inputs)
        result_str: str = result.raw
        response_json, updated_state_dict = parse_json_from_string(result_str)

        if updated_state_dict:
            state = ConversationState(**{**state.model_dump(), **updated_state_dict})
        
        state_manager.save_state(contact_id, state)

        send_message = False
        # --- Asynchronous Message Sending ---
        if response_json and response_json.get('messages_sequence'):
            phone_number = state.metadata.phone_number
            if not phone_number:
                logger.error(f"[{contact_id}] - Cannot send message, phone number is missing from state.")
                return {"status": "error", "reason": "Missing phone number"}

            send_message = True

        # 1. Cleaning the messages
        all_messages = redis_client.lrange(f"contacts_messages:waiting:{contact_id}", 0, -1)
        messages_left = [m for m in all_messages if m not in last_processed_messages]

        pipe = redis_client.pipeline()

        pipe.delete(f"contacts_messages:waiting:{contact_id}")

        if messages_left:
            pipe.rpush(f"contacts_messages:waiting:{contact_id}", *messages_left)

        pipe.execute()

        # 2. Trigger enrichment pipeline (now self-sufficient) and send_message if needed
        trigger_post_processing.apply_async(args=[contact_id, send_message, response_json, phone_number])
        
        return {"status": "communication_dispatched"}
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in communication_task: {e}", exc_info=True)
        raise e