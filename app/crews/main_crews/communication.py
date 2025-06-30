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

@celery_app.task(name='io.send_message')
def send_message(state: ConversationState, messages, contact_id, plan_names, phone_number):
    try:
        from app.config.utils.messages_plans import plans_messages

        if plan_names:
            for plan_name in plan_names:
                messages.extend(plans_messages.get(plan_name, []))
                
        if state.communication_preference.prefers_audio:
            logger.info(f'[{contact_id}] - "prefers_audio" encontrado em state. Enviando mensagem de áudio.')
            audio_url = eleven_labs_service(messages)
            send_callbell_message(phone_number=phone_number, type="audio", audio_url=audio_url)
            redis_client.hset(f"{contact_id}:attachments", audio_url, ' '.join(messages))
        
        else:
        
            has_long_message = False
            for message in messages:
                if len(message) > 250:
                    has_long_message = True
            
            if has_long_message and not all([len(message) > 250 for message in messages]):
                logger.info(f"[{contact_id}] - Encontrada mensagem com mais de 250 caracteres. Enviando mensagem de áudio.")
                            
                for message in messages:
                    if len(message) > 250:
                        audio_url = eleven_labs_service([message])
                        send_callbell_message(phone_number=phone_number, type="audio", audio_url=audio_url)
                        redis_client.hset(f"{contact_id}:attachments", audio_url, message)

                    else:
                        send_callbell_message(phone_number=phone_number, messages=[message])
            
            else:
                logger.info(f"[{contact_id}] - Não encontrada mensagem com mais de 250 caracteres.")
                
                messages_all_str = '\n'.join(messages)
                if len(messages_all_str) > 300:
                    logger.info(f"[{contact_id}] - Todas as mensagens somam mais de 300 caracteres. Enviando mensagem de áudio.")

                    audios_messages_qnt = len(messages) // 2 + 1
                    audios_messages = messages[:audios_messages_qnt]
                    audios_messages_str = '/n'.join(audios_messages)

                    messages_left = messages[audios_messages_qnt:]

                    audio_url = eleven_labs_service(audios_messages)
                    send_callbell_message(phone_number=phone_number, type="audio", audio_url=audio_url)
                    redis_client.hset(f"{contact_id}:attachments", audio_url, audios_messages_str)

                    if messages_left:
                        send_callbell_message(phone_number=phone_number, messages=messages_left)
                else:
                    logger.info(f"[{contact_id}] - Todas as mensagens somam menos de 300 caracteres. Enviando mensagens de texto.")
                    send_callbell_message(phone_number=phone_number, messages=messages)

    except Exception as e:
        logger.error(f'[{contact_id}] - Erro ao enviar mensagens para Callbell: {e}')

    else:
        if plan_names:
            redis_client.rpush(f"{contact_id}:sended_catalogs", *plan_names)

    finally:
        redis_client.delete(f"processing:{contact_id}")
        logger.info(f'[{contact_id}] - Lock "processing:{contact_id}" LIBERADO no Redis.')


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

            send_message.delay(phone_number, response_json['messages_sequence'], response_json.get("plan_names", []), contact_id)

        # 1. Trigger enrichment pipeline (now self-sufficient)
        trigger_enrichment_pipeline(contact_id, state.model_dump())

        # 2. Clean up Redis keys for the next turn
        redis_client.delete(f"contacts_messages:waiting:{contact_id}")

        return {"status": "communication_dispatched"}
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in communication_task: {e}", exc_info=True)
        raise e