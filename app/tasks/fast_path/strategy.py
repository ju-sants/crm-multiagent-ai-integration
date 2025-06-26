import json
from crewai import Crew, Process
from app.services.celery_Service import celery_app
from app.core.logger import get_logger
from app.agents.agent_declaration import get_strategic_advisor_agent
from app.tasks.tasks_declaration import create_develop_strategy_task
from app.models.data_models import ConversationState, CustomerProfile
from app.services.state_manager_service import StateManagerService
from app.utils.funcs.funcs import parse_json_from_string
from app.services.redis_service import get_redis

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

@celery_app.task(name='fast_path.strategy', bind=True)
def strategy_task(self, contact_id: str):
    """
    Second task in the state machine chain. Loads state, runs strategy,
    and passes contact_id to the next task.
    """
    logger.info(f"[{contact_id}] - Starting strategy task.")
    state = state_manager.get_state(contact_id)

    if state.is_plan_acceptable:
        logger.info(f"[{contact_id}] - Plan is acceptable, skipping strategy generation.")
        return contact_id

    try:
        # A new strategy is needed
        agent = get_strategic_advisor_agent()
        task = create_develop_strategy_task(agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential)

        # Load the full customer profile for the agent
        profile_json = redis_client.get(f"{contact_id}:customer_profile")
        profile = CustomerProfile.model_validate_json(profile_json) if profile_json else CustomerProfile(contact_id=contact_id)
        
        # Load summarized history
        history_summary_json = redis_client.get(f"history:{contact_id}")
        history_summary = json.loads(history_summary_json) if history_summary_json else {}
        history_messages = "\n\n".join([
            f"Topic: {topic.get('title', 'N/A')}\nSummary: {topic.get('summary', 'N/A')}"
            for topic in history_summary.get("topics", [])
        ])

        inputs = {
            "contact_id": contact_id,
            "history": history_messages,
            "conversation_state": state.model_dump_json(),
            "profile_customer_task_output": profile.model_dump_json(),
            "message_text_original": "\n".join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
            "operational_context": state.operational_context,
            "identified_topic": state.identified_topic,
        }

        result = crew.kickoff(inputs=inputs)
        strategic_plan, updated_state_dict = parse_json_from_string(result)

        if updated_state_dict:
            state = ConversationState(**{**state.model_dump(), **updated_state_dict})
        
        if strategic_plan:
            state.strategic_plan = strategic_plan

        state_manager.save_state(contact_id, state)
        
        return contact_id
    except Exception as e:
        logger.error(f"[{contact_id}] - Error in strategy_task: {e}", exc_info=True)
        raise e