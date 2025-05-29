from crewai.tools import BaseTool
from typing import Type, Any, Dict, List
from pydantic import BaseModel, Field
from app.config.settings import settings
import requests

from time import sleep

class CallbellSendInput(BaseModel):
    """Modelo para enviar informações via Callbell."""
    phone_number: str = Field(..., description="Número de telefone do destinatário")
    messages: str = Field(..., description="Mensagens a ser enviadas")

class CallbellSendTool(BaseTool):
    name: str = "CallbellSendTool"
    description: str = "Envia uma mensagem via Callbell para um número de telefone específico"
    args_schema: Type[BaseModel] = CallbellSendInput
    
    def _run(self, phone_number: str, messages: str) -> Dict[str, Any]:
        """Envia uma mensagem via Callbell."""
        
        for message in messages:
            message = f'*Alessandro - Assistente Global System*:\n{message}'
            
            sleep(0.5)
            
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
                "filds": "conversation,contact"
            }
            
            response = requests.post(url, json=payload, headers=headers)
            
            if response.status_code == 200:
                return {"status": "success", "data": response.json()}
            else:
                return {"status": "error", "message": response.text}