import json
from crewai import Crew, Process
import datetime
import pytz

from app.services.celery_service import celery_app
from app.core.logger import get_logger
from app.crews.agents_definitions.obj_declarations.agent_declaration import get_strategic_advisor_agent
from app.config.llm_config import X_llm
from app.tools.knowledge_tools import knowledge_service_tool, drill_down_topic_tool
from app.crews.agents_definitions.obj_declarations.tasks_declaration import create_develop_strategy_task
from app.models.data_models import ConversationState
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.parse_llm_output import parse_json_from_string
from app.services.redis_service import get_redis
from app.utils.funcs.funcs import distill_conversation_state

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

HISTORY_TOPIC_LIMIT = 10

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
        llm_w_tools = X_llm.bind_tools([knowledge_service_tool, drill_down_topic_tool])
        agent = get_strategic_advisor_agent(llm_w_tools)
        task = create_develop_strategy_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

        # Load the full customer profile for the agent
        profile = redis_client.get(f"{contact_id}:customer_profile")
        
        shorterm_history = redis_client.get(f"shorterm_history:{contact_id}")

        # Load summarized history
        longterm_history_json = redis_client.get(f"longterm_history:{contact_id}")
        longterm_history = json.loads(longterm_history_json) if longterm_history_json else {}
        history_messages = "\n\n".join([
            f"Topic: {topic.get('title', 'N/A')}\nSummary: {topic.get('summary', 'N/A')}"
            for topic in longterm_history.get("topic_details", [])[-HISTORY_TOPIC_LIMIT:]
        ])

        
        # State Distillation
        conversation_state_distilled = distill_conversation_state(state, "StrategicAdvisor")

        inputs = {
            "contact_id": contact_id,
            "longterm_history": history_messages,
            "shorterm_history": str(shorterm_history),
            "conversation_state": json.dumps(conversation_state_distilled) if conversation_state_distilled else "{}",
            "profile_customer_task_output": str(profile),
            "client_message": "\n".join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
            "operational_context": state.operational_context or "",
            "identified_topic": state.identified_topic or "",
            "timestamp": datetime.datetime.now(pytz.timezone("America/Sao_Paulo")).isoformat(),
            "turn": state.metadata.current_turn_number
        }

        # Set a flag to indicate that strategy is being developed
        redis_client.set(f"doing_strategy:{contact_id}", '1')

        result = crew.kickoff(inputs=inputs)
        strategic_plan, updated_state_dict = parse_json_from_string(result.raw)

        if updated_state_dict:
            with redis_client.lock(f"lock:state:{contact_id}", timeout=10):
                updated_state_dict["strategic_plan"] = strategic_plan

                state, _ = state_manager.get_state(contact_id)
                state = ConversationState(**{**state.model_dump(), **updated_state_dict})
            
                state_manager.save_state(contact_id, state)
        
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in strategy_task: {e}", exc_info=True)
        raise e

    finally:
        # Clean up the flag after task completion
        redis_client.delete(f"doing_strategy:{contact_id}")
        logger.info(f"[{contact_id}] - Strategy task completed.")
        return contact_id