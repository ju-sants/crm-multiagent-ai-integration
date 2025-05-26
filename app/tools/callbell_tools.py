from crewai.tools import BaseTool
from typing import Type, Any, Dict
from pydantic import BaseModel, Field
from app.config.settings import settings
import requests


class CallbellSendInfo(BaseModel):
    """Modelo para enviar informações via Callbell."""
    phone_number: str = Field(..., description="Número de telefone do destinatário")
    message: str = Field(..., description="Mensagem a ser enviada")

class CallbellSendTool(BaseTool):
    name: str = "CallbellSendTool"
    description: str = "Envia uma mensagem via Callbell para um número de telefone específico."
    args_schema: Type[BaseModel] = CallbellSendInfo
    
    def _run(self, phone_number: str, message: str) -> Dict[str, Any]:
        """Envia uma mensagem via Callbell."""
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
        }
        
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            return {"status": "success", "data": response.json()}
        else:
            return {"status": "error", "message": response.text}