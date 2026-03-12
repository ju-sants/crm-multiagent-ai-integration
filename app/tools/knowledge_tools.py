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
    queries: List[Dict[str, Any]] = Field(
        ...,
        description=(
            "Lista de consultas. Cada item é um dicionário com 'topic' (obrigatório) "
            "e 'params' (dict opcional). Todas as queries são executadas em lote."
        ),
    )


@tool("knowledge_service_tool", args_schema=KnowledgeServiceToolInput)
def knowledge_service_tool(queries: List[Dict[str, Any]]) -> str:
    """Consulta a base de conhecimento da Global System. Agrupe múltiplas perguntas em uma única chamada.

    TÓPICOS DISPONÍVEIS (use o valor exato como 'topic'):

    ┌─────────────────────────────────────────────────────────────────┐
    │  PRODUTOS                                                       │
    ├─────────────────────────────────────────────────────────────────┤
    │ 'list_plans'           → Lista RESUMIDA de todos os planos      │
    │                          (nome, tipo, preço, sales_pitch).      │
    │                          USE ESTE PRIMEIRO para descobrir os     │
    │                          planos e depois buscar detalhes.        │
    │   params: (nenhum)                                              │
    │   RETORNO: { plans: [...], sales_guidance: {...} }               │
    │                                                                 │
    │ 'get_plan_details'     → Retorna TODOS os dados de um plano     │
    │                          específico (pricing, FAQ, contrato,     │
    │                          objeções, key_selling_points).          │
    │   params: { "plan_name": "nome exato do plano" }                │
    │   RETORNO: Objeto completo do plano com todas as seções         │
    │                                                                 │
    │ 'pricing'              → Preços de um plano específico.         │
    │   params: { "plan_name": "nome exato do plano" }                │
    │   RETORNO: { adesao, mensalidade, detalhes de preço }           │
    │                                                                 │
    │ 'faq'                  → Perguntas frequentes de um plano.      │
    │   params: { "plan_name": "nome exato do plano" }                │
    │   RETORNO: Lista de perguntas e respostas do plano              │
    │                                                                 │
    │ 'key_selling_points'   → Argumentos de venda de um plano.       │
    │   params: { "plan_name": "nome exato do plano" }                │
    │   RETORNO: Lista de argumentos e diferenciais                   │
    │                                                                 │
    │ 'objection_handling'   → Respostas a objeções de um plano.      │
    │   params: { "plan_name": "nome exato do plano" }                │
    │   RETORNO: Mapa de objeções comuns e respostas sugeridas        │
    │                                                                 │
    │ 'list_all_products'    → TODOS os dados de TODOS os planos      │
    │                          (resposta grande — prefira list_plans). │
    │   params: (nenhum)                                              │
    │   RETORNO: Array com categorias e todos os planos completos     │
    ├─────────────────────────────────────────────────────────────────┤
    │  ESTRATÉGIA E EMPRESA                                           │
    ├─────────────────────────────────────────────────────────────────┤
    │ 'sales_guidance'       → Filosofia de upsell e hierarquia       │
    │                          de produtos.                           │
    │   params: (nenhum)                                              │
    │   RETORNO: Diretrizes de hierarquia, upsell, margens            │
    │                                                                 │
    │ 'sales_philosophy'     → Diretrizes de venda (tom, princípios,  │
    │                          fluxo, scripts de roubo).              │
    │   params: (nenhum)                                              │
    │   RETORNO: Scripts, tom, pilares da comunicação comercial       │
    │                                                                 │
    │ 'support_philosophy'   → Diretrizes de suporte técnico.         │
    │   params: (nenhum)                                              │
    │   RETORNO: Procedimentos, tom e fluxo de suporte                │
    │                                                                 │
    │ 'company_info'         → Dados da empresa (CNPJ, endereço).     │
    │   params: (nenhum)                                              │
    │   RETORNO: CNPJ, razão social, endereço, contatos               │
    │                                                                 │
    │ 'customer_profile_scripts' → Scripts de abordagem por perfil.   │
    │   params: (nenhum)                                              │
    │   RETORNO: Scripts segmentados por tipo de cliente               │
    │                                                                 │
    │ 'theft_communication_scripts' → Scripts de comunicação em caso  │
    │                          de roubo (por tipo de plano).          │
    │   params: (nenhum)                                              │
    │   RETORNO: Scripts de emergência por plano e situação            │
    ├─────────────────────────────────────────────────────────────────┤
    │  CONTRATOS E POLÍTICAS                                          │
    ├─────────────────────────────────────────────────────────────────┤
    │ 'contract_terms'       → Cláusulas contratuais.                 │
    │   params: { "contract_id": "standard_contract" }                │
    │   IDs válidos: "standard_contract", "moto_pgs_contract"         │
    │   Sem params → retorna termos gerais.                           │
    │   RETORNO: Cláusulas, multas, prazos, condições                 │
    │                                                                 │
    │ 'installation_policy'  → Regras de instalação.                  │
    │   params: { "detail": "general_policy" } (opcional)             │
    │   RETORNO: Procedimentos, prazos e requisitos de instalação     │
    │                                                                 │
    │ 'maintenance_policy'   → Regras de manutenção.                  │
    │   params: (nenhum)                                              │
    │   RETORNO: Regras de manutenção preventiva e corretiva          │
    │                                                                 │
    │ 'scheduling_rules'     → Regras de agendamento.                 │
    │   params: (nenhum)                                              │
    │   RETORNO: Horários, lead times e regras de agenda              │
    │                                                                 │
    │ 'blocker_installation_rules' → Regras de instalação de bloqueio.│
    │   params: (nenhum)                                              │
    │   RETORNO: Requisitos e procedimentos de bloqueador             │
    │                                                                 │
    │ 'regional_availability'→ Disponibilidade regional e técnicos.   │
    │   params: { "detail": "outsourced_cities_list" } (opcional)     │
    │   RETORNO: Cidades atendidas, técnicos terceirizados            │
    │                                                                 │
    │ 'technical_limitations'→ Limitações técnicas dos rastreadores.   │
    │   params: { "detail": "satelital" } (opcional)                  │
    │   Valores de detail: "general", "gsm_gprs", "satelital"         │
    │   RETORNO: Limitações por tecnologia de rastreamento            │
    │                                                                 │
    │ 'product_compatibility'→ Compatibilidade de equipamentos.       │
    │   params: { "detail": "john_deere_autopilot" } (opcional)       │
    │   RETORNO: Matriz de compatibilidade por veículo/equipamento    │
    ├─────────────────────────────────────────────────────────────────┤
    │  FUNCIONALIDADES                                                │
    ├─────────────────────────────────────────────────────────────────┤
    │ 'application_features' → Funcionalidades do app mobile.         │
    │   params: { "feature_name": "notifications" } (opcional)        │
    │   Sem params → retorna overview geral de todas as features.     │
    │   RETORNO: Lista de funcionalidades com descrições              │
    │                                                                 │
    │ 'web_access_features'  → Funcionalidades do acesso web.         │
    │   params: (nenhum)                                              │
    │   RETORNO: Funcionalidades disponíveis na plataforma web        │
    └─────────────────────────────────────────────────────────────────┘

    NOMES EXATOS DOS PLANOS (use estes em 'plan_name'):
      - "Rastreador Híbrido SATELITAL"
      - "Rastreador GSM (2G+3G+4G) + WI-FI"
      - "Rastreador GSM 4G"
      - "Plano Rastreamento + Proteção Total PGS"  (APENAS motos)
      - "Plano Rastreamento Moto Básico"  (APENAS motos)
      - "Plano para Scooters, Patinetes e Bikes Elétricas"

    REGRAS DE COMPATIBILIDADE:
      - PGS e Moto Básico → APENAS motos (NÃO disponível para carros/caminhões)
      - PGS → NÃO disponível em DDD 66 (Mato Grosso)
      - GSM+WI-FI → ideal para fazendas sem sinal de celular
      - Híbrido SATELITAL → funciona em qualquer veículo e local
      - Híbrido SATELITAL → NÃO compatível com piloto automático John Deere

    FORMATO DE RETORNO:
      Cada resultado contém:
      - 'data': Os dados solicitados (conteúdo principal)
      - 'related_queries': Sugestões de consultas complementares (topic + params)
      Em caso de erro:
      - 'error': Mensagem descritiva do problema e como corrigi-lo

    ERROS COMUNS (evite estes):
      ✗ Esquecer 'plan_name' em tópicos de produto → SEMPRE inclua params.plan_name
      ✗ Usar nomes aproximados → Use os NOMES EXATOS listados acima
      ✗ Chamar 'list_all_products' para um plano → Use 'get_plan_details' com plan_name
      ✗ Inventar tópicos → Use APENAS os tópicos listados nesta documentação
      ✗ Enviar queries vazias → Cada item deve ter pelo menos a chave 'topic'

    ESTRATÉGIA DE CONSULTA EFICIENTE:
      1. Comece com 'list_plans' para uma visão geral leve
      2. Use 'get_plan_details' para mergulhar em um plano específico
      3. Agrupe múltiplas queries em UMA chamada para economizar tempo
      4. Siga as 'related_queries' do retorno para aprofundar

    EXEMPLOS DE USO:
      # Descobrir planos (leve):
      {"queries": [{"topic": "list_plans"}]}

      # Buscar preço + FAQ de um plano:
      {"queries": [
        {"topic": "pricing", "params": {"plan_name": "Rastreador GSM 4G"}},
        {"topic": "faq", "params": {"plan_name": "Rastreador GSM 4G"}}
      ]}

      # Tudo sobre um plano:
      {"queries": [{"topic": "get_plan_details", "params": {"plan_name": "Rastreador Híbrido SATELITAL"}}]}

      # Política + contrato:
      {"queries": [
        {"topic": "contract_terms", "params": {"contract_id": "standard_contract"}},
        {"topic": "installation_policy"}
      ]}
    """
    logger.info(f"--- KNOWLEDGE SERVICE TOOL CALLED with queries: {queries} ---")

    if not isinstance(queries, list):
        return json.dumps({
            "status": "error",
            "error": "O input deve ser uma lista de dicionários de query. Exemplo: [{\"topic\": \"list_plans\"}]",
            "fix": "Envie queries como lista: [{\"topic\": \"<topico>\", \"params\": {}}]"
        }, ensure_ascii=False)

    if not queries:
        return json.dumps({
            "status": "error",
            "error": "Lista de queries vazia. Forneça pelo menos uma query.",
            "fix": "Adicione pelo menos um item: [{\"topic\": \"list_plans\"}]"
        }, ensure_ascii=False)

    results = []
    for query in queries:
        if not isinstance(query, dict) or 'topic' not in query:
            results.append({
                "status": "error",
                "query_received": str(query),
                "error": "Cada query deve ser um dicionário com a chave 'topic'.",
                "fix": "Formato correto: {\"topic\": \"<topico>\", \"params\": {}}"
            })
            continue

        cache_key = f"knowledge_cache:{json.dumps(query, sort_keys=True)}"
        
        try:
            cached_result = redis_client.get(cache_key)
            if cached_result:
                logger.info(f"Cache HIT para a query: {query}")
                results.append(json.loads(cached_result))
                continue
        except Exception as e:
            logger.error(f"Erro ao acessar o cache Redis: {e}")

        logger.info(f"Cache MISS para a query: {query}. Buscando na KnowledgeService.")
        result = knowledge_service_instance.find_information(query)
        results.append(result)
        
        try:
            redis_client.set(cache_key, json.dumps(result, ensure_ascii=False), ex=3600)
        except Exception as e:
            logger.error(f"Erro ao salvar no cache Redis: {e}")

    if len(results) == 1:
        final_result = results[0]
    else:
        final_result = results
        
    return json.dumps(final_result, indent=2, ensure_ascii=False)


class DrillDownTopicToolInput(BaseModel):
    """Input para a ferramenta drill_down_topic_tool."""
    contact_id: str = Field(..., description="ID único do contato (fornecido nos dados de input da tarefa).")
    topic_id: str = Field(..., description="Slug do tópico no histórico (ex: 'rastreamento_moto', 'suporte_gps_offline'). Visível no longterm_history como [topic_id].")

@tool("drill_down_topic_tool", args_schema=DrillDownTopicToolInput)
def drill_down_topic_tool(contact_id: str, topic_id: str) -> str:
    """Busca os detalhes completos de um tópico do histórico de conversa.

    O longterm_history mostra apenas título e resumo de cada tópico.
    Use esta ferramenta para obter o 'full_details' — uma versão narrativa
    e detalhada do que foi discutido naquele tópico.

    QUANDO USAR:
      - Precisa entender o contexto completo de algo que o cliente já discutiu.
      - O resumo no longterm_history não tem detalhes suficientes.
      - Quer verificar o que exatamente foi dito sobre um assunto.
      - O cliente referencia algo anterior e você precisa do contexto completo.

    QUANDO NÃO USAR:
      - NÃO use para buscar informações de produto → use knowledge_service_tool
      - NÃO use se o resumo no longterm_history já é suficiente para responder

    COMO USAR:
      - O 'topic_id' aparece no longterm_history entre colchetes: [topic_id]
        Exemplo: "[rastreamento_moto] Discussão sobre planos de moto"
        → topic_id = "rastreamento_moto"
      - O 'contact_id' é fornecido nos dados de input da task.

    RETORNO (sucesso):
      {
        "title": "Título do tópico",
        "summary": "Resumo conciso",
        "full_details": "Narrativa completa do que foi discutido",
        "quality_score": 0.85  // 0.0 a 1.0 — confiabilidade do resumo
      }

    RETORNO (erro):
      {
        "error": "Topic details not found.",
        "available_topics": ["topic_1", "topic_2", ...]
      }
    """
    logger.info(f"[{contact_id}] - Executing drill_down_topic_tool for topic: {topic_id}")

    if not contact_id or not contact_id.strip():
        return json.dumps({"error": "contact_id é obrigatório e não pode ser vazio. Use o contact_id dos dados de input da task."}, ensure_ascii=False)

    if not topic_id or not topic_id.strip():
        return json.dumps({"error": "topic_id é obrigatório. Consulte o longterm_history para encontrar os topic_ids disponíveis (aparecem entre colchetes: [topic_id])."}, ensure_ascii=False)

    topic_id = topic_id.strip()

    try:
        details_key = f"history:topic_details:{contact_id}:{topic_id}"
        topic_details_json = redis_client.get(details_key)

        if not topic_details_json:
            logger.warning(f"[{contact_id}] - No details found for topic {topic_id}.")
            # List available topics for this contact to help the agent self-correct
            available_topics = []
            try:
                pattern = f"history:topic_details:{contact_id}:*"
                for key in redis_client.scan_iter(match=pattern, count=100):
                    key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                    t_id = key_str.split(':')[-1]
                    available_topics.append(t_id)
            except Exception:
                pass

            error_response = {
                "error": f"Tópico '{topic_id}' não encontrado para este contato.",
                "fix": "Verifique o topic_id no longterm_history. Os topic_ids aparecem entre colchetes: [topic_id].",
            }
            if available_topics:
                error_response["available_topics"] = available_topics
                error_response["hint"] = f"Tópicos disponíveis para este contato: {', '.join(available_topics)}. Use um destes como topic_id."
            else:
                error_response["hint"] = "Nenhum tópico detalhado encontrado para este contato. O histórico pode ainda não ter sido processado pelo pipeline de enriquecimento."

            return json.dumps(error_response, ensure_ascii=False)

        if isinstance(topic_details_json, bytes):
            return topic_details_json.decode('utf-8')
        return topic_details_json

    except Exception as e:
        logger.error(f"[{contact_id}] - Error in drill_down_topic_tool for topic {topic_id}: {e}", exc_info=True)
        return json.dumps({"error": "Erro inesperado ao buscar detalhes do tópico. Tente novamente ou use o longterm_history como fonte alternativa."}, ensure_ascii=False)
