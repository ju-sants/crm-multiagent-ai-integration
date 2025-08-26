import time
import requests
import logging

from app.config.settings import settings

def main(session, recipient, logger):
    """Realiza login na LSM (TNSi) e busca todos os dados dos SIMs/dispositivos."""
    logger.info("[LSM] Iniciando busca de dados.")
    base_url = settings.LINK_BASE_URL
    auth_url = f'{base_url}/api/authenticate'
    bearer_token = None

    try:
        # 1. Autenticar para obter o Token Bearer
        auth_payload = {'username': settings.LINK_LOGIN, 'password': settings.LINK_PASSWORD}
        # Headers mínimos para autenticação
        auth_headers = {
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json;charset=UTF-8',
            'Origin': base_url,
            'Referer': f'{base_url}/',
        }

        cache_buster_auth = int(time.time() * 1000) # Cache buster em milissegundos
        logger.info(f"[LSM] Enviando POST para autenticação em {auth_url}?cacheBuster={cache_buster_auth}")
        response_auth = session.post(f'{auth_url}?cacheBuster={cache_buster_auth}',
                                     headers=auth_headers,
                                     json=auth_payload,
                                     timeout=30)
        response_auth.raise_for_status()
        auth_data = response_auth.json()
        bearer_token = auth_data.get('id_token')
        if not bearer_token:
            logger.error("[LSM] Falha ao obter o Bearer token na autenticação.")
            return None

        logger.info("[LSM] Autenticação bem-sucedida. Token Bearer obtido.")
        logger.info(f"[LSM] Bearer Token: {bearer_token[:10]}...")

        headers_reset = {
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "authorization": f'Bearer {bearer_token}',
            "connection": "keep-alive",
            "host": base_url.split("//")[-1],
            "referer": f"{base_url}/",
            "sec-ch-ua": '"Not(A:Brand";v="99", "Opera GX";v="118", "Chromium";v="133"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 OPR/118.0.0.0"
        }

        cache_buster_reset = int(time.time() * 1000) # Cache buster em milissegundos
        reset_data = [recipient]

        response_reset = session.post(f'{base_url}/api/outside?cacheBuster={cache_buster_reset}&action=reset&key=msisdn', json=reset_data, headers=headers_reset)
        response_reset.raise_for_status()
        if response_reset.status_code == 200:
            logger.error(f"[LSM] Reset de rede enviado para {recipient}, com sucesso! status code: {response_reset.status_code}")

        return response_reset.status_code

    except requests.exceptions.Timeout as e:
        logger.error(f"[LSM] Timeout durante a operação: {e}")
    except requests.exceptions.HTTPError as e:
        # Log detalhado do erro HTTP
        error_details = f"Status: {e.response.status_code}."
        try:
            error_body = e.response.json()
            error_details += f" Resposta JSON: {error_body}"
        except requests.exceptions.JSONDecodeError:
            error_details += f" Resposta Texto (parcial): {e.response.text[:200]}..."
        logger.error(f"[LSM] Erro HTTP: {error_details}")
    except requests.exceptions.RequestException as e:
        logger.error(f"[LSM] Erro de Rede: {e}")
    except requests.exceptions.JSONDecodeError as e:
        logger.error(f"[LSM] Erro ao decodificar JSON da resposta: {e}")
    except Exception as e:
        logger.error(f"[LSM] Erro inesperado: {e}")

    return None

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    main(requests.Session(), '5573938368303', logger)
