from typing import Any, Dict, Optional
from time import sleep
from datetime import datetime
import requests
import json

from app.config.settings import settings
from app.core.logger import get_logger
from app.services.celery_service import celery_app
from app.services.state_manager_service import StateManagerService
from app.services.redis_service import get_redis
from app.services.eleven_labs_service import main as eleven_labs_service


state_manager = StateManagerService()
redis_client = get_redis()

logger = get_logger(__name__)



def send_callbell_message(contact_id, phone_number: str, messages: str = None, type: str = None, audio_url: str = None) -> Dict[str, Any]:
        """Envia uma mensagem via Callbell."""
        
        statuses = []

        if type and type == 'audio':
            sleep(2)
            
            url = "https://api.callbell.eu/v1/messages/send"
            headers = {
                "Authorization": f"Bearer {settings.CALLBELL_API_KEY}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "to": phone_number,
                "from": "whatsapp",
                "type": "document",
                "channel_uuid": "b3501c231325487086646e19fc647b0d",
                "content": {
                    "url": audio_url
                },
                "fields": "conversation,contact"
            }
            
            response = requests.post(url, json=payload, headers=headers)

            now = datetime.now()
            redis_client.set(f"history:last_timestamp:to_follow_up{contact_id}", now.isoformat())
            
            statuses.append(response.status_code)
        else:
            for i, message in enumerate(messages):
                sleep(1 if i % 3 != 0 else 3)
                
                url = "https://api.callbell.eu/v1/messages/send"
                headers = {
                    "Authorization": f"Bearer {settings.CALLBELL_API_KEY}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "to": phone_number,
                    "from": "whatsapp",
                    "type": "text",
                    "channel_uuid": "b3501c231325487086646e19fc647b0d",
                    "content": {
                        "text": f"*Alessandro Assistente Global:*\n{message}"
                    },
                    "fields": "conversation,contact",
                    "assigned_user": "alessandro-ia@alessandro-ia.com"
                }
                
                response = requests.post(url, json=payload, headers=headers)
                
                now = datetime.now()
                redis_client.set(f"history:last_timestamp:to_follow_up{contact_id}", now.isoformat())

                statuses.append(response.status_code)
            
        if all(status in (200, 201) for status in statuses):
            return {"status": "success"}
        else:
            return {"status": "error"}

def get_contact_messages(
    contact_uuid: str,
    limit: int = 50,
    since_timestamp: Optional[str] = None
) -> list:
    """
    Busca as mensagens de um contato na API da Callbell.
    - Se 'since_timestamp' for fornecido, busca mensagens desde esse timestamp.
    - Caso contrário, busca as últimas 'limit' mensagens.
    """
    url = f"https://api.callbell.eu/v1/contacts/{contact_uuid}/messages"
    headers = {
        "Authorization": f"Bearer {settings.CALLBELL_API_KEY}",
        "Content-Type": "application/json"
    }
    page = 1
    messages = []
    
    since_dt = None
    if since_timestamp:
        try:
            # Handle both 'Z' and potential timezone offsets like '+00:00'
            if since_timestamp.endswith('Z'):
                since_dt = datetime.fromisoformat(since_timestamp.replace('Z', '+00:00'))
            else:
                since_dt = datetime.fromisoformat(since_timestamp)
        except ValueError:
            logger.error(f"Invalid timestamp format for {contact_uuid}: {since_timestamp}")
            return []

    try:
        while True:
            params = {"page": page}
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            messages_temp = data.get("messages", [])

            if not messages_temp:
                break

            if since_dt:
                for msg in messages_temp:
                    msg_dt_str = msg.get("createdAt")
                    if msg_dt_str:
                        if msg_dt_str.endswith('Z'):
                            msg_dt = datetime.fromisoformat(msg_dt_str.replace('Z', '+00:00'))
                        else:
                            msg_dt = datetime.fromisoformat(msg_dt_str)
                        
                        if msg_dt > since_dt:
                            messages.append(msg)
                        else:
                            # Stop fetching as we have reached messages older than the timestamp
                            messages_temp = [] # Break outer loop
                            break
            else:
                messages.extend(messages_temp)
                if len(messages) >= limit:
                    break
            
            if not messages_temp:
                break
                
            page += 1

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch messages for contact {contact_uuid}: {e}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON for contact {contact_uuid}: {e}")
        return []
    
    # Return messages in chronological order (oldest to newest)
    return messages[::-1]

def create_conversation_note(uuid: str, note_text: str) -> bool:
    """
    Cria uma nota em uma conversa associada a um contato na plataforma Callbell.

    Parâmetros:
    - uuid (str): UUID do contato.
    - note_text (str): Texto da nota (pode incluir @ para mencionar usuários).
    - api_key (str): Chave de autenticação Bearer da API.

    Retorna:
    - bool: True se a requisição for bem-sucedida, False caso contrário.
    """
    url = f'https://api.callbell.eu/v1/contacts/{uuid}/conversation/note'
    
    headers = {
        'Authorization': f'Bearer {settings.CALLBELL_API_KEY}',
        'Content-Type': 'application/json',
    }
    
    payload = {
        'text': note_text,
    }

    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code == 201 or response.status_code == 200:
        return response.json().get('success', False)
    else:
        print(f"Erro {response.status_code}: {response.text}")
        return False
    
@celery_app.task(name='io.send_message')
def send_message(phone_number, messages, plan_names, contact_id):
    try:
        from app.utils.static import plans_messages
        
        state, _ = state_manager.get_state(contact_id)
        if state.prefers_audio:
            logger.info(f'[{contact_id}] - "prefers_audio" encontrado em state. Enviando mensagem de áudio.')
            audio_url = eleven_labs_service(messages)
            if audio_url:
                send_callbell_message(contact_id=contact_id, phone_number=phone_number, type="audio", audio_url=audio_url)
                redis_client.hset(f"{contact_id}:attachments", audio_url, ' '.join(messages))
            
            else:
                logger.info(f'[{contact_id}] - Não foi possível gerar áudio para a mensagem. Enviando mensagem de texto.')
                send_callbell_message(contact_id=contact_id, phone_number=phone_number, messages=messages)
        
        else:
        
            has_long_message = False
            for message in messages:
                if len(message) > 250:
                    has_long_message = True
            
            if has_long_message and not all([len(message) > 250 for message in messages]):
                logger.info(f"[{contact_id}] - Encontrada mensagem com mais de 250 caracteres. Enviando mensagem de áudio.")
                            
                for message in messages:
                    if len(message) > 250:
                        audio_url = eleven_labs_service([message])
                        if audio_url:
                            send_callbell_message(contact_id=contact_id, phone_number=phone_number, type="audio", audio_url=audio_url)
                            redis_client.hset(f"{contact_id}:attachments", audio_url, message)
                        else:
                            logger.info(f"[{contact_id}] - Não foi possível gerar áudio para a mensagem. Enviando mensagem de texto.")
                            send_callbell_message(contact_id=contact_id, phone_number=phone_number, messages=[message])

                    else:
                        send_callbell_message(contact_id=contact_id, phone_number=phone_number, messages=[message])
            
            else:
                logger.info(f"[{contact_id}] - Não encontrada mensagem com mais de 250 caracteres.")
                
                messages_all_str = '\n'.join(messages)
                if len(messages_all_str) > 300:
                    logger.info(f"[{contact_id}] - Todas as mensagens somam mais de 300 caracteres. Enviando mensagem de áudio.")

                    audios_messages_qnt = len(messages) // 2 + 1
                    audios_messages = messages[:audios_messages_qnt]
                    audios_messages_str = '\n'.join(audios_messages)

                    messages_left = messages[audios_messages_qnt:]

                    audio_url = eleven_labs_service(audios_messages)
                    if audio_url:
                        send_callbell_message(contact_id=contact_id, phone_number=phone_number, type="audio", audio_url=audio_url)
                        redis_client.hset(f"{contact_id}:attachments", audio_url, audios_messages_str)

                        if messages_left:
                            send_callbell_message(contact_id=contact_id, phone_number=phone_number, messages=messages_left)

                    else:
                        logger.info(f"[{contact_id}] - Não foi possível gerar áudio para a mensagem. Enviando mensagem de texto.")
                        send_callbell_message(contact_id=contact_id, phone_number=phone_number, messages=audios_messages)

                else:
                    logger.info(f"[{contact_id}] - Todas as mensagens somam menos de 300 caracteres. Enviando mensagens de texto.")
                    send_callbell_message(contact_id=contact_id, phone_number=phone_number, messages=messages)

        if plan_names:
            for plan_name in plan_names:
                message = plans_messages.get(plan_name, [])
                if message:
                    send_callbell_message(contact_id=contact_id, phone_number=phone_number, messages=[message])

            
        # After send message, update the state current turn number
        with redis_client.lock(f"lock:state:{contact_id}", timeout=10):
            state, _ = state_manager.get_state(contact_id)
            state.metadata.current_turn_number += 1
            state_manager.save_state(contact_id, state)

    except Exception as e:
        logger.error(f'[{contact_id}] - Erro ao enviar mensagens para Callbell: {e}')

    else:
        if plan_names:
            redis_client.rpush(f"{contact_id}:sended_catalogs", *plan_names)

    finally:
        redis_client.delete(f"processing:{contact_id}")
        logger.info(f'[{contact_id}] - Lock "processing:{contact_id}" LIBERADO no Redis.')
