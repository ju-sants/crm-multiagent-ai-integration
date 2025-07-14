from flask import Flask, jsonify, request
import json
import requests
from datetime import datetime, timedelta
import logging
import time

from app.services.celery_service import celery_app
from app.core.logger import get_logger
from app.config.settings import settings
from app.config.patches import apply_litellm_patch
from app.services.state_manager_service import StateManagerService
from app.crews.main_crews.context_analysis import context_analysis_task
from app.crews.main_crews.routing import routing_task
from celery import chain
from app.services.redis_service import get_redis
from app.services.transcript_service import transcript
from app.services.image_describer_service import ImageDescriptionAPI
from app.crews.enrichment_crew import raw_history_to_messages

CALLBELL_API_KEY = settings.CALLBELL_API_KEY
CALLBELL_API_BASE_URL = "https://api.callbell.eu/v1"
IMAGE_EXTENSIONS = ['.png', '.jpg', '.gif', '.webp', '.jpeg']


app = Flask(__name__)
apply_litellm_patch()
redis_client = get_redis()
# redis_client.flushdb()
# exit()
redis_client.delete("processing:71464be80c504971ae263d710b39dd1f")

# redis_client.rpop("contacts_messages:waiting:71464be80c504971ae263d710b39dd1f")
# redis_client.delete("contacts_messages:waiting:71464be80c504971ae263d710b39dd1f")
# redis_client.rpush("contacts_messages:waiting:71464be80c504971ae263d710b39dd1f", 'voltou a funcionar corretamente, queria falar dos orçamentos')

# print(redis_client.lrange("contacts_messages:waiting:71464be80c504971ae263d710b39dd1f", 0, -1))
# redis_client.flushdb()

state_manager = StateManagerService()
# print(json.dumps(state_manager.get_state("71464be80c504971ae263d710b39dd1f").strategic_plan, indent=4))
# exit()
# state.strategic_plan = None
# state_manager.save_state("71464be80c504971ae263d710b39dd1f", state)

client_description = ImageDescriptionAPI(settings.APPID_IMAGE_DESCRIPTION, settings.SECRET_IMAGE_DESCRIPTION)
logger:  logging.Logger = get_logger(__name__)

def get_callbell_headers():
    """Retorna os headers padrão para as requisições Callbell."""
    return {
        'Authorization': f'Bearer {settings.CALLBELL_API_KEY}',
        'Content-Type': 'application/json',
    }

def send_callbell_message(phone_number, text):
    """Envia uma mensagem de texto simples via Callbell."""
    url = f"{CALLBELL_API_BASE_URL}/messages/send"
    payload = {
        'to': phone_number,
        'from': 'whatsapp',
        'type': 'text',
        'content': {'text': text},
    }
    logger.info(f"Enviando mensagem simples para {phone_number}: {text}")
    try:
        response = requests.post(url, headers=get_callbell_headers(), json=payload)
        response.raise_for_status()
        logger.info(f"Mensagem simples enviada com sucesso para {phone_number}.")
        return True
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao enviar mensagem simples para {phone_number}: {e}")
        logger.error(f"Payload enviado: {json.dumps(payload)}")
        logger.error(f"Resposta recebida (se houver): {e.response.status_code} - {e.response.text if e.response else 'N/A'}")
        return False
    
    except Exception as e:
        logger.error(f"Erro inesperado ao processar envio de mensagem simples para {phone_number}: {e}")
        return False


@celery_app.task(name='io.process_audio_attachment')
def process_audio_attachment_task(contact_uuid, url):
    logger.info(f"[{contact_uuid}] - Transcribing audio from URL: {url}")
    redis_client.set(f"transcribing:audio:{contact_uuid}", "true")

    try:
        transcription = transcript(url)
        if transcription:
            message = f"(Áudio transcrito): {transcription}"
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
        description = description_json.get('data', {}).get('content', '')
        if description:
            message = f"(Descrição de imagem): {description}"
            redis_client.rpush(f'contacts_messages:waiting:{contact_uuid}', message)
            static_url_part = url.split('uploads/')[1].split('?')[0]
            redis_client.hset(f'{contact_uuid}:attachments', static_url_part, message)
    
    except Exception as e:
        logger.error(f"Error processing image attachment for contact {contact_uuid}: {e}")
    finally:
        redis_client.delete(f"transcribing:image:{contact_uuid}")

@celery_app.task(name='main.process_message_task')
def process_message_task(contact_uuid):
    """
    This task processes the aggregated messages for a contact after a debounce period.
    It now serves as the entrypoint to the Celery State Machine.
    """
    logger.info(f"[{contact_uuid}] - Debounced task started. Initializing state machine.")
    
    redis_client.delete(f'pending_task:{contact_uuid}')

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
        
        contact_info = json.loads(contact_info_raw)
        phone_number = str(contact_info.get("phoneNumber", "")).replace('+', '')
        contact_name = contact_info.get("name", "")

        state = state_manager.get_state(contact_uuid)
        state.metadata.phone_number = phone_number
        state.metadata.contact_name = contact_name
        state_manager.save_state(contact_uuid, state)
        
        pipeline = chain(
            context_analysis_task.s(contact_id=contact_uuid),
            routing_task.s()
        )
        pipeline.apply_async()
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

    text = str(payload.get('text', ''))
    text = '' if text == 'None' else text
    
    content = payload.get('attachments', [])
    
    # --- Attachment Processing ---
    content_audio = [attach for attach in content if '.mp3' in attach]
    content_image = [attach for attach in content if any(ext in attach for ext in IMAGE_EXTENSIONS)]

    for audio_url in content_audio:
        process_audio_attachment_task.delay(contact_uuid, audio_url)
    
    for image_url in content_image:
        process_image_attachment_task.delay(contact_uuid, image_url)

    if text:
        redis_client.rpush(f'contacts_messages:waiting:{contact_uuid}', text)
        logger.info(f'[{contact_uuid}] - Message text added to Redis queue.')

    # --- Debounce Logic ---
    pending_task_key = f'pending_task:{contact_uuid}'
    existing_task_id = redis_client.get(pending_task_key)
    
    if existing_task_id:
        celery_app.control.revoke(existing_task_id.decode('utf-8'))
        logger.info(f"[{contact_uuid}] - Revoked previous pending task: {existing_task_id.decode('utf-8')}")

    new_task = process_message_task.apply_async(args=[contact_uuid], eta=datetime.now() + timedelta(seconds=1))
    redis_client.set(pending_task_key, new_task.id, ex=30)
    logger.info(f"[{contact_uuid}] - Scheduled new processing task {new_task.id} in 1 seconds.")


@app.route('/receive_message', methods=['POST'])
def receive_message():
    webhook_payload = request.get_json()
    if not webhook_payload:
        logger.info("Webhook: Payload vazio recebido.")
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
            process_incoming_message(payload)
                
    return jsonify({'status': 'ok'}), 200


if __name__ == '__main__':
    app.run('0.0.0.0', port=8080)