import json
import re
import requests
from unidecode import unidecode

from app.core.logger import get_logger
from app.config.settings import settings
from app.services.redis_service import get_redis

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


def parse_json_from_string(json_string, update=True):
    """
    Parses a JSON object from a string, attempting to fix common LLM syntax errors.
    This function is designed to be robust against malformed JSON from language models.
    """
    if not isinstance(json_string, str):
        logger.warning("Input is not a string, returning None.")
        return (None, None) if update else None

    processed_string = re.sub(r'```json\s*|\s*```', '', json_string.strip())
    
    match = re.search(r'\{.*\}', processed_string, re.DOTALL)
    if not match:
        logger.warning("No JSON object found in the string.")
        return (None, None) if update else None
    processed_string = match.group(0)

    processed_string = processed_string.replace(': True', ': true').replace(': False', ': false')
    processed_string = processed_string.replace(': None', ': null')

    try:
        json_response = json.loads(processed_string)
    except json.JSONDecodeError as e:
        logger.warning(f"Initial JSON parsing failed: {e}. Attempting to fix common errors...")
        try:
            fixed_string = re.sub(r',\s*([\}\]])', r'\1', processed_string)
            
            fixed_string = re.sub(r'(?<=")\s+(?=")', ',', fixed_string)

            json_response = json.loads(fixed_string)
            logger.info("Successfully parsed JSON after applying automated fixes.")
        except json.JSONDecodeError as e2:
            logger.error(f"Failed to decode JSON string even after attempting fixes: {e2}")
            logger.debug(f"Original string provided to function:\n{json_string}")
            logger.debug(f"String that failed parsing after fixes:\n{fixed_string}")
            return (None, None) if update else None

    if update:
        task_output = json_response.get('task_output')
        updated_state = json_response.get('updated_state')
        return task_output, updated_state
    else:
        return json_response