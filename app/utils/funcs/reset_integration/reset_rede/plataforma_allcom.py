import requests
import logging

from app.config.settings import settings

def obter_token_acesso(auth_url=f"{settings.ALLCOM_BASE_URL}/oauth-portal/access-token", session=None, logger=None):
    """
    Executa a criação de um token de acesso (login).
    """
    payload = {
        "grant_type": 'client_credentials'
    }

    headers = {
        'authorization': f'Basic {settings.ALLCOM_TOKEN}',
        'cache-control': 'no-cache',
        'content-type': 'application/json',
        'realm': '0d5a3954',
        'username': settings.ALLCOM_USER,
        'password': settings.ALLCOM_PASSWORD,
        'Cookie': 'TS013760f7=0117335212ef439c0598d782717985b889dc2c64b30a2003f6b3cfa96aa7391d35114a3245ef15c09b406955920f2ec80e4259a55f'
    }

    try:
        response = session.post(auth_url, headers=headers, json=payload)
        logger.info(f"URL: {auth_url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Payload: {payload}")

        response.raise_for_status()

        token_data = response.json()
        logger.info('Resposta do servidor: ' + str(response.json()))
        logger.info("Token obtido com sucesso!")
        return token_data.get('access_token')

    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao obter token de acesso: {e}")
        if 'response' in locals():
            logger.error(f"Resposta do servidor: {response.status_code} - {response.text}")
        return None

def solicitar_reset_rede(access_token, msisdn, reset_url=f"{settings.ALLCOM_BASE_URL}/telecom/product-Inventory-management/management/v1/broker/reset-network", session=None, logger=None):
    """
    Solicita o reset de rede para um determinado MSISDN.
    """
    headers = {
        "client_id": "38928381-409d-3eac-a791-ca8f11d7dde6",
        'access_token': access_token,
    }

    payload = {
        "msisdns": [msisdn]
    }

    try:
        response = session.post(reset_url, headers=headers, json=payload)
        logger.info(f"Tentando resetar rede para {msisdn}...")
        logger.info(f"URL: {reset_url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Payload: {payload}")

        if response.status_code == 201:
            logger.info("Solicitação de reset de rede enviada com sucesso!")
            logger.info(f"Resposta do servidor (Status {response.status_code}): {response.text}")
            return True
        else:
            logger.error(f"Erro ao solicitar reset de rede. Status: {response.status_code}")
            logger.error(f"Resposta do servidor: {response.text}")
            response.raise_for_status()
            return False

    except requests.exceptions.RequestException as e:
        logger.error(f"Erro na requisição de reset de rede: {e}")
        if 'response' in locals():
            logger.error(f"Resposta do servidor: {response.status_code} - {response.text}")
        return False

def main(recipient, session, logger):
    """
    Função principal para obter token de acesso e solicitar reset de rede.
    """
    MSISDN_PARA_RESETAR = recipient

    try:
        token = obter_token_acesso(session=session, logger=logger)

        if token:
            logger.info(f"\nToken recebido: {token[:10]}...")

            sucesso_reset = solicitar_reset_rede(
                access_token=token,
                msisdn=MSISDN_PARA_RESETAR,
                session=session,
                logger=logger
            )

            if sucesso_reset:
                logger.info("\nFluxo concluído: Token obtido e reset de rede solicitado.")
            else:
                logger.error("\nFluxo falhou na etapa de reset de rede.")
        else:
            logger.error("\nFluxo falhou: Não foi possível obter o token de acesso.")

    except Exception as e:
        logger.error(f'Ocorreu um erro não tratado durante a execução do reset de rede para {recipient}')

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    main("5511972297953", requests.Session(), logger)
