from langchain_core.tools import tool
from typing import List, Dict, Any
from pydantic import BaseModel, Field


from app.services.system_operations_service import system_operations_service
from app.core.logger import get_logger

logger = get_logger(__name__)


class SystemOperationsToolInput(BaseModel):
    """Input for system_operations_tool."""
    queries: List[Dict[str, Any]] = Field(..., description="A list of query dictionaries to be executed in a single batch. Each dictionary requires an 'action_type' key and an optional 'params' dictionary.")


@tool("system_operations_tool", args_schema=SystemOperationsToolInput)
def system_operations_tool(queries: List[Dict[str, Any]]) -> dict:
    """
    Executa operações de sistema. Para eficiência, utilize consultas em lote.
    O input é uma lista de dicionários, cada um com `action_type` e `params`.

    CATÁLOGO DE OPERAÇÕES DE SISTEMA:

    # --- Workflows de Negócio (Ações Orquestradas) ---
    - action_type: 'GET_VEHICLE_DETAILS', params: {'plate': '...', 'client_name': '...'}
    - action_type: 'GET_VEHICLE_POSITIONS', params: {'plate': '...', 'client_name': '...', 'initial_date': 'YYYY-MM-DD', 'final_date': 'YYYY-MM-DD'}
    - action_type: 'GET_VEHICLE_TRIPS_REPORT', params: {'plate': '...', 'client_name': '...', 'start_date': 'YYYY-MM-DD', 'end_date': 'YYYY-MM-DD'}
    - action_type: 'GET_VEHICLE_EVENTS_REPORT', params: {'plate': '...', 'client_name': '...', 'start_date': 'YYYY-MM-DD', 'end_date': 'YYYY-MM-DD'}
    - action_type: 'GET_VEHICLE_GEOFENCES', params: {'plate': '...', 'client_name': '...'}
    - action_type: 'GET_CLIENT_VEHICLES', params: {'search_term': '...'}
    - action_type: 'GET_PAYMENT_HISTORY', params: {'search_term': '...'}
    - action_type: 'FIND_CLIENT_AND_GET_FINANCIALS', params: {'search_term': '...'}
    - action_type: 'GET_VEHICLE_FULL_REPORT', params: {'plate': '...', 'client_name': '...'}
    - action_type: 'SEND_TRACKER_RESET', params: {'plate': '...'}
    - action_type: 'CALCULATE_DISPLACEMENT_COST', params: {'destination_city': '...', 'destination_state': '...'}

    # --- Ações de Busca (Uso Restrito) ---
    - action_type: 'SEARCH_CLIENTS', params: {'search_term': '...'}
    - action_type: 'SEARCH_VEHICLES', params: {'search_term': '...'}

    Notas sobre parâmetros:
    - 'plate': Placa do veículo.
    - 'client_name': Nome do cliente para desambiguação quando múltiplos veículos com a mesma placa são encontrados.
    - 'search_term': Termo de busca para clientes (nome, CPF, etc.).
    - As datas devem estar no formato YYYY-MM-DD. Para relatórios, use intervalos de até um dia. NÃO PEÇA DATAS AO CLIENTE.

    Ex de input:
        {"queries": [{"action_type": "FIND_CLIENT_AND_GET_FINANCIALS", "params": {"search_term": "JUAN"}}]}
        
    Args:
        queries (List[Dict[str, Any]]): Uma lista de dicionários contendo as queries.
    """
    logger.info(f"Received queries: {queries}")

    # Definição dos parâmetros obrigatórios para cada ação
    required_params = {
        'SEARCH_CLIENTS': ['search_term'],
        'SEARCH_VEHICLES': ['search_term'],
        'GET_CLIENT_VEHICLES': ['search_term'],
        'GET_VEHICLE_DETAILS': ['plate', 'client_name'],
        'GET_VEHICLE_POSITIONS': ['plate', 'client_name', 'initial_date', 'final_date'],
        'GET_VEHICLE_TRIPS_REPORT': ['plate', 'client_name', 'start_date', 'end_date'],
        'GET_VEHICLE_EVENTS_REPORT': ['plate', 'client_name', 'start_date', 'end_date'],
        'GET_VEHICLE_GEOFENCES': ['plate', 'client_name'],
        'GET_PAYMENT_HISTORY': ['search_term'],
        'FIND_CLIENT_AND_GET_FINANCIALS': ['search_term'],
        'GET_VEHICLE_FULL_REPORT': ['plate', 'client_name'],
        'SEND_TRACKER_RESET': ['plate'],
        'CALCULATE_DISPLACEMENT_COST': ['destination_city', 'destination_state'],
    }

    # Validação estrutural do input
    if not isinstance(queries, list) or not all(isinstance(q, dict) for q in queries):
        return {"status": "error", "error_message": "O input deve ser uma lista de dicionários de query."}

    # Validação de cada query individualmente
    for query in queries:
        action_type = query.get("action_type")
        params = query.get("params", {})

        if not action_type:
            return {"status": "error", "error_message": "Todas as queries devem ter um campo 'action_type'."}

        # Validar parâmetros obrigatórios
        if action_type in required_params:
            for param in required_params[action_type]:
                if param not in params or params[param] is None:
                    return {
                        "status": "error",
                        "error_message": f"Parâmetro obrigatório '{param}' ausente ou nulo para a ação '{action_type}'."
                    }

    # Execução das queries se todas forem válidas
    results = {}
    for query in queries:
        action_type = query["action_type"]
        params = query.get("params", {})
        result = system_operations_service.execute(action_type, params)
        results[action_type] = result
    
    return results