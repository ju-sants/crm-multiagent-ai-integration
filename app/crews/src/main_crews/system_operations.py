import json
from crewai import Crew, Process

from app.services.celery_service import celery_app
from app.core.logger import get_logger
from app.crews.agents_definitions.obj_declarations.agent_declaration import get_system_operations_agent
from app.config.llm_config import X_llm
from app.tools.system_operations_tools import system_operations_tool
from app.crews.agents_definitions.obj_declarations.tasks_declaration import create_execute_system_operations_task
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.parse_llm_output import parse_json_from_string
from app.services.redis_service import get_redis
from app.services.callbell_service import send_callbell_message
from app.crews.src.main_crews.communication import communication_task
from app.crews.src.secondary_crews.enrichment_crew import trigger_post_processing
from app.utils.funcs.funcs import distill_conversation_state

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

HISTORY_TOPIC_LIMIT = 10

@celery_app.task(name='main_crews.system_operations')
def system_operations_task(contact_id: str):
    """
    Task for handling system operations requests.
    """
    logger.info(f"[{contact_id}] - Starting system operations task.")
    state, _ = state_manager.get_state(contact_id)
    
    try:
        llm_w_tools = X_llm.bind_tools([system_operations_tool])
        agent = get_system_operations_agent(llm_w_tools)
        task = create_execute_system_operations_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

        profile = redis_client.get(f"{contact_id}:customer_profile")

        shorterm_history = redis_client.get(f"shorterm_history:{contact_id}")

        longterm_history_json = redis_client.get(f"longterm_history:{contact_id}")
        longterm_history = json.loads(longterm_history_json) if longterm_history_json else {}
        longterm_history = "\n\n".join([
            f"Topic: {topic.get('title', 'N/A')}\nSummary: {topic.get('summary', 'N/A')}"
            for topic in longterm_history.get("topic_details", [])[-HISTORY_TOPIC_LIMIT:]
        ])

        last_processed_messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)

        # State Distillation
        conversation_state_distilled = distill_conversation_state(state, "SystemOperationsAgent")

        inputs = {
            "action_requested": state.system_action_request,
            "customer_profile": str(profile),
            "conversation_state": str(conversation_state_distilled),
            "longterm_history": longterm_history,
            "shorterm_history": str(shorterm_history),
            "client_message": "\n".join(last_processed_messages),
            "contact_name": state.metadata.contact_name,
        }

        # Set the flag
        redis_client.set(f"doing_system_operations:{contact_id}", "true")
        
        result = crew.kickoff(inputs=inputs)
        response_json = parse_json_from_string(result.raw, update=False)

        if response_json:
            with redis_client.lock(f"lock:state:{contact_id}", timeout=10):
                
                state, _ = state_manager.get_state(contact_id)

                redis_client.set(f"{contact_id}:last_system_operation_output", json.dumps(response_json))
                if response_json.get("status") == "INSUFFICIENT_DATA":
                    # Pause the operation and wait for more user input
                    state.pending_system_operation = str(state.system_action_request)[:]
                    state.system_action_request = None
                    send_callbell_message(contact_id=contact_id, phone_number=state.metadata.phone_number, messages=[response_json.get("message_to_user", "")])

                    state.metadata.current_turn_number += 1

                    # Liberating the lock
                    redis_client.delete(f'processing:{contact_id}')
                    logger.info(f'[{contact_id}] - Lock "processing:{contact_id}" LIBERADO no Redis.')

                    redis_client.set(f"{contact_id}:last_processed_messages", '\n'.join(last_processed_messages))

                    trigger_post_processing.apply_async(args=[contact_id])

                    # Cleaning up the messages
                    all_messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
                    messages_left = [m for m in all_messages if m not in last_processed_messages]
                    
                    pipe = redis_client.pipeline()

                    pipe.delete(f'contacts_messages:waiting:{contact_id}')
                    if messages_left:
                        pipe.lpush(f'contacts_messages:waiting:{contact_id}', *messages_left)
                    
                    # Deletando a FLAG
                    pipe.delete(f"doing_system_operations:{contact_id}")

                    pipe.execute()

                else:
                    # The operation is complete, clear all related flags
                    state.system_operation_status = "COMPLETED"
                    state.pending_system_operation = None
                    state.system_action_request = None
                    if state.strategic_plan and "system_action_request" in state.strategic_plan:
                        del state.strategic_plan["system_action_request"]

                    communication_task.apply_async(args=[contact_id])

                state_manager.save_state(contact_id, state)

        # Deletando a FLAG
        redis_client.delete(f"doing_system_operations:{contact_id}")

        return contact_id
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in system_operations_task: {e}", exc_info=True)
        raise e