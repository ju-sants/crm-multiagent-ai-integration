from langchain_core.tools import tool
from typing import List, Dict, Any


from app.services.system_operations_service import system_operations_service
from app.core.logger import get_logger

logger = get_logger(__name__)

@tool("system_operations_tool")
def system_operations_tool(queries: List[Dict[str, Any]]) -> dict:
    """
    Executa operações de sistema. Para eficiência, utilize consultas em lote.
    O input é uma lista de dicionários, cada um com `action_type` e `params`.

    CATÁLOGO DE OPERAÇÕES DE SISTEMA:

    # --- Funções Técnicas (Ações Granulares) ---
    - action_type: 'SEARCH_CLIENTS', params: {'search_term': '...'}
    - action_type: 'SEARCH_VEHICLES', params: {'search_term': '...'}
    - action_type: 'GET_CLIENT_VEHICLES', params: {'client_id': '...'}
    - action_type: 'GET_VEHICLE_DETAILS', params: {'vehicle_id': '...'}
    - action_type: 'GET_VEHICLE_POSITIONS', params: {'vehicle_id': '...', 'initial_date': '...', 'final_date': '...'}
    - action_type: 'GET_VEHICLE_TRIPS_REPORT', params: {'vehicle_id': '...', 'start_date': '...', 'end_date': '...'}
    - action_type: 'GET_VEHICLE_EVENTS_REPORT', params: {'vehicle_id': '...', 'start_date': '...', 'end_date': '...'}
    - action_type: 'GET_VEHICLE_GEOFENCES', params: {'vehicle_id': '...'}
    - action_type: 'GET_VEHICLES_WITH_SIGNAL_FAIL', params: {}
    - action_type: 'GET_PAYMENT_HISTORY', params: {'customer_id': '...'}

    # --- Workflows de Negócio (Ações Orquestradas) ---
    - action_type: 'WF_FIND_CLIENT_AND_GET_FINANCIALS', params: {'search_term': '...'}
    - action_type: 'WF_GET_VEHICLE_FULL_REPORT', params: {'vehicle_id': '...'}
    - action_type: 'WF_SEND_TRACKER_RESET', params: {'plate': '...'}
    - action_type: 'WF_CALCULATE_DISPLACEMENT_COST', params: {'destination_city': '...', 'destination_state': '...'}

    Notas sobre parâmetros:
    - Os parâmetros do tipo "search_term" podem ser qualquer informação relatada ao cliente/veículo que o sistema o encontrará, como nome, CPF, placa, etc.
    - Os parâmetros do tipo ID podem ser obtidos utilizando uma ação de busca "SEARCH_*"
    - Para relatórios use intervalos de data de até um dia atrás, pois o sistema backend pode falhar em intervalos longos, formato: YYYY-MM-DD HH:MM:SS.

    Args:
        queries (List[Dict[str, Any]]): Uma lista de dicionários contendo as queries.
    """
    logger.info(f"Received queries: {queries}")

    # pre check
    if not isinstance(queries, list):
        return {"status": "error", "error_message": "O input deve ser uma lista de dicionários de query."}
    
    if not all(isinstance(query, dict) for query in queries):
        return {"status": "error", "error_message": "O input deve ser uma lista de dicionários de query."}
    
    if not all(query.get("action_type") for query in queries):
        return {"status": "error", "error_message": "Todas as queries devem ter um campo 'action_type'."}
    
    results = {}
    for query in queries:
        action_type = query.get("action_type", "")
        params = query.get("params", {})
        result = system_operations_service.execute(action_type, params)
        
        results[action_type] = result
    
    return results