import json
from crewai import Crew, Process
from datetime import datetime, timezone
from app.services.celery_Service import celery_app
from app.crews.enrichment_crew import trigger_enrichment_pipeline
from app.core.logger import get_logger
from app.agents.agent_declaration import get_communication_agent
from app.config.llm_config import default_openai_llm
from app.tools.knowledge_tools import drill_down_topic_tool
from app.tasks.tasks_declaration import create_communication_task
from app.models.data_models import ConversationState, CustomerProfile
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.funcs import parse_json_from_string
from app.services.redis_service import get_redis
from app.services.callbell_service import send_callbell_message
from app.services.eleven_labs_service import main as eleven_labs_service

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

# --- New, Asynchronous I/O Tasks ---

@celery_app.task(name='io.send_text_message')
def send_text_message_task(phone_number: str, message: str):
    send_callbell_message(phone_number=phone_number, messages=[message])

@celery_app.task(name='io.send_audio_message')
def send_audio_message_task(phone_number: str, messages: list, contact_id: str):
    audio_url = eleven_labs_service(messages)
    send_callbell_message(phone_number=phone_number, type="audio", audio_url=audio_url)
    redis_client.hset(f"{contact_id}:attachments", audio_url, ' '.join(messages))

# --- Main Communication Task ---

@celery_app.task(name='main_crews.communication', bind=True)
def communication_task(self, contact_id: str):
    """
    Third task in the state machine chain. Loads state, generates the final response,
    and dispatches messages to the user asynchronously.
    """
    logger.info(f"[{contact_id}] - Starting communication task.")
    state = state_manager.get_state(contact_id)

    try:
        llm_w_tools = default_openai_llm.bind_tools([drill_down_topic_tool])
        agent = get_communication_agent(llm_w_tools)
        task = create_communication_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential)

        # Load the pre-computed distilled profile for the agent
        distilled_profile_json = redis_client.get(f"{contact_id}:distilled_profile")
        
        history_summary_json = redis_client.get(f"history:{contact_id}")
        history_summary = json.loads(history_summary_json) if history_summary_json else {}
        history_messages = "\n\n".join([
            f"Topic: {topic.get('title', 'N/A')}\nSummary: {topic.get('summary', 'N/A')}"
            for topic in history_summary.get("topics", [])
        ])

        system_op_output = redis_client.get(f"{contact_id}:last_system_operation_output")

        inputs = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "turn": state.metadata.current_turn_number,
            "develop_strategy_task_output": json.dumps(state.strategic_plan),
            "system_operations_task_output": system_op_output if system_op_output else "{}",
            "profile_customer_task_output": distilled_profile_json if distilled_profile_json else "{}",
            "conversation_state": state.model_dump_json(),
            "history": history_messages,
            "recently_sent_catalogs": ", ".join(redis_client.lrange(f"{contact_id}:sended_catalogs", 0, -1)),
            "disclosure_checklist": json.dumps([item.model_dump() for item in state.disclosure_checklist]),
        }

        result = crew.kickoff(inputs=inputs)
        response_json, updated_state_dict = parse_json_from_string(result.raw)

        if updated_state_dict:
            state = ConversationState(**{**state.model_dump(), **updated_state_dict})
        
        state_manager.save_state(contact_id, state)

        # --- Asynchronous Message Sending ---
        if response_json and response_json.get('messages_sequence'):
            phone_number = state.metadata.phone_number
            if not phone_number:
                logger.error(f"[{contact_id}] - Cannot send message, phone number is missing from state.")
                return {"status": "error", "reason": "Missing phone number"}

            if state.communication_preference.prefers_audio:
                send_audio_message_task.delay(phone_number, response_json['messages_sequence'], contact_id)
            else:
                for message in response_json['messages_sequence']:
                    send_text_message_task.delay(phone_number, message)
            


        # Final step: trigger the enrichment for the next turn and liberate de lock

        redis_client.delete(f'processing:{contact_id}')
        logger.info(f'[{contact_id}] - Lock "processing:{contact_id}" LIBERADO no Redis.')

        # 1. Get historical messages and new messages
        base_history_json = redis_client.get(f"raw_history:{contact_id}")
        base_history = json.loads(base_history_json) if base_history_json else {"messages": []}
        
        new_messages_raw = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
        
        new_messages_dicts = [
            {"from": "contact", "text": msg, "timestamp": datetime.now(timezone.utc).isoformat(), "type": "text"}
            for msg in new_messages_raw
        ]

        # The API returns newest first. So new messages should be at the start.
        # 2. Trigger enrichment pipeline (now self-sufficient)
        trigger_enrichment_pipeline(contact_id, state.model_dump())

        # 3. Clean up Redis keys for the next turn
        redis_client.delete(f"contacts_messages:waiting:{contact_id}")

        return {"status": "communication_dispatched"}
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in communication_task: {e}", exc_info=True)
        raise e