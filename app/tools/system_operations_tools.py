from langchain_core.tools import tool
from typing import List, Dict, Any
from pydantic import BaseModel, Field


from app.services.system_operations_service import system_operations_service
from app.core.logger import get_logger

logger = get_logger(__name__)


# Catálogo centralizado de ações válidas e seus parâmetros obrigatórios
VALID_ACTIONS = {
    # Workflows de Negócio (Ações Orquestradas)
    'GET_VEHICLE_DETAILS': ['plate', 'client_name'],
    'GET_VEHICLE_POSITIONS': ['plate', 'client_name', 'initial_date', 'final_date'],
    'GET_VEHICLE_TRIPS_REPORT': ['plate', 'client_name', 'start_date', 'end_date'],
    'GET_VEHICLE_EVENTS_REPORT': ['plate', 'client_name', 'start_date', 'end_date'],
    'GET_VEHICLE_GEOFENCES': ['plate', 'client_name'],
    'GET_CLIENT_VEHICLES': ['search_term'],
    'GET_PAYMENT_HISTORY': ['search_term'],
    'FIND_CLIENT_AND_GET_FINANCIALS': ['search_term'],
    'GET_VEHICLE_FULL_REPORT': ['plate', 'client_name'],
    'SEND_TRACKER_RESET': ['plate'],
    'CALCULATE_DISPLACEMENT_COST': ['destination_city', 'destination_state'],
    # Ações de Busca (Uso Restrito)
    'SEARCH_CLIENTS': ['search_term'],
    'SEARCH_VEHICLES': ['search_term'],
}


class SystemOperationsToolInput(BaseModel):
    """Input for system_operations_tool."""
    queries: List[Dict[str, Any]] = Field(..., description="A list of query dictionaries to be executed in a single batch. Each dictionary requires an 'action_type' key and an optional 'params' dictionary.")


@tool("system_operations_tool", args_schema=SystemOperationsToolInput)
def system_operations_tool(queries: List[Dict[str, Any]]) -> dict:
    """
    Executa operações de sistema. Para eficiência, utilize consultas em lote.
    O input é uma lista de dicionários, cada um com `action_type` e `params`.

    ┌─────────────────────────────────────────────────────────────────────────────┐
    │  WORKFLOWS DE NEGÓCIO (Ações Orquestradas — preferir estes)               │
    ├─────────────────────────────────────────────────────────────────────────────┤
    │                                                                           │
    │ 'GET_VEHICLE_DETAILS'                                                     │
    │   Busca detalhes completos de um veículo (modelo, rastreador, status).    │
    │   params: { plate, client_name }                                         │
    │   RETORNO: { vehicle_id, model, tracker_info, last_position, status }    │
    │   QUANDO USAR: Cliente pergunta sobre dados cadastrais do veículo.       │
    │                                                                           │
    │ 'GET_VEHICLE_POSITIONS'                                                   │
    │   Histórico de posições GPS de um veículo em um período.                 │
    │   params: { plate, client_name, initial_date, final_date }               │
    │   RETORNO: Lista de posições com lat/lng, velocidade, ignição            │
    │   QUANDO USAR: Cliente quer saber por onde o veículo passou.             │
    │                                                                           │
    │ 'GET_VEHICLE_TRIPS_REPORT'                                               │
    │   Relatório de viagens (trajetos) do veículo em um período.              │
    │   params: { plate, client_name, start_date, end_date }                   │
    │   RETORNO: Viagens com origem, destino, distância, duração               │
    │   QUANDO USAR: Cliente quer ver trajetos e quilometragem.                │
    │                                                                           │
    │ 'GET_VEHICLE_EVENTS_REPORT'                                              │
    │   Relatório de eventos e alertas do veículo (cercas, velocidade, etc.)   │
    │   params: { plate, client_name, start_date, end_date }                   │
    │   RETORNO: Lista de eventos com tipo, data/hora, localização             │
    │   QUANDO USAR: Cliente quer verificar alertas disparados.                │
    │                                                                           │
    │ 'GET_VEHICLE_GEOFENCES'                                                  │
    │   Lista todas as cercas eletrônicas configuradas para o veículo.         │
    │   params: { plate, client_name }                                         │
    │   RETORNO: Lista de cercas com nome, tipo, coordenadas                   │
    │   QUANDO USAR: Cliente pergunta sobre cercas virtuais ativas.            │
    │                                                                           │
    │ 'GET_CLIENT_VEHICLES'                                                    │
    │   Lista TODOS os veículos associados a um cliente.                       │
    │   params: { search_term }                                                │
    │   RETORNO: Lista de veículos com placa, modelo, status                   │
    │   QUANDO USAR: Cliente quer saber quais veículos tem cadastrados.        │
    │                                                                           │
    │ 'GET_PAYMENT_HISTORY'                                                    │
    │   Histórico de pagamentos/boletos de um cliente.                         │
    │   params: { search_term }                                                │
    │   RETORNO: Boletos com valor, vencimento, status (pago/pendente/atrasado)│
    │   QUANDO USAR: Cliente pergunta sobre pendências financeiras.            │
    │                                                                           │
    │ 'FIND_CLIENT_AND_GET_FINANCIALS'                                         │
    │   Busca o cliente E retorna histórico financeiro em uma única operação.  │
    │   params: { search_term }                                                │
    │   RETORNO: { customer_details, financial_history }                       │
    │   QUANDO USAR: Análise financeira completa — prefira sobre GET_PAYMENT.  │
    │                                                                           │
    │ 'GET_VEHICLE_FULL_REPORT'                                                │
    │   Relatório completo: detalhes do veículo + últimas posições.            │
    │   params: { plate, client_name }                                         │
    │   RETORNO: { vehicle_details, recent_position_history }                  │
    │   QUANDO USAR: Diagnóstico completo — ex: veículo sem comunicação.       │
    │                                                                           │
    │ 'SEND_TRACKER_RESET'                                                     │
    │   Envia comando de reset para o rastreador do veículo.                   │
    │   params: { plate }                                                      │
    │   RETORNO: { results: [{ status, message }] }                            │
    │   QUANDO USAR: Suporte técnico — rastreador não comunica.                │
    │   ⚠ AÇÃO IRREVERSÍVEL: use apenas após diagnóstico.                      │
    │                                                                           │
    │ 'CALCULATE_DISPLACEMENT_COST'                                            │
    │   Calcula custo estimado de deslocamento técnico até a cidade do cliente. │
    │   params: { destination_city, destination_state }                        │
    │   RETORNO: { distance_km, estimated_cost, route_info }                   │
    │   QUANDO USAR: Cliente pergunta sobre custo de visita técnica.           │
    │                                                                           │
    ├─────────────────────────────────────────────────────────────────────────────┤
    │  AÇÕES DE BUSCA (Uso Restrito — preferir workflows acima)                │
    ├─────────────────────────────────────────────────────────────────────────────┤
    │                                                                           │
    │ 'SEARCH_CLIENTS'                                                         │
    │   Busca clientes por nome, CPF, etc. Retorna lista paginada.             │
    │   params: { search_term }                                                │
    │   RETORNO: Lista paginada de clientes com id, nome, status               │
    │   ⚠ Prefira FIND_CLIENT_AND_GET_FINANCIALS para análise completa.        │
    │                                                                           │
    │ 'SEARCH_VEHICLES'                                                        │
    │   Busca veículos por placa. Retorna lista de resultados.                 │
    │   params: { search_term }                                                │
    │   RETORNO: Lista de veículos com id, placa, proprietário                 │
    │   ⚠ Prefira GET_VEHICLE_DETAILS para dados completos de um veículo.      │
    │                                                                           │
    └─────────────────────────────────────────────────────────────────────────────┘

    REGRAS DE PARÂMETROS:
      - 'plate': Placa do veículo (ex: "ABC1D23" ou "ABC-1234").
      - 'client_name': Nome do cliente para desambiguação quando múltiplos
        veículos com a mesma placa são encontrados.
      - 'search_term': Termo de busca (nome, CPF, placa, etc.).
      - Datas DEVEM estar no formato YYYY-MM-DD.
        Para relatórios: use intervalos de até 1 dia. NÃO PEÇA DATAS AO CLIENTE.

    FORMATO DE RETORNO:
      Sucesso: { "status": "success", "data": { ... } }
      Erro:    { "status": "error", "error_message": "Descrição do problema" }

    ERROS COMUNS (evite estes):
      ✗ Esquecer 'client_name' em ações de veículo → necessário para desambiguação
      ✗ Usar datas sem formato YYYY-MM-DD → causa erro de parsing
      ✗ Chamar SEARCH_CLIENTS quando precisa de financeiro → use FIND_CLIENT_AND_GET_FINANCIALS
      ✗ Pedir datas ao cliente → use a data atual e calcule internamente
      ✗ Enviar action_type inventado → use APENAS os listados acima

    EXEMPLOS DE USO:
      # Relatório completo de veículo:
      {"queries": [{"action_type": "GET_VEHICLE_FULL_REPORT", "params": {"plate": "ABC1D23", "client_name": "João Silva"}}]}

      # Financeiro do cliente:
      {"queries": [{"action_type": "FIND_CLIENT_AND_GET_FINANCIALS", "params": {"search_term": "JUAN"}}]}

      # Reset de rastreador:
      {"queries": [{"action_type": "SEND_TRACKER_RESET", "params": {"plate": "ABC1D23"}}]}

      # Lote: veículos do cliente + custo de deslocamento:
      {"queries": [
        {"action_type": "GET_CLIENT_VEHICLES", "params": {"search_term": "Maria"}},
        {"action_type": "CALCULATE_DISPLACEMENT_COST", "params": {"destination_city": "Goiânia", "destination_state": "GO"}}
      ]}
    """
    logger.info(f"Received queries: {queries}")

    # Validação estrutural do input
    if not isinstance(queries, list) or not all(isinstance(q, dict) for q in queries):
        return {
            "status": "error",
            "error_message": "O input deve ser uma lista de dicionários de query.",
            "fix": "Formato correto: [{\"action_type\": \"<AÇÃO>\", \"params\": {}}]",
            "valid_actions": list(VALID_ACTIONS.keys())
        }

    if not queries:
        return {
            "status": "error",
            "error_message": "Lista de queries vazia. Forneça pelo menos uma query.",
            "fix": "Adicione pelo menos um item com 'action_type' e 'params'.",
            "valid_actions": list(VALID_ACTIONS.keys())
        }

    # Validação de cada query individualmente
    for query in queries:
        action_type = query.get("action_type")
        params = query.get("params", {})

        if not action_type:
            return {
                "status": "error",
                "error_message": "Todas as queries devem ter um campo 'action_type'.",
                "fix": "Adicione 'action_type' à query. Ações válidas: " + ", ".join(VALID_ACTIONS.keys())
            }

        if action_type not in VALID_ACTIONS:
            return {
                "status": "error",
                "error_message": f"Ação '{action_type}' não existe.",
                "valid_actions": list(VALID_ACTIONS.keys()),
                "fix": f"Substitua '{action_type}' por uma das ações válidas listadas."
            }

        # Validar parâmetros obrigatórios
        required = VALID_ACTIONS[action_type]
        for param in required:
            if param not in params or params[param] is None:
                return {
                    "status": "error",
                    "error_message": f"Parâmetro obrigatório '{param}' ausente ou nulo para a ação '{action_type}'.",
                    "required_params": required,
                    "params_received": list(params.keys()) if params else [],
                    "fix": f"Adicione o parâmetro '{param}' ao dict 'params'. Todos obrigatórios para '{action_type}': {required}"
                }

    # Execução das queries se todas forem válidas
    results = {}
    for query in queries:
        action_type = query["action_type"]
        params = query.get("params", {})
        result = system_operations_service.execute(action_type, params)
        results[action_type] = result
    
    return results