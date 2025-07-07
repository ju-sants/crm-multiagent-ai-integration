import json
from crewai import Crew, Process
from app.services.celery_Service import celery_app
from app.core.logger import get_logger
from app.agents.agent_declaration import get_system_operations_agent
from app.config.llm_config import decivise_openai_llm
from app.tools.system_operations_tools import system_operations_tool
from app.tasks.tasks_declaration import create_execute_system_operations_task
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.funcs import parse_json_from_string
from app.services.redis_service import get_redis
from app.services.callbell_service import send_callbell_message
from app.utils.funcs.funcs import process_history
from app.crews.main_crews.communication import communication_task
from app.crews.enrichment_crew import trigger_enrichment_pipeline

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

@celery_app.task(name='main_crews.system_operations')
def system_operations_task(contact_id: str):
    """
    Task for handling system operations requests.
    """
    logger.info(f"[{contact_id}] - Starting system operations task.")
    state = state_manager.get_state(contact_id)
    
    try:
        llm_w_tools = decivise_openai_llm.bind_tools([system_operations_tool])
        agent = get_system_operations_agent(llm_w_tools)
        task = create_execute_system_operations_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential)

        profile = redis_client.get(f"{contact_id}:customer_profile")

        history_raw = []
        history_raw_messages = ""

        try:
            history_raw = json.loads(redis_client.get(f"history_raw:{contact_id}"))
        except:
            pass
        
        if history_raw:
            history_raw = history_raw[:10]
            history_raw_messages = process_history(history_raw, contact_id)

        history_summary_json = redis_client.get(f"history:{contact_id}")
        history_summary = json.loads(history_summary_json) if history_summary_json else {}
        history_summary_messages = "\n\n".join([
            f"Topic: {topic.get('title', 'N/A')}\nSummary: {topic.get('summary', 'N/A')}"
            for topic in history_summary.get("topic_details", [])
        ])

        last_processed_messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)

        inputs = {
            "action_requested": state.system_action_request,
            "customer_profile": str(profile),
            "conversation_state": state.model_dump_json(),
            "history": history_summary_messages,
            "history_raw": history_raw_messages,
            "client_message": "\n".join(last_processed_messages),
            "customer_name": state.metadata.contact_name,
        }

        result = crew.kickoff(inputs=inputs)
        response_json = parse_json_from_string(result.raw, update=False)

        if response_json:
            redis_client.set(f"{contact_id}:last_system_operation_output", json.dumps(response_json))
            if response_json.get("status") == "INSUFFICIENT_DATA":
                # Pause the operation and wait for more user input
                state.pending_system_operation = state.system_action_request
                state.system_action_request = None
                send_callbell_message(phone_number=state.metadata.phone_number, messages=[response_json.get("message_to_user", "")])

                # Liberating the lock
                redis_client.delete(f'processing:{contact_id}')
                logger.info(f'[{contact_id}] - Lock "processing:{contact_id}" LIBERADO no Redis.')

                redis_client.set(f"{contact_id}:last_processed_messages", '\n'.join(last_processed_messages))

                trigger_enrichment_pipeline.delay(contact_id, state.model_dump())

                # Cleaning up the messages
                all_messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
                messages_left = [m for m in all_messages if m not in last_processed_messages]
                
                pipe = redis_client.pipeline()

                pipe.delete(f'contacts_messages:waiting:{contact_id}')
                if messages_left:
                    pipe.lpush(f'contacts_messages:waiting:{contact_id}', *messages_left)

                pipe.execute()

            else:
                # The operation is complete, clear all related flags
                state.system_operation_status = "COMPLETED"
                state.pending_system_operation = None
                state.system_action_request = None
                if state.strategic_plan and "system_action_request" in state.strategic_plan:
                    del state.strategic_plan["system_action_request"]

                communication_task.delay(contact_id)

        
        state_manager.save_state(contact_id, state)
        return contact_id
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in system_operations_task: {e}", exc_info=True)
        raise e