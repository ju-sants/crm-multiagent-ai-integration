import json
from crewai import Crew, Process
import datetime
import pytz

from app.services.celery_service import celery_app
from app.core.logger import get_logger
from app.crews.agents_definitions.obj_declarations.agent_declaration import get_incremental_strategic_planner_agent
from app.config.llm_config import X_llm
from app.tools.knowledge_tools import knowledge_service_tool, drill_down_topic_tool
from app.crews.agents_definitions.obj_declarations.tasks_declaration import create_refine_strategy_task
from app.models.data_models import ConversationState
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.funcs import parse_json_from_string
from app.services.redis_service import get_redis
from app.utils.funcs.funcs import distill_conversation_state

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

AGENT_TOPIC_LIMIT =10

@celery_app.task(name='main_crews.refine_strategy', bind=True)
def refine_strategy_task(self, contact_id: str):
    """
    A task that runs in parallel with context analysis to incrementally
    improve the strategic plan based on the latest client message.
    """
    logger.info(f"[{contact_id}] - Starting incremental strategy refinement task.")
    state, _ = state_manager.get_state(contact_id)

    # This task should always run, as long as there is a plan to refine.
    if not state.strategic_plan:
        logger.info(f"[{contact_id}] - No existing plan to refine. Skipping.")
        return contact_id

    try:
        llm_w_tools = X_llm.bind_tools([knowledge_service_tool, drill_down_topic_tool])
        agent = get_incremental_strategic_planner_agent(llm_w_tools)
        task = create_refine_strategy_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

        profile = redis_client.get(f"{contact_id}:customer_profile")
        shorterm_history = redis_client.get(f"shorterm_history:{contact_id}")

        longterm_history_json = redis_client.get(f"longterm_history:{contact_id}")
        longterm_history = json.loads(longterm_history_json) if longterm_history_json else {}
        history_messages = "\n\n".join([
            f"Topic: {topic.get('title', 'N/A')}\nSummary: {topic.get('summary', 'N/A')}"
            for topic in longterm_history.get("topic_details", [])[-AGENT_TOPIC_LIMIT:]
        ])


        # State Distillation
        conversation_state_distilled = distill_conversation_state(state, "IncrementalStrategicPlannerAgent")
        system_op_output = redis_client.get(f"{contact_id}:last_system_operation_output")
        
        inputs = {
            "last_system_operation": system_op_output if system_op_output else "",
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

        redis_client.set(f"refining_strategy:{contact_id}", "1")  # Set flag to indicate refinement in progress

        result = crew.kickoff(inputs=inputs)
        refined_plan, updated_state_dict = parse_json_from_string(result.raw)

        if updated_state_dict and refined_plan:
            # Lock the state to prevent race conditions with routing_agent
            with redis_client.lock(f"lock:state:{contact_id}", timeout=10):
                # Re-fetch state to get latest version
                current_state, _ = state_manager.get_state(contact_id)
                
                # Merge the refined plan and any other updates
                updated_state_dict["strategic_plan"] = refined_plan
                final_state = ConversationState(**{**current_state.model_dump(), **updated_state_dict})
                
                state_manager.save_state(contact_id, final_state)
        
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in refine_strategy_task: {e}", exc_info=True)
        raise e
    
    finally:
        redis_client.delete(f"refining_strategy:{contact_id}")  # Clear the flag
        return contact_id
