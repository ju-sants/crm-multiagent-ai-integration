import requests
import json
import os
from typing import Dict, Any, List
import datetime

from app.core.logger import get_logger
from app.config.settings import settings 

from app.utils.funcs.reset_sending import process_reset_sending

logger = get_logger(__name__)

class SystemOperationsService:
    """
    Serviço central para executar tanto operações de sistema granulares quanto workflows de negócio
    complexos, interagindo com múltiplas APIs e plataformas internas.
    """

    def __init__(self):
        # As URLs base devem ser configuradas para fácil manutenção
        self.plataforma_api_base_url = "https://api.plataforma.app.br"

    def execute(self, action_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Roteador principal que chama a função ou o workflow apropriado com base no action_type.
        """
        action_map = {
            # --- Funções Técnicas ---
            "GET_VEHICLE_DETAILS": self._get_vehicle_details,
            "GET_VEHICLE_POSITIONS": self._get_vehicle_positions,
            "GET_PAYMENT_HISTORY": self._get_payment_history,
            "SEARCH_CLIENTS": self._search_clients,
            "SEARCH_VEHICLES": self._search_vehicles,
            "GET_CLIENT_VEHICLES": self._get_client_vehicles,
            "GET_VEHICLE_TRIPS_REPORT": self._get_vehicle_trips_report,
            "GET_VEHICLE_EVENTS_REPORT": self._get_vehicle_events_report,
            "GET_VEHICLE_GEOFENCES": self._get_vehicle_geofences,
            
            # --- Workflows ---
            "WF_GET_VEHICLE_FULL_REPORT": self._wf_get_vehicle_full_report,
            "WF_SEND_TRACKER_RESET": self._wf_send_tracker_reset_command,
            "WF_FIND_CLIENT_AND_GET_FINANCIALS": self._wf_find_client_and_get_financials
        }

        action_function = action_map.get(action_type)

        if not action_function:
            return {"status": "error", "error_message": f"Ação desconhecida: {action_type}. A ação deve ser uma das seguintes: {list(action_map.keys())}"}

        try:
            result_data = action_function(params)
            return {"status": "success", "data": result_data}
        except Exception as e:
            logger.error(f"Erro ao executar a ação '{action_type}' com parâmetros {params}: {e}", exc_info=True)
            return {"status": "error", "error_message": str(e)}

    # --- Implementações de Funções Técnicas ---

    def _get_vehicle_details(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Busca detalhes de um veículo específico."""
        vehicle_id = params.get("vehicle_id")
        if not vehicle_id: raise ValueError("'vehicle_id' é obrigatório.")
        
        url = f"{self.plataforma_api_base_url}/manager/vehicle/{vehicle_id}"
        headers = {"X-TOKEN": settings.PLATAFORMA_X_TOKEN}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json()

    def _get_vehicle_positions(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Busca o histórico de posições de um veículo.
        Adaptação da função get_vehicle_positions.
        """
        required_params = ["vehicle_id", "initial_date", "final_date"]
        if not all(p in params for p in required_params):
            raise ValueError(f"Parâmetros obrigatórios ausentes. Necessário: {', '.join(required_params)}")

        url = f"{self.plataforma_api_base_url}/report/{params['vehicle_id']}/positions"
        request_params = {
            "initial_date": params['initial_date'],
            "final_date": params['final_date'],
            "ignition_state": params.get("ignition_state", 2),
            "speed_above": params.get("speed_above", 0)
        }
        headers = {"X-TOKEN": settings.PLATAFORMA_X_TOKEN}

        logger.info(f"SERVICE: Buscando posições com parâmetros: {request_params}")
        response = requests.get(url, headers=headers, params=request_params, timeout=30)
        response.raise_for_status()
        return response.json()

    def _get_payment_history(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Busca o histórico de boletos de um cliente no Gerencianet.
        """
        customer_id = params.get("customer_id")
        if not customer_id: raise ValueError("'customer_id' é obrigatório.")

        last_months = params.get("last_months", 36)
        include_nfe = params.get("include_nfe_history", 1)
        include_receipt = params.get("include_receipt_history", 1)
        
        url = f"{self.plataforma_api_base_url}/gerencianet/payment/history/{customer_id}"
        headers = {"X-TOKEN": settings.PLATAFORMA_X_TOKEN}
        request_params = {
            "last_months": last_months,
            "include_nfe_history": include_nfe,
            "include_receipt_history": include_receipt
        }
        
        logger.info(f"SERVICE: Buscando histórico financeiro para customer_id: {customer_id}")
        response = requests.get(url, headers=headers, params=request_params, timeout=20)
        response.raise_for_status()
        return response.json()

    def _search_clients(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Busca e pagina clientes na plataforma principal.
        Adaptação da função get_client_data.
        """
        url = f"{self.plataforma_api_base_url}/manager/users"
        headers = {"X-TOKEN": settings.PLATAFORMA_X_TOKEN}
        
        request_params = {
            'include_managers': 1,
            'items_per_page': params.get('items_per_page', 50),
            'paginate': 1,
            'current_page': params.get('page', 1),
            'all': params.get('search_term', ''),
            'active': params.get('active_filter'),
            'financial_alert': params.get('financial_alert_filter')
        }

        request_params = {k: v for k, v in request_params.items() if v is not None}
        
        logger.info(f"SERVICE: Buscando clientes com parâmetros: {request_params}")
        response = requests.get(url, headers=headers, params=request_params, timeout=20)
        response.raise_for_status()
        return response.json()

    def _get_client_vehicles(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Busca a lista de veículos associados a um ID de cliente específico.
        Adaptação da função get_vehicles.
        """
        client_id = params.get('client_id')
        if not client_id: raise ValueError("'client_id' é obrigatório.")

        url = f"{self.plataforma_api_base_url}/manager/user/{client_id}/vehicles"
        headers = {"X-TOKEN": settings.PLATAFORMA_X_TOKEN}
        
        logger.info(f"SERVICE: Buscando veículos para o client_id: {client_id}")
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json()

    def _get_vehicle_trips_report(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Busca o relatório de viagens (percursos/trilhas) de um veículo.
        Adaptação da função get_vehicle_trips.
        """
        vehicle_id = params.get("vehicle_id")
        if not vehicle_id: raise ValueError("'vehicle_id' é obrigatório.")
        
        url = f"{self.plataforma_api_base_url}/report/vehicle/{vehicle_id}/trips/v2"
        headers = {"X-TOKEN": settings.PLATAFORMA_X_TOKEN}
        request_params = {
            "from": params.get("start_date"),
            "to": params.get("end_date"),
            "include_positions": params.get("include_positions", 0)
        }

        logger.info(f"SERVICE: Buscando relatório de viagens para vehicle_id: {vehicle_id}")
        response = requests.get(url, headers=headers, params=request_params, timeout=30)
        response.raise_for_status()
        return response.json()

    def _get_vehicle_events_report(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Busca o relatório de eventos e alertas (ignição, cercas, etc.).
        Adaptação da função sisras_events_report.
        """
        vehicle_id = params.get("vehicle_id")
        if not vehicle_id: raise ValueError("'vehicle_id' é obrigatório.")

        url = f"{self.plataforma_api_base_url}/sisras/web/events/report"
        headers = {"X-TOKEN": settings.PLATAFORMA_X_TOKEN, "Content-Type": "application/json"}
        payload = {
            "vehicleId": vehicle_id,
            "initialDate": params.get("start_date"),
            "finalDate": params.get("end_date")
        }

        logger.info(f"SERVICE: Buscando relatório de eventos para vehicle_id: {vehicle_id}")
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def _get_vehicle_geofences(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Busca todas as cercas eletrônicas de um veículo.
        Adaptação da integração de busca de geofences.
        """
        vehicle_id = params.get("vehicle_id")
        if not vehicle_id: raise ValueError("'vehicle_id' é obrigatório.")

        url = f"{self.plataforma_api_base_url}/vehicle/{vehicle_id}/geofences"
        headers = {"X-TOKEN": settings.PLATAFORMA_X_TOKEN}
        
        logger.info(f"SERVICE: Buscando cercas eletrônicas para vehicle_id: {vehicle_id}")
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()
    
    def _get_vehicle_data_by_plate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Busca detalhes de um veículo com base em sua placa.
        Adaptação da função get_vehicle_details.
        """
        plate = params.get("plate")
        if not plate: raise ValueError("'plate' é obrigatório.")

        search_result = self._search_vehicles({"search_term": plate})
        if not search_result:
            raise ValueError(f"Nenhum veículo encontrado com a placa {plate}.")
        
        return search_result

    def _search_vehicles(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Obter TODOS os veículos cadastrados, paginado e por pesquisa"""

        # --- Configurações da API ---
        API_URL = "https://api.plataforma.app.br/manager/vehicles"
        # Token e headers baseados no geofence_deleter.py e informações fornecidas
        HEADERS = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 OPR/117.0.0.0",
            "Origin": "https://globalsystem.plataforma.app.br",
            "Referer": "https://globalsystem.plataforma.app.br/",
            "x-token": settings.PLATAFORMA_X_TOKEN,
        }

        items_per_page = params.get('items_per_page')
        current_page = params.get('current_page')
        search_term = params.get('search_term')

        PARAMS = {
            "items_per_page": 50 if not items_per_page else items_per_page,
            "paginate": 1,
            "current_page": 1 if not current_page else current_page,
            "sort_by_field": "license_plate",
            "sort_direction": "asc"
        }

        if search_term:
            PARAMS['all'] = search_term

        # --- Botão para Buscar Dados ---
        try:
            response = requests.get(API_URL, headers=HEADERS, params=PARAMS, timeout=60)
            response.raise_for_status() # Lança exceção para status HTTP 4xx/5xx
            data = response.json()

            data_v = data.get('data', [])
            if data_v:
                if not current_page:
                    logger.info(f"{len(data_v)} registros de veículos carregados.")

                return data_v
            else:
                return []
                    
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"Erro HTTP ao buscar dados: {http_err}")
            logger.error(f"Detalhes: {response.text}")
            return []
        
        except requests.exceptions.RequestException as req_err:
            logger.error(f"Erro de requisição ao buscar dados: {req_err}")
            return []
        
        except ValueError as json_err: # Trata erro de decodificação do JSON
            logger.error(f"Erro ao decodificar JSON da resposta da API: {json_err}")
            logger.info(f"Conteúdo da resposta: {response.text if 'response' in locals() else 'Não disponível'}")
            return []

    # --- Implementação de Workflows de Negócio ---

    def _wf_get_vehicle_full_report(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        WORKFLOW: Orquestra múltiplas chamadas para montar um relatório completo do veículo.
        Obtém detalhes do veículo e seu histórico de posições recente em uma única ação.
        """
        vehicle_id = params.get("vehicle_id")
        if not vehicle_id: raise ValueError("'vehicle_id' é obrigatório para este workflow.")

        logger.info(f"SERVICE WORKFLOW: Iniciando relatório completo para vehicle_id: {vehicle_id}")

        # 1. Primeira chamada de API: Obter detalhes do veículo
        details = self._get_vehicle_details({"vehicle_id": vehicle_id})
        
        # 2. Segunda chamada de API: Obter posições dos últimos 2 dias
        today = datetime.date.today()
        seven_days_ago = today - datetime.timedelta(days=2)
        positions_params = {
            "vehicle_id": vehicle_id,
            "initial_date": seven_days_ago.strftime("%Y-%m-%d"),
            "final_date": today.strftime("%Y-%m-%d")
        }
        recent_positions = self._get_vehicle_positions(positions_params)

        # 3. Consolida os resultados em um único objeto de resposta
        full_report = {
            "vehicle_details": details,
            "recent_position_history": recent_positions
        }

        return full_report

    def _wf_send_tracker_reset_command(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        WORKFLOW: Executa o processo completo de envio de um comando de reset para um rastreador.
        Abstrai a complexidade de múltiplos sistemas (Eseye, SMSBarato, resets de rede).
        """
        plate = params.get("plate")
        if not plate: raise ValueError("'plate' é obrigatório para este workflow.")

        # ETAPA 1: Obter os dados do veículo/rastreador usando a placa (função placeholder)
        vehicles_data = self._get_vehicle_data_by_plate({"plate": plate})
        if not vehicles_data:
            return {"status": "error", "message": f"Veículo com placa {plate} não encontrado."}
        
        results = []
        for v in vehicles_data:
            vehicle_data = self._get_vehicle_details({"vehicle_id": v["id"]})
            result = process_reset_sending(vehicle_data)
            results.append(result)
        
        return results

    def _wf_find_client_and_get_financials(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        WORKFLOW: Encontra um cliente pelo nome ou documento e retorna seu
        histórico financeiro completo.
        """
        search_term = params.get("nome_cliente")
        
        if not search_term: raise ValueError("'nome_cliente' é obrigatório.")

        logger.info(f"SERVICE WORKFLOW: Iniciando busca de cliente e histórico financeiro para: {search_term}")

        # 1. Primeira chamada de API: Buscar pelo cliente
        clients_found = self._search_clients({"search_term": search_term, "items_per_page": 1})
        
        client_data = clients_found.get("data", [])
        if not client_data:
            raise ValueError(f"Nenhum cliente encontrado para o termo de busca: '{search_term}'")
        
        payload = []
        for customer in client_data:
            customer_id = customer.get("id")
            
            # 2. Segunda chamada de API: Obter o histórico financeiro com o ID encontrado
            financial_history = self._get_payment_history({"customer_id": customer_id})
            payload.append({
                "customer_details": customer,
                "financial_history": financial_history
            })

        return payload
    

# Instância Singleton do serviço
system_operations_service = SystemOperationsService()