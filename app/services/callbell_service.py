from typing import Any, Dict
from time import sleep
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
                        "text": message
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

def get_contact_messages(contact_uuid: str, limit: int = 50) -> list:
    """Busca as mensagens de um contato na API da Callbell."""
    url = f"https://api.callbell.eu/v1/contacts/{contact_uuid}/messages"
    headers = {
        "Authorization": f"Bearer {settings.CALLBELL_API_KEY}",
        "Content-Type": "application/json"
    }
    page = 1
    messages = []

    try:
        while True:
            params = {"page": page}
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            messages_temp = data.get("messages", [])
            if messages_temp:
                messages.extend(messages_temp)
                page += 1
                if len(messages) >= limit:
                    break
            else:
                break
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch messages for contact {contact_uuid}: {e}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON for contact {contact_uuid}: {e}")
        return []
    
    else:
        return messages
    
    