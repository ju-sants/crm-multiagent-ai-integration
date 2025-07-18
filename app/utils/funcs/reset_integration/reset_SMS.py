import requests
import json
import logging
from urllib.parse import urljoin
from base64 import b64encode
import logging

from app.core.logger import get_logger

logger = get_logger(__name__)

# Global variable to store log messages
report_lines = []

# --- Configuração ---
BASE_URL = settings.ESEYE_BASE_URL

# --- Funções ---

def login(username: str, password: str, session: requests.Session = None) -> requests.Session | None:
    """
    Realiza login na plataforma Eseye e retorna uma sessão autenticada.
    """
    login_url = urljoin(BASE_URL, "user/login")

    if not session:
        session = requests.Session() # Inicia uma nova sessão para guardar cookies

    # Payload baseado nos detalhes fornecidos (form-data)
    payload = {
        'username': username,
        'password': password,
        'signin': 'Sign in' # Valor do botão conforme observado
    }
    # Cabeçalhos baseados na requisição de login
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Origin': BASE_URL.rstrip('/'),
        'Referer': login_url,
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
    }

    try:
        logger.info(f"Tentando login como {username}...")
        response = session.post(login_url, data=payload, headers=headers, allow_redirects=True)
        response.raise_for_status() # Verifica erros na *última* resposta após redirecionamentos

        PHPSESSIONID = session.cookies

        final_url = response.url
        expected_final_url_path = "/sim/index"
        logger.info(f"URL final após tentativa de login: {final_url}")

        if expected_final_url_path in final_url and response.status_code == 200:
            logger.info("Login realizado com sucesso!")
            return session, PHPSESSIONID
        else:
            logger.error("Falha no login. URL final ou status code inesperado.")
            logger.error(f"Status Code final: {response.status_code}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Erro na requisição de login: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Status Code: {e.response.status_code}")
            logger.error(f"Response Body: {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Um erro inesperado ocorreu durante o login: {e}")
        return None

def get_iccid(session: requests.Session, msisdn: str, sess_id) -> str | None:
    """
    Pesquisa por um MSISDN na plataforma Eseye e retorna o ICCID correspondente.
    """
    search_url = urljoin(BASE_URL, "/ajax/getsims")
    payload = {
        'matchFields': 'IM',
        'matchType': 'C',
        'matchString': msisdn,
        'tariff': 'all',
        'group': 'all',
        'state': 'provisioned',
        'usageFilter': '',
        'numRecs': '10',
        'startRecs': '0',
        'sortOrder': 'I',
    }
    headers = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': urljoin(BASE_URL, "/sim/index"),
        'Origin': BASE_URL.rstrip('/'),
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
    }
    try:
        logger.info(f"\nPesquisando ICCID para MSISDN: {msisdn}...")
        response = session.post(search_url, data=payload, headers=headers, cookies=sess_id)
        response.raise_for_status()

        json_data = response.json()

        sims = json_data.get('sims', [])

        iccid = None

        if sims:
            sim = sims[0]

            iccid = sim.get('ICCID', '')

        return iccid

    except requests.exceptions.RequestException as e:
        logger.error(f"Erro na requisição para obter ICCID: {e}")
        logger.error(f'Resposta do Servidor: {response.status_code}, {response.text}')
        if hasattr(e, 'response') and e.response is not None:
             logger.error(f"Status Code: {e.response.status_code}")
             logger.error(f"Response Body: {e.response.text}")
        return None
    
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar JSON da resposta: {e}")
        logger.error(f"Conteúdo recebido: {response.text}")
        return None
    
    except Exception as e:
        logger.error(f"Um erro inesperado ocorreu em get_iccid: {e}")
        return None

def send_sms_eseye(session: requests.Session, iccid: str, message: str, session_id) -> bool:
    """
    Envia uma mensagem SMS para um rastreador específico via plataforma Eseye.
    """
    sms_url_path = f"/sim/controlpanel/modal/1/iccid/{iccid}/controls/S"
    sms_url = urljoin(BASE_URL, sms_url_path)
    payload = {
        'message': message,
        'SMS': 'Send via SMS'
    }
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Origin': BASE_URL.rstrip('/'),
        'Referer': sms_url,
        'Sec-Fetch-Dest': 'iframe',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
    }
    try:
        logger.info(f"\nEnviando SMS para ICCID: {iccid}...")
        logger.info(f"URL: {sms_url}")
        logger.info(f"Payload: {payload}")
        response = session.post(sms_url, data=payload, headers=headers, cookies=session_id)
        logger.info(f"Status Code da resposta: {response.status_code}")
        response.raise_for_status()

        if response.status_code == 200:
             # Verificação simples da resposta HTML por texto de sucesso
             if "SMS successfully sent" in response.text or "SMS queued for delivery" in response.text:
                 logger.info("Sucesso: Requisição de envio de SMS enviada e confirmação encontrada na resposta.")
                 return True
             else:
                 logger.info("Alerta: Requisição enviada (status 200), mas mensagem de sucesso não confirmada na resposta HTML.")
                 # Consideramos sucesso se a requisição foi aceita (200 OK)
                 return True
        else:
            logger.error(f"Falha no envio da requisição de SMS (Status: {response.status_code}).")
            return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro na requisição para enviar SMS: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Status Code: {e.response.status_code}")
            logger.error(f"Response Body: {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"Um erro inesperado ocorreu em send_sms: {e}")
        return False

def reset_eseye(msisdn_alvo, comando, session):
    """
    Executa o reset de um dispositivo Eseye.
    """
    import os
    import dotenv

    dotenv.load_dotenv()

    try:
        # Credenciais (substitua pelos valores reais ou use variáveis de ambiente)
        USERNAME = os.getenv("USERNAME_ESEYE")
        PASSWORD = os.getenv("PASSWORD_ESEYE")
        # 1. Realizar Login
        authenticated_session, PHPSESSIONID = login(USERNAME, PASSWORD, session)

        # 2. Proceder somente se o login foi bem-sucedido
        if authenticated_session:
            # 3. Obter ICCID usando a sessão autenticada
            iccid_encontrado = get_iccid(authenticated_session, msisdn_alvo, PHPSESSIONID)

            if iccid_encontrado:
                # 4. Enviar SMS usando a sessão autenticada e o ICCID encontrado
                sucesso_envio = send_sms_eseye(authenticated_session, iccid_encontrado, comando, PHPSESSIONID)

                if sucesso_envio:
                    logger.info(f"\nRequisição para enviar SMS '{comando}' para {iccid_encontrado} (MSISDN: {msisdn_alvo}) enviada com sucesso.")
                else:
                    logger.error(f"\nFalha ao enviar requisição de SMS para {iccid_encontrado} (MSISDN: {msisdn_alvo}).")
                return sucesso_envio
            else:
                logger.error(f"\nNão foi possível encontrar o ICCID para {msisdn_alvo}.")
                return False
        else:
            logger.error('Não foi possível autenticar na plataforma da Eseye.')
            return False
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        logger.error(f'Houve um erro não tratado ao tentar enviar um reset sms eseye para o telefone {msisdn_alvo}, {e}.')


def reset_sms(recipient, message):
    """
    Envia SMS via API smsbarato.
    """
    url = settings.SMS_BARATO_URL
    usuario = settings.SMS_BARATO_USER
    senha = settings.SMS_BARATO_PASSWORD
    auth_header = b64encode(f"{usuario}:{senha}".encode()).decode()
    headers = {"Authorization": f"Basic {auth_header}", "Content-Type": "application/x-www-form-urlencoded"}
    payload = {"dest": recipient, "text": message, "countdown": 160 - len(message), "Enviar": "Enviar"}
    try:
        response = requests.post(url, headers=headers, data=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"SMS API call to {recipient} successful (status {response.status_code}).")
        return response
    except requests.exceptions.RequestException as e:
        logger.error(f"SMS API call to {recipient} failed: {e}")
        return None

if __name__ == '__main__':
    reset_eseye('5518920039280', 'ST300;CMD84218115;0203', requests.Session())