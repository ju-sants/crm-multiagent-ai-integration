import json
from crewai import Crew, Process, Task
from datetime import datetime, timezone

from app.core.logger import get_logger
from app.services.celery_service import celery_app
from app.services.redis_service import get_redis
from app.crews.src.main_crews.communication import communication_task
from app.crews.agents_definitions.obj_declarations.agent_declaration import get_follow_up_agent
from app.utils.funcs.funcs import parse_json_from_string

logger = get_logger(__name__)
redis_client = get_redis()

@celery_app.task(name='main_crews.follow_up')
def follow_up_task(contact_id: str):
    """
    This task is triggered by the inactivity worker. It runs the Follow-up Crew
    to decide if a customer should be re-engaged.
    """
    logger.info(f"[{contact_id}] - Starting follow-up task for inactive contact.")

    agent = get_follow_up_agent()

    task = Task(
        description="Analyze the customer's profile and conversation history to decide if a follow-up is appropriate.",
        expected_output="A JSON object with a single boolean key: 'send_follow_up'.",
        agent=agent
    )

    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

    # Fetch required data from Redis
    longterm_history_json = redis_client.get(f"longterm_history:{contact_id}")
    customer_profile_json = redis_client.get(f"{contact_id}:customer_profile")

    longterm_history = json.loads(longterm_history_json) if longterm_history_json else {}
    customer_profile = json.loads(customer_profile_json) if customer_profile_json else {}

    inputs = {
        "contact_id": contact_id,
        "longterm_history": json.dumps(longterm_history),
        "customer_profile": json.dumps(customer_profile),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "last_message_timestamp": redis_client.get(f"history:last_timestamp:{contact_id}")
    }

    result = crew.kickoff(inputs=inputs)
    output = parse_json_from_string(result.raw)

    if output and output.get("send_follow_up") is True:
        logger.info(f"[{contact_id}] - Follow-up approved. Triggering communication crew.")
        # Trigger the communication task with an empty client_message
        communication_task.apply_async(args=[contact_id], kwargs={'is_follow_up': True})
    else:
        logger.info(f"[{contact_id}] - Follow-up not recommended at this time.")

    return {"status": "follow_up_processed", "decision": output.get("send_follow_up", False)}