import json
import re
import requests
from unidecode import unidecode

from app.core.logger import get_logger
from app.config.settings import settings
from app.services.redis_service import get_redis
from app.models.data_models import ConversationState
from app.utils.static import agent_state_mapping


logger = get_logger(__name__)
redis_client = get_redis()

def get_vehicle_details(vehicle_id):
    """Fetches details for a specific vehicle ID."""
    url = f"https://api.plataforma.app.br/manager/vehicle/{vehicle_id}"

    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 OPR/117.0.0.0",
        "Origin": "https://globalsystem.plataforma.app.br",
        "Referer": "https://globalsystem.plataforma.app.br/",
        "x-token": settings.PLATAFORMA_X_TOKEN,
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get details for vehicle {vehicle_id}: {e}")
        return {} # Return empty dict on error
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON for vehicle {vehicle_id}: {e}")
        return {}

def sanitize_tel(tel):
    """Removes country code 55 if present."""
    if isinstance(tel, str) and tel.startswith('55') and (len(tel) == 12 or len(tel) == 13):
        tel = tel[2:]
    return tel

def qual_fornecedora(observation):
    if observation:
        if bool(re.search(r"\beseye\b", unidecode(observation), re.IGNORECASE)):
            return 'ESEYE'
        
        if bool(re.search(r"\bvs\b", unidecode(observation), re.IGNORECASE)):
            return 'VS'
        
        if bool(re.search(r"\bvsolucoes\b", unidecode(observation), re.IGNORECASE)):
            return 'VS'
        
        if bool(re.search(r"\blinks field\b", unidecode(observation), re.IGNORECASE)):
            return 'LINKS'
        
        if bool(re.search(r"\blf\b", unidecode(observation), re.IGNORECASE)):
            return 'LINKS'
        
        if bool(re.search(r"\blinksfield\b", unidecode(observation), re.IGNORECASE)):
            return 'LINKS'
        
        if bool(re.search(r"\btelefonica\b", unidecode(observation), re.IGNORECASE)):
            return 'VIVO'
        
        if bool(re.search(r"\ballcom\b", unidecode(observation), re.IGNORECASE)):
            return 'ALLCOM'
        
        if bool(re.search(r"\bveye\b", unidecode(observation), re.IGNORECASE)):
            return 'VEYE'
        
        if bool(re.search(r"\bvirtueyes\b", unidecode(observation), re.IGNORECASE)):
            return 'VEYE'
        
        if bool(re.search(r"\bvirtu\b", unidecode(observation), re.IGNORECASE)):
            return 'VEYE'
        
        if bool(re.search(r"\blink\b", unidecode(observation), re.IGNORECASE)):
            return 'LINK'
        
        if bool(re.search(r"\btns\b", unidecode(observation), re.IGNORECASE)):
            return 'LINK'
        
        if bool(re.search(r"\blinksol\b", unidecode(observation), re.IGNORECASE)):
            return 'LINK'

def padronizar_telefone(telefone):
    # Remove tudo que não for número
    telefone = re.sub(r'\D', '', telefone)

    # Lógicas de normalização
    if len(telefone) == 13 and telefone.startswith('55'):
        # Ex: 55 + DDD + 9 dígitos (celular)
        return telefone
    elif len(telefone) == 12 and telefone.startswith('55'):
        # Ex: 55 + DDD + 8 dígitos (fixo)
        return telefone
    elif len(telefone) == 11 and telefone[2] == '9':
        # Ex: DDD + 9 dígitos → celular nacional sem código do país
        return '55' + telefone
    elif len(telefone) == 10:
        # Ex: DDD + 8 dígitos → fixo nacional sem código do país
        return '55' + telefone
    elif len(telefone) == 13 and not telefone.startswith('55'):
        # Ex: 1 + DDD + número (mal formatado) → remove 1º dígito e insere 55
        return '55' + telefone[1:]
    elif len(telefone) > 13 and '55' in telefone:
        # Remove excesso de dígitos e mantém estrutura correta
        telefone = telefone[telefone.find('55'):]
        return telefone[:13]
    else:
        # Caso não caiba em nenhuma regra
        return None
def distill_conversation_state(conversation_state: ConversationState, agent_name: str) -> dict:
    """
    Filtra o ConversationState para fornecer a cada agente apenas os dados
    necessários para sua tarefa, otimizando o contexto e a performance.

    Args:
        conversation_state: O objeto de estado completo da conversa.
        agent_name: O nome do agente para o qual o estado será destilado.

    Returns:
        Um dicionário contendo apenas as chaves do estado relevantes para o agente.
    """
    required_keys = agent_state_mapping.get(agent_name)
    conversation_dict = conversation_state.model_dump()

    # Se o agente não está no mapa ou se o valor é None, retorne o estado completo.
    if required_keys is None:
        logger.debug(f"Nenhum mapeamento de estado encontrado para o agente '{agent_name}'. Retornando estado completo.")
        return conversation_dict

    distilled_state = {}
    for key in required_keys:
        if key in conversation_dict:
            distilled_state[key] = conversation_dict[key]

    logger.debug(f"Estado destilado para o agente '{agent_name}': {list(distilled_state.keys())}")
    return distilled_state