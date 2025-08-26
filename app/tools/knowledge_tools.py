from pydantic import BaseModel, Field
from langchain_core.tools import tool
import json
from typing import Any, Dict, List

from app.services.knowledge_service import knowledge_service_instance
from app.services.redis_service import get_redis
from app.core.logger import get_logger

redis_client = get_redis()
logger = get_logger(__name__)


class KnowledgeServiceToolInput(BaseModel):
    """Input para a ferramenta knowledge_service_tool."""
    queries: List[Dict[str, Any]] = Field(..., description="Uma lista de dicionários de consulta a serem executados em um único lote. Cada dicionário requer uma chave 'topic' e um dicionário 'params' opcional.")


@tool("knowledge_service_tool", args_schema=KnowledgeServiceToolInput)
def knowledge_service_tool(queries: List[Dict[str, Any]]) -> str:
    """
    Use esta ferramenta para obter informações da base de conhecimento da Global System.
    Para máxima eficiência, agrupe múltiplas perguntas em uma única chamada.

    **CARDÁPIO DE TÓPICOS VÁLIDOS PARA A `knowledge_service_tool`:**
        # INFORMAÇÕES GERAIS E ESTRATÉGICAS
        - **'get_company_info'**: Retorna informações básicas da empresa (CNPJ, endereço).
        - **'get_sales_philosophy'**: Retorna as diretrizes gerais de venda (fluxo, tom, princípios).
        - **'get_support_philosophy'**: Retorna as diretrizes gerais de suporte.
        - **'customer_profile_scripts'**: Retorna scripts de abordagem para diferentes perfis de cliente.

        # PRODUTOS E PREÇOS
        - **'list_all_products'**: Retorna uma lista com nome e descrição de todos os planos.
        - **'pricing'**: Para valores de um plano. `params: { "plan_name": "..." }`
        - **'faq'**: Para perguntas frequentes de um plano. `params: { "plan_name": "...", "question_keyword": "..." }`
        - **'key_selling_points'**: Retorna os pontos chave de venda para um plano. `params: { "plan_name": "..." }`
        - **'objection_handling'**: Retorna respostas para objeções comuns de um plano. `params: { "plan_name": "..." }`
        - **'product_compatibility'**: Para verificar compatibilidade. `params: { "detail": "..." }`

        # POLÍTICAS E PROCEDIMENTOS
        - **'contract_terms'**: Para cláusulas contratuais. `params: { "contract_id": "..." }` # IDs: "standard_contract", "moto_pgs_contract"
        - **'installation_policy'**: Para regras de instalação. `params: { "vehicle_type": "..." }`
        - **'maintenance_policy'**: Para regras de manutenção.
        - **'scheduling_rules'**: Para regras de agendamento de serviços.
        - **'technical_limitations'**: Para obter as limitações técnicas dos rastreadores.
        - **'blocker_installation_rules'**: Para regras sobre a instalação do bloqueio.
        - **'regional_availability'**: Para saber onde um serviço/plano está disponível. `params: { "location_info": ... }`

        # OUTRAS INFORMAÇÕES
        - **'application_features'**: Para detalhes e funcionalidades do aplicativo.
        - **'get_web_access_features'**: Para detalhes e funcionalidades do acesso via web.

        # INFORMAÇÕES IMPORTANTES
         - **Compatibilidade de planos**:
            * O plano "Rastreador GSM (2G+3G+4G) + WI-FI" é indicado para fazendas e locais remotos.
            * Os planos "Plano Rastreamento + Proteção Total PGS" e "Plano Rastreamento Moto Básico" são apenas para motos.
            * O plano "Rastreador Híbrido SATELITAL" é indicado para locais remotos e fazendas, e para frotas. Mas pode ser utilizado em qualquer tipo de veículo em qualquer local.
    """
    logger.info(f"--- KNOWLEDGE SERVICE TOOL CALLED with queries: {queries} ---")

    if not isinstance(queries, list):
        return "Erro de formato: O input deve ser uma lista de dicionários de query."

    results = []
    for query in queries:
        # Criar uma chave de cache única e determinística para a query
        # Ordenar o dicionário garante que a mesma query gere sempre a mesma chave
        cache_key = f"knowledge_cache:{json.dumps(query, sort_keys=True)}"
        
        try:
            # Tentar obter o resultado do cache primeiro
            cached_result = redis_client.get(cache_key)
            if cached_result:
                logger.info(f"Cache HIT para a query: {query}")
                results.append(json.loads(cached_result))
                continue  # Pula para a próxima query
        except Exception as e:
            logger.error(f"Erro ao acessar o cache Redis: {e}")

        # Se não estiver no cache (Cache MISS), executa a busca
        logger.info(f"Cache MISS para a query: {query}. Buscando na KnowledgeService.")
        result = knowledge_service_instance.find_information(query)
        results.append(result)
        
        # Salva o novo resultado no cache com um tempo de expiração (e.g., 1 hora)
        try:
            redis_client.set(cache_key, json.dumps(result, ensure_ascii=False), ex=3600)
        except Exception as e:
            logger.error(f"Erro ao salvar no cache Redis: {e}")

    # Retorna a lista de resultados como uma string formatada para o agente
    if len(results) == 1:
        final_result = results[0]
    else:
        final_result = results
        
    return json.dumps(final_result, indent=2, ensure_ascii=False)


class DrillDownTopicToolInput(BaseModel):
    """Input schema for drill_down_topic_tool."""
    contact_id: str = Field(..., description="The unique ID of the contact, essential for locating the correct history.")
    topic_id: str = Field(..., description="The specific ID of the topic you need to drill down into for more details.")

@tool("drill_down_topic_tool", args_schema=DrillDownTopicToolInput)
def drill_down_topic_tool(contact_id: str, topic_id: str) -> str:
    """Use this tool to get the full, detailed context for a specific topic of conversation that has already been summarized. This provides deeper insights than the high-level summary."""
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
