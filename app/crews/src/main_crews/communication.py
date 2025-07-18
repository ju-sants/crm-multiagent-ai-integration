import json
from crewai import Crew, Process
from datetime import datetime, timezone
import time

from app.services.celery_service import celery_app
from app.crews.src.enrichment_crew import trigger_post_processing
from app.core.logger import get_logger
from app.agents.agent_declaration import get_communication_agent
from app.config.llm_config import creative_openai_llm
from app.tools.knowledge_tools import drill_down_topic_tool
from app.tasks.tasks_declaration import create_communication_task
from app.models.data_models import ConversationState
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.funcs import parse_json_from_string
from app.services.redis_service import get_redis

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()


# --- Main Communication Task ---
@celery_app.task(name='main_crews.communication', bind=True)
def communication_task(self, contact_id: str):
    """
    Third task in the state machine chain. Loads state, generates the final response,
    and dispatches messages to the user asynchronously.
    """
    logger.info(f"[{contact_id}] - Starting communication task.")
    state, _ = state_manager.get_state(contact_id)

    while redis_client.keys(f"transcribing:*:{contact_id}"):
        logger.info(f"[{contact_id}] - Waiting for transcription to complete.")
        time.sleep(1)

    try:
        llm_w_tools = creative_openai_llm.bind_tools([drill_down_topic_tool])
        agent = get_communication_agent(llm_w_tools)
        task = create_communication_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

        # Process inputs
        history_raw = redis_client.get(f"history_raw_text:{contact_id}")

        history_summary_json = redis_client.get(f"history:{contact_id}")
        history_summary = json.loads(history_summary_json) if history_summary_json else {}
        history_summary_messages = "\n\n".join([
            f"Topic: {topic.get('title', 'N/A')}\nSummary: {topic.get('summary', 'N/A')}"
            for topic in history_summary.get("topic_details", [])
        ])

        system_op_output = redis_client.get(f"{contact_id}:last_system_operation_output")

        last_processed_messages = redis_client.lrange(f"contacts_messages:waiting:{contact_id}", 0, -1)

        redis_client.set(f"{contact_id}:last_processed_messages", '\n'.join(last_processed_messages))
        
        conversation_state_str = state.model_dump_json()
        conversation_state: dict = json.loads(conversation_state_str)
        
        strategic_plan = conversation_state.pop("strategic_plan", None)
        disclosure_checklist = conversation_state.pop("disclosure_checklist", None)

        inputs = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategic_plan": json.dumps(strategic_plan),
            "system_operations_task_output": system_op_output if system_op_output else "{}",
            "customer_profile": str(redis_client.get(f"{contact_id}:customer_profile")),
            "conversation_state": str(conversation_state),
            "history": history_summary_messages,
            "history_raw": str(history_raw),
            "recently_sent_catalogs": ", ".join(redis_client.lrange(f"{contact_id}:sended_catalogs", 0, -1)),
            "disclosure_checklist": json.dumps([item.model_dump() for item in state.disclosure_checklist]) if not disclosure_checklist else str(disclosure_checklist),
            "client_message": "\n".join(last_processed_messages),
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
        trigger_post_processing(contact_id, send_message, response_json, phone_number)
        
        return {"status": "communication_dispatched"}
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in communication_task: {e}", exc_info=True)
        raise e