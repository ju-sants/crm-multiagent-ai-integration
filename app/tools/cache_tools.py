from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type


L1_cache = {}

class L1CacheQueryInput(BaseModel):
    client_id: str = Field(..., description="O ID do cliente para o qual a consulta deve ser realizada. Apenas o ID, não passe em json ou outro formato. Exemplo: '12345'.")
class L1CacheQueryTool(BaseTool):
    name: str = "L1CacheQueryTool"
    description: str = "Com essa ferramenta, você tem acesso rápido a perguntas e respostas, pares de mensagem e resposta, e pares de contexto e resposta. Você pode consultar o cache L1 para obter respostas rápidas para perguntas/mensagens/solicitações idênticas."
    args_schema: Type[BaseModel] = L1CacheQueryInput
    
    def _run(self, client_id: str):
        """
        Executa a consulta no cache L1 para o client_id fornecido.
        
        Args:
            client_id (str): O ID do cliente para o qual a consulta deve ser realizada.
        
        Returns:
            dict: Um dicionário contendo as respostas do cache L1.
        """
        if client_id in L1_cache:
            return L1_cache[client_id]
        else:
            return {"message": "No data found for the provided client_id."}