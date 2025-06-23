from pydantic import BaseModel, Field
from typing import Literal, Type
from crewai.tools import BaseTool
from langchain_core.tools import tool
import json
from typing import Type, Any, Dict, List, Union

from app.services.knowledge_service import knowledge_service_instance


class KnowledgeServiceToolInput(BaseModel):
    """
    Input schema para a KnowledgeServiceTool.
    Agora espera uma lista de dicionários de query.
    """
    queries: List[Dict[str, Any]] = Field(..., description="Uma lista de queries, onde cada query é um dicionário contendo 'topic' e 'params'.")

class KnowledgeServiceTool(BaseTool):
    name: str = "KnowledgeServiceTool"
    description: str = (
        "Use esta ferramenta para obter informações da base de conhecimento da Global System. "
        "Para máxima eficiência, agrupe múltiplas perguntas em uma única chamada. "
        "O input deve ser uma lista de dicionários de query. Ex: [{'topic': 'pricing', 'params': {'plan_name': 'Plano X'}}]"
    )
    args_schema: Type[BaseModel] = KnowledgeServiceToolInput
    
    def _run(self, queries: List[Dict[str, Any]]) -> str:
        """
        Executa uma ou múltiplas consultas na base de conhecimento.
        Este método agora recebe uma lista de dicionários diretamente,
        tornando a chamada muito mais robusta.

        Args:
            queries (List[Dict[str, Any]]): A lista de queries vinda do agente.

        Returns:
            str: O resultado da(s) consulta(s), formatado como uma string JSON.
        """
        # A validação de formato agora é feita pelo Pydantic/CrewAI,
        # eliminando a necessidade de json.loads() e o risco de erro.
        
        if not isinstance(queries, list):
             return "Erro de formato: O input deve ser uma lista de dicionários de query."

        # Itera sobre a lista de queries e coleta os resultados
        results = [knowledge_service_instance.find_information(query) for query in queries]

        # Retorna a lista de resultados como uma string formatada para o agente
        if len(results) == 1:
            # Se houver apenas um resultado, retorna-o diretamente para simplicidade
            final_result = results[0]
        else:
            final_result = results
            
        return json.dumps(final_result, indent=2, ensure_ascii=False)

@tool("KnowledgeServiceTool", description="Use esta ferramenta para obter informações da base de conhecimento da Global System. Para máxima eficiência, agrupe múltiplas perguntas em uma única chamada. O input deve ser uma lista de dicionários de query. Ex: [{'topic': 'pricing', 'params': {'plan_name': 'Plano X'}}]")
def knowledge_service_tool(queries: List[Dict[str, Any]]) -> str:
    if not isinstance(queries, list):
             return "Erro de formato: O input deve ser uma lista de dicionários de query."

    # Itera sobre a lista de queries e coleta os resultados
    results = [knowledge_service_instance.find_information(query) for query in queries]

    # Retorna a lista de resultados como uma string formatada para o agente
    if len(results) == 1:
        # Se houver apenas um resultado, retorna-o diretamente para simplicidade
        final_result = results[0]
    else:
        final_result = results
        
    return json.dumps(final_result, indent=2, ensure_ascii=False)