from typing import Any, Dict, Optional
from time import sleep
from datetime import datetime
import requests
import json

from app.config.settings import settings
from app.core.logger import get_logger

logger = get_logger(__name__)



def send_callbell_message(phone_number: str, messages: str = None, type: str = None, audio_url: str = None) -> Dict[str, Any]:
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
            
            statuses.append(response.status_code)
        else:
            for i, message in enumerate(messages):
                sleep(2 if i % 3 != 0 else 5)
                
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
                        "text": f"Alessandro Assistente Global:\n{message}"
                    },
                    "fields": "conversation,contact",
                    "assigned_user": "alessandro-ia@alessandro-ia.com"
                }
                
                response = requests.post(url, json=payload, headers=headers)
                
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