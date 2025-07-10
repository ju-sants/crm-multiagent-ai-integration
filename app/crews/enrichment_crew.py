import json
from celery import group, chain
from crewai import Crew, Process

from app.config.settings import settings
from app.core.logger import get_logger
from app.services.redis_service import get_redis
from app.services.celery_Service import celery_app
from app.utils.funcs.funcs import parse_json_from_string
from app.services.callbell_service import get_contact_messages
from app.services.state_manager_service import StateManagerService
from app.models.data_models import ConversationState

state_manager = StateManagerService()

# Import agent and task creation functions
from app.agents.agent_declaration import (
    get_history_summarizer_agent,
    get_data_quality_agent,
    get_state_summarizer_agent,
    get_profile_enhancer_agent
)
from app.tasks.tasks_declaration import (
    create_summarize_history_task,
    create_clean_noisy_data_task,
    create_summarize_state_task,
    create_enhance_profile_task
)


logger = get_logger(__name__)
redis_client = get_redis()

@celery_app.task(name='enrichment.history_summarizer')
def history_summarizer_task(contact_id: str):
    """
    Asynchronous task to incrementally summarize conversation history.
    - Fetches only new messages since the last update.
    - Intelligently merges new messages into the existing summary.
    - Detects noisy data and flags it.
    - Stores the updated summary, topic details, and last message timestamp in Redis.
    """
    logger.info(f"[{contact_id}] - Starting incremental history summarization.")

    summary_key = f"history:{contact_id}"
    timestamp_key = f"history:last_timestamp:{contact_id}"

    # Get existing data from Redis
    existing_summary_json = redis_client.get(summary_key)
    last_timestamp = redis_client.get(timestamp_key)
    
    existing_summary = json.loads(existing_summary_json) if existing_summary_json else None

    # Fetch new messages
    if last_timestamp:
        logger.info(f"[{contact_id}] - Fetching new messages since {last_timestamp}.")
        new_messages = get_contact_messages(contact_id, since_timestamp=last_timestamp)
    else:
        logger.info(f"[{contact_id}] - No existing summary found. Fetching full history.")
        new_messages = get_contact_messages(contact_id, limit=50)

    if not new_messages:
        logger.info(f"[{contact_id}] - No new messages to process. Skipping summarization.")
        return f"No new messages to summarize for {contact_id}."

    # The full history for context is the combination of old and new
    raw_history_json = redis_client.get(f"history_raw:{contact_id}")
    raw_history = json.loads(raw_history_json) if raw_history_json else []
    full_history = raw_history + new_messages
    redis_client.set(f"history_raw:{contact_id}", json.dumps(full_history))

    agent = get_history_summarizer_agent()
    task = create_summarize_history_task(agent)
    
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    
    inputs = {
        "contact_id": contact_id,
        "existing_summary": json.dumps(existing_summary) if existing_summary else "null",
        "new_messages": json.dumps(new_messages),
        "full_raw_history": json.dumps(full_history) # For context and cleaning tasks
    }
    
    result = crew.kickoff(inputs=inputs)
    
    output = parse_json_from_string(result.raw, update=False)
    
    if output:
        # Save the main summary
        redis_client.set(summary_key, json.dumps(output))
        
        # Save details for each topic and check for noise
        for topic_detail in output.get('topic_details', []):
            topic_id = topic_detail.get('topic_id')
            if topic_id:
                details_key = f"history:topic_details:{contact_id}:{topic_id}"
                redis_client.set(details_key, json.dumps(topic_detail))
                
                # Trigger data quality task based on the new quality score
                quality_score = topic_detail.get('quality_score', 1.0)
                if quality_score < 0.6:
                    logger.info(f"[{contact_id}] - Topic {topic_id} has low quality score ({quality_score}). Triggering data quality task.")
                    start_index = topic_detail.get('start_index')
                    end_index = topic_detail.get('end_index')

                    if start_index is not None and end_index is not None:
                        # Slice the raw history to get the relevant snippet for the noisy topic
                        raw_history_snippet = full_history[start_index:end_index + 1]
                        data_quality_task.delay(contact_id, topic_id, json.dumps(raw_history_snippet), json.dumps(full_history))
                    else:
                        logger.warning(f"[{contact_id}] - Could not trigger data quality task for topic {topic_id} due to missing indices.")
        
        # Save the timestamp of the last processed message
        last_message_timestamp = new_messages[-1].get("createdAt")
        if last_message_timestamp:
            redis_client.set(timestamp_key, last_message_timestamp)
            logger.info(f"[{contact_id}] - Updated last processed timestamp to {last_message_timestamp}.")

    logger.info(f"[{contact_id}] - Finished history summarization.")
    return output

@celery_app.task(name='enrichment.data_quality_agent')
def data_quality_task(contact_id: str, topic_id: str, raw_history_snippet: str, full_raw_history: str):
    """
    Asynchronous task to clean up a noisy conversation topic, using the full conversation for context.
    """
    logger.info(f"[{contact_id}] - Starting data quality task for topic {topic_id}.")
    
    agent = get_data_quality_agent()
    task = create_clean_noisy_data_task(agent)
    
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    
    inputs = {
        "contact_id": contact_id,
        "topic_id": topic_id,
        "raw_history_snippet": raw_history_snippet,
        "full_raw_history": full_raw_history
    }
    
    result = crew.kickoff(inputs=inputs)
    
    output = parse_json_from_string(result.raw, update=False)

    if output:
        details_key = f"history:topic_details:{contact_id}:{topic_id}"
        
        # Update the existing topic details with the cleaned version
        existing_details_json = redis_client.get(details_key)
        if existing_details_json:
            existing_details = json.loads(existing_details_json)
            existing_details['summary'] = output.get('cleaned_summary')
            existing_details['full_details'] = output.get('cleaned_details')
            existing_details['is_noisy'] = False # Mark as cleaned
            redis_client.set(details_key, json.dumps(existing_details))

    logger.info(f"[{contact_id}] - Finished data quality task for topic {topic_id}.")
    return f"Data quality for topic {topic_id} of contact {contact_id} improved."


@celery_app.task(name='enrichment.state_summarizer')
def state_summarizer_task(history_summary: dict, contact_id: str, last_turn_state: dict):
    """
    Asynchronous task to summarize and enrich the conversation state.
    """
    logger.info(f"[{contact_id}] - Starting state summarization.")

    state = state_manager.get_state(contact_id)

    disclousure_checklist = state.disclosure_checklist
    strategic_plan = state.strategic_plan

    agent = get_state_summarizer_agent()
    task = create_summarize_state_task(agent)

    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

    inputs = {
        "history_summary": json.dumps(history_summary),
        "last_turn_state": json.dumps(last_turn_state),
        "client_message": str(redis_client.get(f"{contact_id}:last_processed_messages"))
    }
    
    result = crew.kickoff(inputs=inputs)
    
    enriched_state = parse_json_from_string(result.raw, update=False)

    if enriched_state:

        new_state = ConversationState(**enriched_state)

        new_state.disclosure_checklist = disclousure_checklist
        new_state.strategic_plan = strategic_plan

        state_manager.save_state(contact_id, new_state)

    logger.info(f"[{contact_id}] - Finished state summarization.")
    return enriched_state

@celery_app.task(name='enrichment.profile_enhancer')
def profile_enhancer_task(history_summary: dict, contact_id: str, last_turn_state: dict):
    """
    Asynchronous task to enhance the long-term customer profile.
    Receives history_summary from the previous task in the chain.
    """
    logger.info(f"[{contact_id}] - Starting profile enhancement.")

    agent = get_profile_enhancer_agent()
    task = create_enhance_profile_task(agent)

    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

    # Fetch the existing profile from Redis
    existing_profile_raw = redis_client.get(f"{contact_id}:customer_profile")
    existing_profile = existing_profile_raw if existing_profile_raw else "{}"

    inputs = {
        "contact_id": contact_id,
        "history_summary": json.dumps(history_summary),
        "last_turn_state": json.dumps(last_turn_state),
        "existing_profile": existing_profile,
        "client_message": str(redis_client.get(f"{contact_id}:last_processed_messages"))
    }
    
    result = crew.kickoff(inputs=inputs)
    
    output = parse_json_from_string(result.raw, update=False)

    if output:
        profile_key = f"{contact_id}:customer_profile"

        master_profile = output.get('master_profile')

        if master_profile:
            redis_client.set(profile_key, json.dumps(master_profile))

    # Cleaning up last messages
    redis_client.delete(f"{contact_id}:last_processed_messages")

    logger.info(f"[{contact_id}] - Finished profile enhancement.")
    return f"Profile for {contact_id} enhanced."


def trigger_enrichment_pipeline(contact_id: str, last_turn_state: dict):
    """
    Triggers the full asynchronous enrichment pipeline using an optimized fan-out architecture.
    1. The history is summarized.
    2. The history summary is then passed to two parallel tasks:
       - State Summarizer
       - Profile Enhancer
    """
    logger.info(f"[{contact_id}] - Triggering optimized fan-out enrichment pipeline.")

    # The history summary is passed as the first argument to the tasks in the group.
    # We pass the remaining arguments (contact_id, last_turn_state) to the group tasks.
    pipeline = chain(
        history_summarizer_task.s(contact_id=contact_id),
        group(
            state_summarizer_task.s(contact_id=contact_id, last_turn_state=last_turn_state),
            profile_enhancer_task.s(contact_id=contact_id, last_turn_state=last_turn_state)
        )
    )

    pipeline.apply_async()

    logger.info(f"[{contact_id}] - Optimized fan-out enrichment pipeline successfully dispatched.")