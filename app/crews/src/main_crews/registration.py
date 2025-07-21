import json
from crewai import Crew, Process
from app.services.celery_service import celery_app
from app.core.logger import get_logger
from app.crews.agents_definitions.obj_declarations.agent_declaration import get_registration_agent
from app.crews.agents_definitions.obj_declarations.tasks_declaration import create_collect_registration_data_task
from app.models.data_models import ConversationState
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.funcs import parse_json_from_string
from app.services.redis_service import get_redis
from app.services.callbell_service import send_callbell_message
from app.services.telegram_service import send_single_telegram_message
from app.utils.funcs.funcs import distill_conversation_state

from datetime import datetime, timezone

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

@celery_app.task(name='main_crews.registration')
def registration_task(contact_id: str):
    """
    Task for handling the customer registration data collection process.
    """
    logger.info(f"[{contact_id}] - Starting registration task.")
    state, _ = state_manager.get_state(contact_id)

    try:
        agent = get_registration_agent()
        task = create_collect_registration_data_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

        user_data_so_far = redis_client.get(f"{contact_id}:user_data_so_far")
        plan_details = redis_client.get(f"{contact_id}:plan_details")

        last_processed_messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)

        conversation_state_dict = state.model_dump()

        # State Distillation
        conversation_state_distilled = distill_conversation_state(conversation_state_dict, "RegistrationDataCollectorAgent")

        inputs = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "conversation_state": json.dumps(conversation_state_distilled) if conversation_state_distilled else "{}",
            "client_message": "\n".join(last_processed_messages),
            "collected_data_so_far": user_data_so_far if user_data_so_far else "{}",
            "plan_details": plan_details if plan_details else "{}",
        }

        result = crew.kickoff(inputs=inputs)
        response_json, updated_state_dict = parse_json_from_string(result.raw)

        if updated_state_dict:
            if "entities_extracted" in updated_state_dict and updated_state_dict["entities_extracted"]:
                state_json = state.model_dump()
                state_json["entities_extracted"] += updated_state_dict["entities_extracted"]

                state = ConversationState(**{**state.model_dump(), **state_json})
        
        state_manager.save_state(contact_id, state)

        if response_json:
            redis_client.set(f"{contact_id}:user_data_so_far", json.dumps(response_json))
            
            if response_json.get("status") == 'COLLECTION_COMPLETE':
                send_callbell_message(phone_number=state.metadata.phone_number, messages=[response_json["next_message_to_send"]])
                send_single_telegram_message(result, '-4854533163')
                redis_client.delete(f"{contact_id}:getting_data_from_user")
            elif response_json.get("next_message_to_send"):
                send_callbell_message(phone_number=state.metadata.phone_number, messages=[response_json["next_message_to_send"]])
                redis_client.set(f"{contact_id}:getting_data_from_user", "1")
            
            # Liberating the lock
            redis_client.delete(f'processing:{contact_id}')
            logger.info(f'[{contact_id}] - Lock "processing:{contact_id}" LIBERADO no Redis.')

            # Cleaning up the messages
            all_messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
            messages_left = [message for message in all_messages if message not in last_processed_messages]

            pipe = redis_client.pipeline()
            
            pipe.delete(f'contacts_messages:waiting:{contact_id}')
            if messages_left:
                pipe.rpush(f'contacts_messages:waiting:{contact_id}', *messages_left)
                

        return contact_id
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in registration_task: {e}", exc_info=True)
        raise e