from pydantic import BaseModel, Field
from typing import Literal, Type
from crewai.tools import BaseTool
from langchain_core.tools import tool
import json
from typing import Type, Any, Dict, List, Union

from app.services.knowledge_service import knowledge_service_instance
from app.services.redis_service import get_redis
from app.core.logger import get_logger

redis_client = get_redis()
logger = get_logger(__name__)


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


class DrillDownTopicToolInput(BaseModel):
    """Input schema for DrillDownTopicTool."""
    contact_id: str = Field(..., description="The unique ID of the contact, essential for locating the correct history.")
    topic_id: str = Field(..., description="The specific ID of the topic you need to drill down into for more details.")

@tool("DrillDownTopicTool", args_schema=DrillDownTopicToolInput, description="Use this tool to get the full, detailed context for a specific topic of conversation that has already been summarized. This provides deeper insights than the high-level summary.")
def drill_down_topic_tool(contact_id: str, topic_id: str) -> str:
    """
    Fetches detailed information for a specific conversation topic from Redis.
    """
    logger.info(f"[{contact_id}] - Executing DrillDownTopicTool for topic: {topic_id}")
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
        logger.error(f"[{contact_id}] - Error in DrillDownTopicTool for topic {topic_id}: {e}", exc_info=True)
        return json.dumps({"error": "An unexpected error occurred while fetching topic details."})