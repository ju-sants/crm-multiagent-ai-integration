from typing import Any, Dict
from time import sleep
import requests

from app.config.settings import settings


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
                message = f'*Alessandro - Assistente Global System*:\n{message}'
                
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
                    "fields": "conversation,contact"
                }
                
                response = requests.post(url, json=payload, headers=headers)
                
                statuses.append(response.status_code)
            
        if all(status == 200 for status in statuses):
            return {"status": "success"}
        else:
            return {"status": "error"}