import json
from crewai import Crew, Process
import datetime
import pytz

from app.services.celery_service import celery_app
from app.core.logger import get_logger
from app.agents.agent_declaration import get_incremental_strategic_planner_agent
from app.config.llm_config import creative_openai_llm
from app.tools.knowledge_tools import knowledge_service_tool, drill_down_topic_tool
from app.tasks.tasks_declaration import create_refine_strategy_task
from app.models.data_models import ConversationState
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.funcs import parse_json_from_string
from app.services.redis_service import get_redis

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

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
        llm_w_tools = creative_openai_llm.bind_tools([knowledge_service_tool, drill_down_topic_tool])
        agent = get_incremental_strategic_planner_agent(llm_w_tools)
        task = create_refine_strategy_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

        profile = redis_client.get(f"{contact_id}:customer_profile")
        history_raw = redis_client.get(f"history_raw_text:{contact_id}")

        history_summary_json = redis_client.get(f"history:{contact_id}")
        history_summary = json.loads(history_summary_json) if history_summary_json else {}
        history_messages = "\n\n".join([
            f"Topic: {topic.get('title', 'N/A')}\nSummary: {topic.get('summary', 'N/A')}"
            for topic in history_summary.get("topic_details", [])
        ])

        inputs = {
            "history": history_messages,
            "history_raw": str(history_raw),
            "conversation_state": state.model_dump_json(),
            "profile_customer_task_output": str(profile),
            "client_message": "\n".join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
            "operational_context": state.operational_context or "",
            "identified_topic": state.identified_topic or "",
            "timestamp": datetime.datetime.now(pytz.timezone("America/Sao_Paulo")).isoformat(),
            "turn": state.metadata.current_turn_number
        }

        redis_client.set(f"refining_strategy:{contact_id}", "1")  # Set flag to indicate refinement in progress
        logger.info(f"[{contact_id}] - Inputs prepared for strategy refinement: {inputs}")

        result = crew.kickoff(inputs=inputs)
        refined_plan, updated_state_dict = parse_json_from_string(result.raw)

        if updated_state_dict and refined_plan:
            # Lock the state to prevent race conditions with routing_agent
            with redis_client.lock(f"lock:state:{contact_id}", timeout=10):
                # Re-fetch state to get latest version
                current_state, _ = state_manager.get_state(contact_id)
                
                # Log the dictionary from the agent to inspect its structure
                logger.info(f"[{contact_id}] - Agent's raw updated_state_dict: {json.dumps(updated_state_dict, indent=2)}")

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
