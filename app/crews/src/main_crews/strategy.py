import json
from crewai import Crew, Process
import datetime
import pytz

from app.services.celery_service import celery_app
from app.core.logger import get_logger
from app.crews.agents_definitions.obj_declarations.agent_declaration import get_strategic_advisor_agent
from app.config.llm_config import get_llm
from app.tools.knowledge_tools import knowledge_service_tool, drill_down_topic_tool
from app.crews.agents_definitions.obj_declarations.tasks_declaration import create_develop_strategy_task
from app.models.data_models import ConversationState
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.parse_llm_output import parse_json_from_string
from app.services.redis_service import get_redis
from app.utils.funcs.funcs import distill_conversation_state, safe_inject, merge_state_fields, build_longterm_context

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

LONGTERM_TOKEN_BUDGET = 2000

@celery_app.task(name='main_crews.strategy')
def strategy_task(contact_id: str):
    """
    Second task in the state machine chain. Loads state, runs strategy,
    and passes contact_id to the next task.
    """
    logger.info(f"[{contact_id}] - Starting strategy task.")
    state, _ = state_manager.get_state(contact_id)

    if state.is_plan_acceptable:
        logger.info(f"[{contact_id}] - Plan is acceptable, skipping strategy generation.")
        return contact_id

    try:
        # A new strategy is needed
        llm = get_llm("StrategicAdvisor", contact_id)
        llm_w_tools = llm.bind_tools([knowledge_service_tool, drill_down_topic_tool])
        agent = get_strategic_advisor_agent(llm_w_tools)
        task = create_develop_strategy_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

        # Load the full customer profile for the agent
        profile = safe_inject(redis_client.get(f"{contact_id}:customer_profile"), "{}")
        
        shorterm_history = safe_inject(redis_client.get(f"shorterm_history:{contact_id}"), "")

        # Load summarized history
        longterm_history_json = redis_client.get(f"longterm_history:{contact_id}")
        longterm_history_raw = json.loads(longterm_history_json) if longterm_history_json else {}
        history_messages = build_longterm_context(longterm_history_raw, max_tokens=LONGTERM_TOKEN_BUDGET)

        
        # State Distillation
        conversation_state_distilled = distill_conversation_state(state, "StrategicAdvisor")

        inputs = {
            "contact_id": contact_id,
            "longterm_history": history_messages,
            "shorterm_history": shorterm_history,
            "conversation_state": json.dumps(conversation_state_distilled) if conversation_state_distilled else "{}",
            "profile_customer_task_output": profile,
            "client_message": "\n".join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
            "operational_context": state.operational_context or "",
            "identified_topic": state.identified_topic or "",
            "timestamp": datetime.datetime.now(pytz.timezone("America/Sao_Paulo")).isoformat(),
            "turn": state.metadata.current_turn_number
        }

        # Set a flag to indicate that strategy is being developed (TTL=300s safety net)
        redis_client.set(f"doing_strategy:{contact_id}", '1', ex=300)

        result = crew.kickoff(inputs=inputs)
        strategic_plan, updated_state_dict = parse_json_from_string(result.raw)

        if updated_state_dict:
            with redis_client.lock(f"lock:state:{contact_id}", timeout=30):
                updated_state_dict["strategic_plan"] = strategic_plan

                state, _ = state_manager.get_state(contact_id)
                merged = merge_state_fields(state.model_dump(), updated_state_dict)
                state = ConversationState(**merged)
            
                state_manager.save_state(contact_id, state)
        
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in strategy_task: {e}", exc_info=True)
        raise e

    finally:
        # Clean up the flag after task completion
        redis_client.delete(f"doing_strategy:{contact_id}")
        logger.info(f"[{contact_id}] - Strategy task completed.")
        return contact_id