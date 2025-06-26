import json
from celery import group, chain
from crewai import Crew, Process

from app.config.settings import settings
from app.core.logger import get_logger
from app.services.redis_service import get_redis
from app.services.celery_Service import celery_app
from app.utils.funcs.funcs import parse_json_from_string
from app.services.callbell_service import get_contact_messages

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
    Asynchronous task to summarize conversation history.
    - Fetches the last 50 messages from Callbell.
    - Creates a hierarchical summary of the conversation.
    - Detects noisy data and flags it.
    - Stores the summary and topic details in Redis.
    """
    logger.info(f"[{contact_id}] - Starting history summarization.")
    
    raw_history = get_contact_messages(contact_id, limit=50)
    if not raw_history:
        logger.warning(f"[{contact_id}] - No history found. Skipping summarization.")
        return f"No history to summarize for {contact_id}."

    agent = get_history_summarizer_agent()
    task = create_summarize_history_task(agent)
    
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    
    inputs = {
        "contact_id": contact_id,
        "raw_history": json.dumps(raw_history)
    }
    
    result = crew.kickoff(inputs=inputs)
    
    output = parse_json_from_string(result.raw, update=False)
    
    if output:
        # Save the main summary
        summary_key = f"history:{contact_id}"
        redis_client.set(summary_key, json.dumps(output['hierarchical_summary']))
        
        # Save details for each topic and check for noise
        for topic_detail in output.get('topic_details', []):
            topic_id = topic_detail.get('topic_id')
            if topic_id:
                details_key = f"history:topic_details:{contact_id}:{topic_id}"
                redis_client.set(details_key, json.dumps(topic_detail))
                
                # If topic is noisy, trigger the data quality agent
                # Trigger data quality task based on the new quality score
                quality_score = topic_detail.get('quality_score', 1.0)
                if quality_score < 0.6:
                    logger.info(f"[{contact_id}] - Topic {topic_id} has low quality score ({quality_score}). Triggering data quality task.")
                    start_index = topic_detail.get('start_index')
                    end_index = topic_detail.get('end_index')

                    if start_index is not None and end_index is not None:
                        # Slice the raw history to get the relevant snippet for the noisy topic
                        raw_history_snippet = raw_history[start_index:end_index + 1]
                        # Pass the full history for context, as per Action Item 2
                        data_quality_task.delay(contact_id, topic_id, json.dumps(raw_history_snippet), json.dumps(raw_history))
                    else:
                        logger.warning(f"[{contact_id}] - Could not trigger data quality task for topic {topic_id} due to missing indices.")

    logger.info(f"[{contact_id}] - Finished history summarization.")
    return f"History for {contact_id} summarized."

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
def state_summarizer_task(contact_id: str, last_turn_state: dict):
    """
    Asynchronous task to summarize and enrich the conversation state.
    """
    logger.info(f"[{contact_id}] - Starting state summarization.")
    
    agent = get_state_summarizer_agent()
    task = create_summarize_state_task(agent)
    
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    
    inputs = {
        "last_turn_state": json.dumps(last_turn_state)
    }
    
    result = crew.kickoff(inputs=inputs)
    
    enriched_state = parse_json_from_string(result.raw, update=False)

    if enriched_state:
        state_key = f"state:{contact_id}"
        redis_client.set(state_key, json.dumps(enriched_state))

    logger.info(f"[{contact_id}] - Finished state summarization.")
    return f"State for {contact_id} summarized."

@celery_app.task(name='enrichment.profile_enhancer')
def profile_enhancer_task(results, contact_id: str):
    """
    Asynchronous task to enhance the long-term customer profile.
    'results' is the ignored output from the preceding parallel tasks.
    """
    logger.info(f"[{contact_id}] - Starting profile enhancement.")
    
    agent = get_profile_enhancer_agent()
    task = create_enhance_profile_task(agent)
    
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    
    # Fetch the necessary data from Redis
    history_summary = redis_client.get(f"history:{contact_id}")
    enriched_state = redis_client.get(f"state:{contact_id}")
    existing_profile = redis_client.get(f"{contact_id}:customer_profile")

    inputs = {
        "contact_id": contact_id,
        "history_summary": history_summary if history_summary else "{}",
        "enriched_state": enriched_state if enriched_state else "{}",
        "existing_profile": existing_profile if existing_profile else "{}"
    }
    
    result = crew.kickoff(inputs=inputs)
    
    output = parse_json_from_string(result.raw, update=False)

    if output:
        profile_key = f"{contact_id}:customer_profile"
        distilled_profile_key = f"{contact_id}:distilled_profile"

        master_profile = output.get('master_profile')
        distilled_profile = output.get('distilled_profile_for_agents')

        if master_profile:
            redis_client.set(profile_key, json.dumps(master_profile))
        if distilled_profile:
            redis_client.set(distilled_profile_key, json.dumps(distilled_profile))

    logger.info(f"[{contact_id}] - Finished profile enhancement.")
    return f"Profile for {contact_id} enhanced."


def trigger_enrichment_pipeline(contact_id: str, last_turn_state: dict):
    """
    Triggers the full asynchronous enrichment pipeline.
    The history and state are summarized in parallel. Once both are complete,
    the profile enhancer is triggered.
    """
    logger.info(f"[{contact_id}] - Triggering asynchronous enrichment pipeline.")
    
    pipeline = group(
        history_summarizer_task.s(contact_id=contact_id),
        state_summarizer_task.s(contact_id=contact_id, last_turn_state=last_turn_state)
    ) | profile_enhancer_task.s(contact_id=contact_id)
    
    pipeline.apply_async()
    
    logger.info(f"[{contact_id}] - Enrichment pipeline successfully dispatched.")