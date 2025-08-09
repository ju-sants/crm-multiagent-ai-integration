import json
from crewai import Crew, Process
from datetime import datetime, timezone

from app.services.celery_service import celery_app
from app.core.logger import get_logger
from app.crews.agents_definitions.obj_declarations.agent_declaration import get_verify_system_action_agent
from app.crews.agents_definitions.obj_declarations.tasks_declaration import create_verify_system_action_task
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.parse_llm_output import parse_json_from_string
from app.services.redis_service import get_redis
from app.crews.src.main_crews.system_operations import system_operations_task

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

@celery_app.task(name='main_crews.verify_system_action')
def verify_system_action_task(contact_id: str):
    """
    A task that runs to proactively check if a system action is needed.
    """
    logger.info(f"[{contact_id}] - Starting verify system action task.")
    state, _ = state_manager.get_state(contact_id)

    # Lógica para a verificação ocorrer nos trẽs primeiros turnos sequencialmente
    now_turn = state.metadata.current_turn_number
    moved_turn = now_turn - 2
    rounded_turn = max(0, moved_turn)

    # Nos dois primeiros turnos temos numeros negativos depois da subtração, e então os arredondamos a 0, fazendo com que passe na verificação
    # 0 % 2 = 0
    if rounded_turn % 2 != 0:
        logger.info(f"[{contact_id}] - Turn {state.metadata.current_turn_number}. Skipping verify_system_action.")
        return contact_id

    # Verificar se já há uma operação de sistema em andamento
    if state.pending_system_operation:
        logger.info(f"[{contact_id}] Theres already a system operation in progress. Skipping.")
        return contact_id
    

    try:
        agent = get_verify_system_action_agent()
        task = create_verify_system_action_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

        # Fetch history of past system actions to avoid redundancy
        system_actions_history_json = redis_client.get(f"{contact_id}:system_actions_history")
        system_actions_history = json.loads(system_actions_history_json) if system_actions_history_json else []

        shorterm_history = redis_client.get(f"shorterm_history:{contact_id}")
        longterm_history_json = redis_client.get(f"longterm_history:{contact_id}")
        longterm_history = json.loads(longterm_history_json) if longterm_history_json else {}
        history_messages = "\n\n".join([
            f"Topic: {topic.get('title', 'N/A')}\nSummary: {topic.get('summary', 'N/A')}"
            for topic in longterm_history.get("topic_details", [])[-5:]
        ])
        
        inputs = {
            "client_message": "\n".join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
            "history_of_system_actions": json.dumps(system_actions_history),
            "shorterm_history": str(shorterm_history),
            "longterm_history": history_messages,
        }

        result = crew.kickoff(inputs=inputs)
        parsed_result = parse_json_from_string(result.raw, update=False)

        if parsed_result and parsed_result.get("system_action_request"):
            action_request = parsed_result.get("system_action_request")
            action_request_datetime = f"{action_request} | {datetime.now(timezone.utc)}"
            
            with redis_client.lock(f"lock:state:{contact_id}", timeout=10):
                state, _ = state_manager.get_state(contact_id)
                state.system_action_request = str(action_request)
                state_manager.save_state(contact_id, state)

            system_operations_task.apply_async(args=[contact_id,])

            system_actions_history.append(action_request_datetime)
            redis_client.set(f"{contact_id}:system_actions_history", json.dumps(system_actions_history))

    except Exception as e:
        logger.error(f"[{contact_id}] - Error in verify_system_action_task: {e}", exc_info=True)
        raise e

    return contact_id