from pydantic import BaseModel, Field
<<<<<<< HEAD
from langchain_core.tools import tool
import json
from typing import Any, Dict, List

from app.services.knowledge_service import knowledge_service_instance
from app.services.redis_service import get_redis
from app.core.logger import get_logger

redis_client = get_redis()
logger = get_logger(__name__)


@tool("knowledge_service_tool")
=======
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

@tool("KnowledgeServiceTool")
>>>>>>> 1452778c3d5f4d9345c24b847961ab71baba43e1
def knowledge_service_tool(queries: List[Dict[str, Any]]) -> str:
    """
    Use esta ferramenta para obter informações da base de conhecimento da Global System.
    Para máxima eficiência, agrupe múltiplas perguntas em uma única chamada.
<<<<<<< HEAD
    O input deve ser uma lista de dicionários de query.

    **CARDÁPIO DE TÓPICOS VÁLIDOS PARA A `knowledge_service_tool`:**
        # INFORMAÇÕES GERAIS E ESTRATÉGICAS
        - **'get_company_info'**: Retorna informações básicas da empresa (CNPJ, endereço).
        - **'get_sales_philosophy'**: Retorna as diretrizes gerais de venda (fluxo, tom, princípios).
        - **'get_support_philosophy'**: Retorna as diretrizes gerais de suporte.

        # PRODUTOS E PREÇOS
        - **'list_all_products'**: Retorna uma lista com nome e descrição de todos os planos.
        - **'pricing'**: Para valores de um plano. `params:  "plan_name": "..." ` # pode ser um desses: "Rastreador GSM (2G+3G+4G) + WI-FI" | "Rastreador GSM 4G" | "Plano Proteção Total PGS" | "Plano Rastreamento Moto"
        - **'faq'**: Para perguntas frequentes de um plano. `params:  "plan_name": "..." ` # pode ser um desses: "Rastreador GSM (2G+3G+4G) + WI-FI" | "Rastreador GSM 4G" | "Plano Proteção Total PGS" | "Plano Rastreamento Moto"
        - **'product_compatibility'**: Para verificar compatibilidade. `params:  "detail": "..." `

        # POLÍTICAS E PROCEDIMENTOS
        - **'contract_terms'**: Para cláusulas contratuais. `params:  "contract_id": "..." ` # Pode ser um desses: "standard" | "moto_pgs"
        - **'installation_policy'**: Para regras de instalação. `params:  "vehicle_type": "..." `
        - **'maintenance_policy'**: Para regras de manutenção.
        - **'scheduling_rules'**: Para regras de agendamento de serviços.
        - **'technical_limitations'**: Para obter as limitações técnicas dos rastreadores.
        - **'blocker_installation_rules'**: Para regras sobre a instalação do bloqueio.
        - **'regional_availability'**: Para saber onde um serviço/plano está disponível. `params:  "location_info": ... `

        # OUTRAS INFORMAÇÕES
        - **'application_features'**: Para detalhes e funcionalidades do aplicativo.

    Exemplo de chamada: [{'topic': 'pricing', 'params': {'plan_name': 'Plano Rastreamento Moto'}}]

    Args:
        queries (List[Dict[str, Any]]): Uma lista de dicionários contendo as queries.
    """
    logger.info(f"--- KNOWLEDGE SERVICE TOOL CALLED with queries: {queries} ---")

    if not isinstance(queries, list):
        return "Erro de formato: O input deve ser uma lista de dicionários de query."
=======
    O input deve ser uma lista de dicionários de query. Ex: [{'topic': 'pricing', 'params': {'plan_name': 'Plano X'}}]
    """

    if not isinstance(queries, list):
             return "Erro de formato: O input deve ser uma lista de dicionários de query."
>>>>>>> 1452778c3d5f4d9345c24b847961ab71baba43e1

    # Itera sobre a lista de queries e coleta os resultados
    results = [knowledge_service_instance.find_information(query) for query in queries]

    # Retorna a lista de resultados como uma string formatada para o agente
    if len(results) == 1:
        # Se houver apenas um resultado, retorna-o diretamente para simplicidade
        final_result = results[0]
    else:
        final_result = results
        
<<<<<<< HEAD
    return json.dumps(final_result, indent=2, ensure_ascii=False)


class DrillDownTopicToolInput(BaseModel):
    """Input schema for drill_down_topic_tool."""
    contact_id: str = Field(..., description="The unique ID of the contact, essential for locating the correct history.")
    topic_id: str = Field(..., description="The specific ID of the topic you need to drill down into for more details.")

@tool("drill_down_topic_tool", args_schema=DrillDownTopicToolInput, description="Use this tool to get the full, detailed context for a specific topic of conversation that has already been summarized. This provides deeper insights than the high-level summary.")
def drill_down_topic_tool(contact_id: str, topic_id: str) -> str:
    """
    Fetches detailed information for a specific conversation topic from Redis.
    """
    logger.info(f"[{contact_id}] - Executing drill_down_topic_tool for topic: {topic_id}")
    try:
        details_key = f"history:topic_details:{contact_id}:{topic_id}"
        topic_details_json = redis_client.get(details_key)

        if not topic_details_json:
            logger.warning(f"[{contact_id}] - No details found for topic {topic_id}.")
            return json.dumps({"error": "Topic details not found."})

        # The data in Redis is stored as a JSON string. redis-py returns bytes.
        if isinstance(topic_details_json, bytes):
            return topic_details_json.decode('utf-8')
        return topic_details_json

    except Exception as e:
        logger.error(f"[{contact_id}] - Error in drill_down_topic_tool for topic {topic_id}: {e}", exc_info=True)
        return json.dumps({"error": "An unexpected error occurred while fetching topic details."})
=======
    return json.dumps(final_result, indent=2, ensure_ascii=False)
>>>>>>> 1452778c3d5f4d9345c24b847961ab71baba43e1
