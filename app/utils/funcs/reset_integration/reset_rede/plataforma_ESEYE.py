import requests
import json
from urllib.parse import urljoin
import logging
import os
import dotenv

from app.config.settings import settings

# --- Configuração ---
BASE_URL = settings.ESEYE_BASE_URL

# --- Funções ---
def login(username: str, password: str, session: requests.Session = None, logger=None) -> requests.Session | None:
    """
    Realiza login na plataforma Eseye e retorna uma sessão autenticada.
    """
    login_url = urljoin(BASE_URL, "user/login")

    if not session:
        session = requests.Session()

    payload = {
        'username': username,
        'password': password,
        'signin': 'Sign in'
    }
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
        response.raise_for_status()

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

def get_iccid(session: requests.Session, msisdn: str, sess_id, logger=None) -> str | None:
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

def send_ticket_network_reset(session, iccid, msisdn, logger=None):
    """
    Envia um ticket de redefinição de rede para a plataforma Eseye.
    """
    url = f"{BASE_URL}/support/create"

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded",
        "Host": BASE_URL.split("//")[-1],
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/support/create",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 OPR/118.0.0.0"
    }

    data = {
        "subject": "Manutenção SIM cards",
        "comment": "Olá, solicito que enviem um comando de redefinição e que redirecionem o SIM para outra rede pois os mesmos pararam de trafegar:\n\n"
                    f"{msisdn} - {iccid}\n\n"
                    "Desde já agradeço!",
        "type": "problem",
        "priority": "normal",
        "submit": "Create New Ticket"
    }

    try:
        logger.info(f"Enviando ticket de redefinição de rede para MSISDN: {msisdn}...")
        response = session.post(url, headers=headers, data=data, allow_redirects=False)

        if response.status_code == 302:
            logger.info("Ticket criado com sucesso! Redirecionado para: " + response.headers.get("Location"))
            return True
        else:
            logger.error("Falha ao criar o ticket.")
            logger.error(f"Response: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Erro ao enviar ticket de redefinição de rede: {e}")
        return False

def main(msisdn_alvo, logger, session):
    """
    Função principal para realizar login, obter ICCID e enviar ticket de redefinição de rede.
    """
    dotenv.load_dotenv()

    try:
        USERNAME = os.getenv("USERNAME_ESEYE")
        PASSWORD = os.getenv("PASSWORD_ESEYE")

        authenticated_session, PHPSESSIONID = login(USERNAME, PASSWORD, logger=logger, session=session)

        if authenticated_session:
            iccid_encontrado = get_iccid(authenticated_session, msisdn_alvo, PHPSESSIONID, logger)

            if iccid_encontrado:
                success = send_ticket_network_reset(authenticated_session, iccid_encontrado, msisdn_alvo, logger)
                return success
            else:
                logger.error("ICCID não encontrado.")
                return False
        else:
            logger.error('Não foi possível autenticar na plataforma da Eseye.')
            return False
    except Exception as e:
        logger.error(f'Ocorreu um erro não tratado durante a execução do reset de rede para {msisdn_alvo}')

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    main('5518920039280', logger, requests.Session())
