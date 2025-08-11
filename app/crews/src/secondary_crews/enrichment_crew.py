import json
from celery import group, chain
from crewai import Crew, Process
from typing import Any
from datetime import datetime
import time

from app.core.logger import get_logger
from app.services.redis_service import get_redis
from app.services.celery_service import celery_app
from app.utils.funcs.parse_llm_output import parse_json_from_string
from app.services.callbell_service import get_contact_messages, send_message
from app.services.state_manager_service import StateManagerService
from app.models.data_models import ConversationState
from app.utils.funcs.funcs import distill_conversation_state

SUMMARIZER_HISTORY_TOPIC_LIMIT = 15

state_manager = StateManagerService()

# Import agent and task creation functions
from app.crews.agents_definitions.obj_declarations.agent_declaration import (
    get_history_summarizer_agent,
    get_data_quality_agent,
    get_state_summarizer_agent,
    get_profile_enhancer_agent
)
from app.crews.agents_definitions.obj_declarations.tasks_declaration import (
    create_summarize_history_task,
    create_clean_noisy_data_task,
    create_summarize_state_task,
    create_enhance_profile_task
)


logger = get_logger(__name__)
redis_client = get_redis()

def process_history(history: Any, contact_id: str) -> str:
    """Processes the message history and returns a formatted string."""
    history_normalized = []

    for message in history:
        if message.get("attachments"):

            attachments = message.get("attachments", [])
            if not attachments:
                history_normalized.append(message)
                continue

            list_of_dicts = isinstance(attachments[0], dict)

            for attachment in attachments:
                raw_url = attachment.get("payload", {}).get('url', '') if list_of_dicts else attachment

                if "audio_eleven_agent_AI" in raw_url:
                    url = raw_url
                else:
                    url = raw_url.split('uploads/')[1].split('?')[0] if 'uploads/' in raw_url else ''

                if url:
                    mapped_attachments = redis_client.hgetall(f"{contact_id}:attachments")
                    if mapped_attachments:
                        attachment_text = mapped_attachments.get(url, "")
                        if attachment_text:
                            message["text"] = attachment_text
                            del message["attachments"]

                            history_normalized.append(message)
                            continue

        else:
            history_normalized.append(message)

    return history_normalized

def raw_history_to_messages(history: list, contact_id: str) -> str:
    """Converts raw history to a string of messages."""
    messages = []
    for message in history:
        if message.get("attachments"):
            attachments = message.get("attachments", [])
            if not attachments:
                messages.append(f'{"Agente IA - " if message.get("status", "") == "sent" else "customer - "}' + f"'{message.get('text', '')}'")
                continue

            list_of_dicts = isinstance(attachments[0], dict)
            for attachment in attachments:
                raw_url = attachment.get("payload", {}).get('url', '') if list_of_dicts else attachment
                if "audio_eleven_agent_AI" in raw_url:
                    url = raw_url
                else:
                    url = raw_url.split('uploads/')[1].split('?')[0] if 'uploads/' in raw_url else ''

                if url:
                        mapped_attachments = redis_client.hgetall(f"{contact_id}:attachments")
                        if mapped_attachments:
                            attachment_text = mapped_attachments.get(url, "")
                            if attachment_text:
                                message["text"] = attachment_text
                                del message["attachments"]

                                messages.append(f'{"Agente IA - " if message.get("status", "") == "sent" else "customer - "}' + f"'{message.get('text', '')}'")
        else:
            if message.get("text"):
                messages.append(f'{"Agente IA - " if message.get("status", "") == "sent" else "customer - "}' + f"'{message.get('text', '')}'")

    return "\n".join([str(msg) for msg in messages])

@celery_app.task(name='enrichment.history_summarizer')
def history_summarizer_task(previous_task_result=None, *, contact_id: str):
    """
    Asynchronous task to incrementally summarize conversation history.
    - Fetches only new messages since the last update.
    - Intelligently merges new messages into the existing summary.
    - Detects noisy data and flags it.
    - Stores the updated summary, topic details, and last message timestamp in Redis.
    """
    logger.info(f"[{contact_id}] - Starting incremental history summarization.")

    summary_key = f"longterm_history:{contact_id}"
    timestamp_key = f"history:last_timestamp:{contact_id}"

    # Get existing data from Redis
    existing_summary_json = redis_client.get(summary_key)
    last_timestamp = redis_client.get(timestamp_key)
    
    existing_summary = json.loads(existing_summary_json) if existing_summary_json else None
    if existing_summary and existing_summary.get("topic_details"):
        existing_summary["topic_details"] = existing_summary["topic_details"][-SUMMARIZER_HISTORY_TOPIC_LIMIT:]
    
    # Fetch new messages
    if last_timestamp:
        logger.info(f"[{contact_id}] - Fetching new messages since {last_timestamp}.")
        new_messages = get_contact_messages(contact_id, since_timestamp=last_timestamp)
    else:
        logger.info(f"[{contact_id}] - No existing summary found. Fetching full history.")
        new_messages = get_contact_messages(contact_id, limit=50)
    
    if contact_id == '71464be80c504971ae263d710b39dd1f':
        new_messages = [msg for msg in new_messages if datetime.strptime(msg.get("createdAt"), "%Y-%m-%dT%H:%M:%SZ") > datetime.strptime("10/08/2025 13:10:00", "%d/%m/%Y %H:%M:%S")]

    if not new_messages:
        logger.info(f"[{contact_id}] - No new messages to process. Skipping summarization.")
        return f"No new messages to summarize for {contact_id}."
    
    # The full history for context is the combination of old and new
    raw_history_json = redis_client.get(f"history_raw:{contact_id}")
    raw_history = json.loads(raw_history_json) if raw_history_json else []
    full_history = raw_history + new_messages
    full_history = full_history[-15:]
    redis_client.set(f"history_raw:{contact_id}", json.dumps(full_history))

    # Normalize the history
    normalized_history = raw_history_to_messages(full_history, contact_id)
    normalized_history = normalized_history.replace("*Alessandro Assistente Global:*\n", "")
    redis_client.set(f"shorterm_history:{contact_id}", normalized_history)

    agent = get_history_summarizer_agent()
    task = create_summarize_history_task(agent)
    
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)
    
    inputs = {
        "contact_id": contact_id,
        "existing_summary": json.dumps(existing_summary) if existing_summary else "null",
        "new_messages": json.dumps(new_messages),
        "raw_history": json.dumps(full_history)
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
                        data_quality_task.apply_async(contact_id, topic_id, json.dumps(raw_history_snippet), json.dumps(full_history))
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
def state_summarizer_task(longterm_history: dict, contact_id: str):
    """
    Asynchronous task to summarize and enrich the conversation state.
    """
    logger.info(f"[{contact_id}] - Starting state summarization.")

    state, _ = state_manager.get_state(contact_id)

    disclousure_checklist = state.disclosure_checklist
    strategic_plan = state.strategic_plan
    current_turn_number = state.metadata.current_turn_number

    agent = get_state_summarizer_agent()
    task = create_summarize_state_task(agent)

    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

    conversation_state_distilled = distill_conversation_state(state, "StateSummarizerAgent")

    shorterm_history = redis_client.get(f"shorterm_history:{contact_id}")

    inputs = {
        "longterm_history": json.dumps(longterm_history),
        "shorterm_history": str(shorterm_history),
        "last_turn_state": json.dumps(conversation_state_distilled),
        "client_message": str(redis_client.get(f"{contact_id}:last_processed_messages"))
    }
    
    result = crew.kickoff(inputs=inputs)
    
    enriched_state = parse_json_from_string(result.raw, update=False)
    
    if enriched_state:
        
        disclousure_checklist_data = [dc.model_dump() for dc in disclousure_checklist] if disclousure_checklist else []

        enriched_state['disclosure_checklist'] = disclousure_checklist_data
        enriched_state['strategic_plan'] = strategic_plan
        
        if enriched_state.get("metadata"):
            enriched_state["metadata"]["current_turn_number"] = current_turn_number

        with redis_client.lock(f"lock:state:{contact_id}", timeout=10):
            state, _ = state_manager.get_state(contact_id)
            new_state = ConversationState(**{**state.model_dump(), **enriched_state})

            state_manager.save_state(contact_id, new_state)

    logger.info(f"[{contact_id}] - Finished state summarization.")
    return enriched_state

@celery_app.task(name='enrichment.profile_enhancer')
def profile_enhancer_task(longterm_history: dict, contact_id: str):
    """
    Asynchronous task to enhance the long-term customer profile.
    Receives longterm_history from the previous task in the chain.
    """
    logger.info(f"[{contact_id}] - Starting profile enhancement.")
    state, _ = state_manager.get_state(contact_id)
    last_turn_state = state.model_dump()

    agent = get_profile_enhancer_agent()
    task = create_enhance_profile_task(agent)

    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=True)

    # Fetch the existing profile from Redis
    existing_profile_raw = redis_client.get(f"{contact_id}:customer_profile")
    existing_profile = existing_profile_raw if existing_profile_raw else "{}"

    shorterm_history = redis_client.get(f"shorterm_history:{contact_id}")

    last_turn_state.pop('strategic_plan', None)
    last_turn_state.pop('disclosure_checklist', None)

    inputs = {
        "contact_id": contact_id,
        "longterm_history": json.dumps(longterm_history),
        "shorterm_history": str(shorterm_history),
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


@celery_app.task(name='enrichment.trigger_post_processing')
def trigger_post_processing(contact_id: str, send_message_task: bool = False, response_json: dict | None = None, phone_number: str | None = None):
    """
    Triggers the full asynchronous enrichment pipeline using an optimized fan-out architecture.
    1. If send_message_task is True, it sends a message to the phone number.
    2. The history is summarized.
    3. The history summary is then passed to two parallel tasks:
       - State Summarizer
       - Profile Enhancer
    """
    logger.info(f"[{contact_id}] - Triggering pipeline.")

    trigger_message_sending = False
    if send_message_task and phone_number and response_json:
        trigger_message_sending = True

    # PREPARANDO ENVIO DE CATÁLOGOS
    plan_names = []
    if response_json:
        state, _ = state_manager.get_state(contact_id)
        plan_names = response_json.get("plan_names", [])

        # Só enviaremos catálogos se o contexto operacional for BUDGET - Vendas
        plan_names = plan_names if plan_names and state.operational_context not in ("SUPPORT", "CUSTOMER_SERVICE") else [] 

    # =================================================================================================================
    
    lock_enrichment_pipeline = redis_client.set(f"lock_enrichment_pipeline:{contact_id}", "locked", nx=True)

    if not lock_enrichment_pipeline:
        logger.info(f"[{contact_id}] - Enrichment pipeline already running. Skipping.")
        redis_client.set("run_enrichment_pipeline_again", "true")

        if trigger_message_sending:
            logger.info(f"[{contact_id}] - Sending message to {phone_number}.")
            send_message.apply_async(args=[phone_number, response_json['messages_sequence'], plan_names, contact_id])

        return

    logger.info(f"[{contact_id}] - Enrichment pipeline lock acquired.")
    
    # The history summary is passed as the first argument to the tasks in the group.
    pipeline = None
    if trigger_message_sending:
        logger.info(f"[{contact_id}] - Preparing to send message to {phone_number}")
        pipeline = chain(
            send_message.s(phone_number=phone_number, messages=response_json['messages_sequence'], plan_names=plan_names, contact_id=contact_id),
            history_summarizer_task.s(contact_id=contact_id),
            group(
                state_summarizer_task.s(contact_id=contact_id),
                profile_enhancer_task.s(contact_id=contact_id),
            )
        )

    else:
        pipeline = chain(
            history_summarizer_task.s(contact_id=contact_id),
            group(
                state_summarizer_task.s(contact_id=contact_id),
                profile_enhancer_task.s(contact_id=contact_id)
            )
        )

    if pipeline:
        result = pipeline.apply_async()
        logger.info(f"[{contact_id}] - Optimized fan-out enrichment pipeline successfully dispatched.")

        try:
            while not result.ready():
                time.sleep(1)

            logger.info(f"[{contact_id}] - Optimized fan-out enrichment pipeline completed successfully.")
        
        except Exception as e:
            logger.error(f"[{contact_id}] - Error during enrichment pipeline execution: {e}")
            redis_client.set("run_enrichment_pipeline_again", "true")
            raise
        
        finally:
            redis_client.delete(f"lock_enrichment_pipeline:{contact_id}")
            if redis_client.get("run_enrichment_pipeline_again"):
                redis_client.delete("run_enrichment_pipeline_again")

                logger.info(f"[{contact_id}] - Enrichment pipeline re-triggered.")
                trigger_post_processing(contact_id)
    
    else:
        logger.error(f"[{contact_id}] - Failed to trigger enrichment pipeline due to missing parameters.")
        return {"status": "error", "reason": "Missing parameters for enrichment pipeline."}