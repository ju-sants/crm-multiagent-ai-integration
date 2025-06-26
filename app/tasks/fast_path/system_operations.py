import json
from crewai import Crew, Process
from app.services.celery_Service import celery_app
from app.core.logger import get_logger
from app.agents.agent_declaration import get_system_operations_agent
from app.tasks.tasks_declaration import create_execute_system_operations_task
from app.models.data_models import ConversationState, CustomerProfile
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.funcs import parse_json_from_string
from app.services.redis_service import get_redis
from app.services.callbell_service import send_callbell_message

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

@celery_app.task(name='fast_path.system_operations')
def system_operations_task(contact_id: str):
    """
    Task for handling system operations requests.
    """
    logger.info(f"[{contact_id}] - Starting system operations task.")
    state = state_manager.get_state(contact_id)
    
    try:
        agent = get_system_operations_agent()
        task = create_execute_system_operations_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential)

        profile_json = redis_client.get(f"{contact_id}:customer_profile")
        profile = CustomerProfile.model_validate_json(profile_json) if profile_json else CustomerProfile(contact_id=contact_id)

        history_summary_json = redis_client.get(f"history:{contact_id}")
        history_summary = json.loads(history_summary_json) if history_summary_json else {}
        history_messages = "\n\n".join([
            f"Topic: {topic.get('title', 'N/A')}\nSummary: {topic.get('summary', 'N/A')}"
            for topic in history_summary.get("topics", [])
        ])

        inputs = {
            "action_requested": state.system_action_request,
            "customer_profile": profile.model_dump_json(),
            "conversation_state": state.model_dump_json(),
            "history": history_messages,
            "message_text_original": "\n".join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
            "customer_name": state.metadata.contact_name,
        }

        result = crew.kickoff(inputs=inputs)
        response_json = parse_json_from_string(result, update=False)

        if response_json:
            redis_client.set(f"{contact_id}:last_system_operation_output", json.dumps(response_json))
            if response_json.get("status") == "INSUFFICIENT_DATA":
                state.system_operation_status = "INSUFFICIENT_DATA"
                send_callbell_message(phone_number=state.metadata.phone_number, messages=[response_json.get("message_to_user", "")])
            else:
                state.system_operation_status = "COMPLETED"
                if state.strategic_plan and "system_action_request" in state.strategic_plan:
                    del state.strategic_plan["system_action_request"]
        
        state_manager.save_state(contact_id, state)
        return contact_id
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in system_operations_task: {e}", exc_info=True)
        raise e