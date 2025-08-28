from flask import Flask, jsonify, request
import json

from datetime import datetime, timedelta
from structlog.stdlib import BoundLogger
import time

from celery import signals
import redis

# Importações locais
from app.models.data_models import ConversationState

from app.core.logger import get_logger

from app.config.settings import settings
from app.patches.litellm_patch import apply_litellm_patch
from app.patches.crewai_telemetry_patch import apply_crewai_telemetry_patch

from app.services.celery_service import celery_app
from app.services.state_manager_service import StateManagerService
from app.services.redis_service import get_redis
from app.services.transcript_service import transcript
from app.services.image_describer_service import ImageDescriptionAPI
from app.services.nlp_service import carregar_modelo_semantico, extrair_nome_contato

from app.crews.src.main_crews.routing_agent import pre_routing_orchestrator
from app.crews.src.main_crews.communication import communication_task

from app.utils.static import default_strategic_plan

@signals.worker_ready.connect
def on_worker_ready(sender, **kwargs):
    get_logger(__name__).info(f"Celery worker ready: {sender.hostname}")

@signals.worker_shutdown.connect
def on_worker_shutdown(sender, **kwargs):
    get_logger(__name__).warning(f"Celery: Worker {getattr(sender, 'hostname', 'unknown')} is shutting down.")

IMAGE_EXTENSIONS = ['.png', '.jpg', '.gif', '.webp', '.jpeg']

apply_litellm_patch()
apply_crewai_telemetry_patch()

# Pre carregamento do modelo semântico
carregar_modelo_semantico()

app: Flask = Flask(__name__)
state_manager: StateManagerService = StateManagerService()
redis_client: redis.Redis = get_redis()
client_description: ImageDescriptionAPI = ImageDescriptionAPI(settings.APPID_IMAGE_DESCRIPTION, settings.SECRET_IMAGE_DESCRIPTION)
logger: BoundLogger = get_logger(__name__)

@celery_app.task(name='io.process_audio_attachment')
def process_audio_attachment_task(contact_uuid, url):
    logger.info(f"[{contact_uuid}] - Transcribing audio from URL: {url}")
    redis_client.set(f"transcribing:audio:{contact_uuid}", "true")

    try:
        transcription = transcript(url)
        if transcription:
            message = f"(Áudio transcrito): {transcription.strip()}"
            redis_client.rpush(f'contacts_messages:waiting:{contact_uuid}', message)
            static_url_part = url.split('uploads/')[1].split('?')[0]
            redis_client.hset(f'{contact_uuid}:attachments', static_url_part, transcription)

    except Exception as e:
        logger.error(f"Error processing audio attachment for contact {contact_uuid}: {e}")
    finally:
        redis_client.delete(f"transcribing:audio:{contact_uuid}")

@celery_app.task(name='io.process_image_attachment')
def process_image_attachment_task(contact_uuid, url):
    logger.info(f"[{contact_uuid}] - Describing image from URL: {url}")
    redis_client.set(f"transcribing:image:{contact_uuid}", "true")
    
    try:
        description_json = client_description.describe_image(image_url=url)
        description = str(description_json.get('data', {}).get('content', ''))
        if description:
            message = f"(Descrição de imagem): {description.strip()}"
            redis_client.rpush(f'contacts_messages:waiting:{contact_uuid}', message)
            static_url_part = url.split('uploads/')[1].split('?')[0]
            redis_client.hset(f'{contact_uuid}:attachments', static_url_part, message)
    
    except Exception as e:
        logger.error(f"Error processing image attachment for contact {contact_uuid}: {e}")
    finally:
        redis_client.delete(f"transcribing:image:{contact_uuid}")

@celery_app.task(name='main.process_message_task', bind=True)
def process_message_task(self, contact_uuid):
    """
    This task processes the aggregated messages for a contact after a debounce period.
    It now serves as the entrypoint to the Celery State Machine.
    """
    pending_task_key = f'pending_task:{contact_uuid}'
    latest_task_id = redis_client.get(pending_task_key)

    if not latest_task_id:
        logger.warning(f"[{contact_uuid}] - No pending task found in Redis for task {self.request.id}. Aborting.")
        return

    if latest_task_id != self.request.id:
        logger.warning(f"[{contact_uuid}] - Stale task {self.request.id} found. Latest task is {latest_task_id}. Aborting.")
        return

    # The valid task consumes its execution token to ensure idempotency.
    redis_client.delete(pending_task_key)

    logger.info(f"[{contact_uuid}] - Debounced task {self.request.id} started. Initializing state machine.")

    contact_lock = redis_client.set(f'processing:{contact_uuid}', value='1', nx=True, ex=300)
    if not contact_lock:
        logger.warning(f"[{contact_uuid}] - Could not acquire lock. Another process is already handling this contact.")
        return

    try:
        for _ in range(5):
            try:
                contact_info_raw = redis_client.get(f"contact_info:{contact_uuid}")
                if not contact_info_raw:
                    logger.error(f"[{contact_uuid}] - Could not retrieve contact info from Redis. Retrying in 2 seconds...")
                    time.sleep(2)
                
                else:
                    break

            except Exception as e:
                logger.error(f"[{contact_uuid}] - Error retrieving contact info from Redis: {e}. Retrying in 2 seconds...")
                time.sleep(2)
                
        if not contact_info_raw:
            logger.error(f"[{contact_uuid}] - Could not retrieve contact info from Redis. Aborting task.")
            return
        
        contact_info = json.loads(str(contact_info_raw))
        phone_number = str(contact_info.get("phoneNumber", "")).replace('+', '')
        contact_name = contact_info.get("name", "")

        with redis_client.lock(f"lock:state:{contact_uuid}", timeout=10):
            state, is_new = state_manager.get_state(contact_uuid)
            state.metadata.phone_number = phone_number
            state.metadata.contact_name = contact_name
            state.metadata.extracted_name = extrair_nome_contato(str(contact_name))
            state_manager.save_state(contact_uuid, state)

        # Verify if theres another instance processing the strategy, waiting before routing agent can judge the strategy properly
        if redis_client.exists(f"doing_strategy:{contact_uuid}") or redis_client.exists(f"refining_strategy:{contact_uuid}"):
            logger.info(f"[{contact_uuid}] - Strategy is already being refined / created. Waiting...")
            while redis_client.exists(f"doing_strategy:{contact_uuid}") or redis_client.exists(f"refining_strategy:{contact_uuid}"):
                time.sleep(1)
            
            logger.info(f"[{contact_uuid}] - Strategy is ready. Continuing...")

        # Adicionando o contato na lista de contatos se não estiver lá
        if not redis_client.sismember("contacts", contact_uuid):
            logger.info(f"[{contact_uuid}] - Adding contact {contact_uuid} to contacts set.")
            redis_client.sadd("contacts", contact_uuid)


        # Roteamento
        if not is_new:
            pre_routing_orchestrator.apply_async(args=[contact_uuid])
        
        else:
            with redis_client.lock(f"lock:state:{contact_uuid}", timeout=10):
                state, _ = state_manager.get_state(contact_uuid)
                state_dict = state.model_dump()
                state_dict['strategic_plan'] = default_strategic_plan

                state = ConversationState(**{**state.model_dump(), **state_dict})

                state_manager.save_state(contact_uuid, state)

            communication_task.apply_async(args=[contact_uuid])


        logger.info(f"[{contact_uuid}] - Celery state machine triggered.")

    except Exception as e:
        logger.error(f"[{contact_uuid}] - CRITICAL ERROR at the start of the state machine: {e}", exc_info=True)
    
def process_incoming_message(payload):
    """
    Handles the initial processing of an incoming message webhook.
    - Extracts message text and attachments.
    - Saves data to Redis.
    - Schedules the debounced processing task.
    """
    contact_info = payload.get("contact")
    contact_uuid = contact_info.get("uuid")
    logger.info(f'[{contact_uuid}] - INICIANDO process_incoming_message')

    # Store contact info for the async task
    redis_client.set(f"contact_info:{contact_uuid}", json.dumps(contact_info), ex=86400) # Expire after 1 day

    text = ""
    if 'messageContext' in payload and 'target' in payload['messageContext'] and 'text' in payload['messageContext']['target']:
        if payload['messageContext']['target']['text'] != "None":
            text = f"Resposta direta a mensagem `{payload['messageContext']['target']['text']}`:\n"

    text += str(payload.get('text', ''))
    
    content = payload.get('attachments', [])
    
    # --- Attachment Processing ---
    content_audio = [attach for attach in content if '.mp3' in attach]
    content_image = [attach for attach in content if any(ext in attach for ext in IMAGE_EXTENSIONS)]

    for audio_url in content_audio:
        process_audio_attachment_task.apply_async(contact_uuid, audio_url)
    
    for image_url in content_image:
        process_image_attachment_task.apply_async(contact_uuid, image_url)

    if text:
        redis_client.rpush(f'contacts_messages:waiting:{contact_uuid}', text)
        logger.info(f'[{contact_uuid}] - Message text added to Redis queue.')

    # --- Debounce Logic ---
    pending_task_key = f'pending_task:{contact_uuid}'
    existing_task_id = redis_client.get(pending_task_key)
    
    if existing_task_id:
        logger.info(f"[{contact_uuid}] - A pending task {existing_task_id} already exists. It will be replaced.")
        # Revoke the old task
        celery_app.control.revoke(existing_task_id, terminate=True)
        logger.info(f"[{contact_uuid}] - Revoked previous pending task: {existing_task_id}")

    # Schedule the new task
    new_task = process_message_task.apply_async(args=[contact_uuid], eta=datetime.now() + timedelta(seconds=4))
    
    # Atomically set the new task ID
    redis_client.set(pending_task_key, new_task.id, ex=60) # Increased expiry for safety
    
    logger.info(f"[{contact_uuid}] - Scheduled new processing task {new_task.id} to run in 4 seconds. Pending task key set.")


@app.route('/receive_message', methods=['POST'])
def receive_message():
    webhook_payload = request.get_json()
    logger.info("Webhook: Received payload", uuid=webhook_payload.get("payload", {}).get("uuid", "N/A"))
    if not webhook_payload:
        logger.info("Webhook: Payload is empty.")
        return jsonify({"status": "ok", "message": "Empty payload"}), 200

    event = webhook_payload.get("event")
    payload = webhook_payload.get("payload")

    if event == "message_created" and payload and payload.get("status") == "received":
        contact_info = payload.get("contact")
        if not contact_info or not contact_info.get("uuid"):
            logger.warning("Webhook: Mensagem recebida sem 'contact.uuid'. Ignorando.")
            return jsonify({"status": "ok", "message": "No contact UUID"}), 200
        
        # Alessandro's team UUID
        if contact_info.get("team", {}).get("uuid") == "d468731afdba45c3a3a65895e4b08a5a":
            # Salvando o timestamp da última mensagem recebida
            redis_client.set(f"history:last_timestamp:to_follow_up:{contact_info['uuid']}", str(datetime.now().isoformat()))
            redis_client.delete(f"follow_up_level:{contact_info['uuid']}")  # Reset follow-up level on new message
            logger.info(f"Webhook: Received message from contact {contact_info['uuid']}. Processing...")
            
            # Roteamento
            process_incoming_message(payload)
                
    return jsonify({'status': 'ok'}), 200


if __name__ == '__main__':
    app.run('0.0.0.0', port=8080)