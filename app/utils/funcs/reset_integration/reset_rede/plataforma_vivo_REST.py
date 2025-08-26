import http.client
import ssl
import json
import dotenv
import os
import logging

from app.config.settings import settings

dotenv.load_dotenv()

# --- Constantes ---
HOST = settings.VIVO_HOST  # Hostname da API 
PORT = 8010  # Porta da API 
# Substitua pelos caminhos corretos dos seus arquivos
CERT_FILE = r"certificado_telefonica_vivo.cer"
KEY_FILE = r"certificado_telefonica_vivo.key"
# Senha da chave privada, se houver (ajuste se for diferente)
KEY_PASSWORD = settings.VIVO_KEY_PASSWORD

# --- SUBSTITUA PELO ICCID ALVO APÓS EXECUTAR get_subscriptions_rest ---
ICCID_ALVO = "SEU_ICCID_AQUI"
# -----------------------------------------------------------------------

# --- DEFINA OS PARAMETROS DO RESET ---
# Escolha pelo menos um
RESET_2G3G = True
RESET_4G = True
# ------------------------------------

def _make_rest_request(method, endpoint, cert_file, key_file, key_password, body=None, logger=None):
    """Função auxiliar para fazer requisições REST com mTLS."""
    try:
        with open(cert_file, 'w') as f:
            f.write(os.getenv('CERT_CER'))

        with open(key_file, 'w') as f:
            f.write(os.getenv('CERT_KEY'))

        # Cria o contexto seguro SSL
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_default_certs(ssl.Purpose.SERVER_AUTH)
        context.load_cert_chain(certfile=cert_file, keyfile=key_file, password=key_password)

        # Estabelece a conexão HTTPS
        conn = http.client.HTTPSConnection(HOST, port=PORT, context=context)

        # Cabeçalhos comuns para REST
        headers = {'Accept': 'application/json'}
        if body:
            headers['Content-Type'] = 'application/json; charset=utf-8'

        # --- LOGGING ---
        logger.info(f"--- INICIANDO REQUISIÇÃO {method} ---")
        logger.info(f"Host: {HOST}:{PORT}")
        logger.info(f"Endpoint: {endpoint}")
        logger.info(f"Método: {method}")
        logger.info("Cabeçalhos da Requisição:")
        logger.info(headers)

        if body:
            logger.info("Corpo da Requisição (JSON):")
            # Imprime o corpo formatado se for JSON válido
        logger.info("-----------------------------------")
        # --- FIM LOGGING ---

        # Envia a requisição
        conn.request(method, endpoint, body.encode('utf-8') if body else None, headers)

        # Obtém a resposta
        response = conn.getresponse()

        os.remove(cert_file)
        os.remove(key_file)

        # --- LOGGING ---
        logger.info("\n--- RESPOSTA RECEBIDA ---")
        logger.info(f"Status Code: {response.status} {response.reason}")
        logger.info("Cabeçalhos da Resposta:")

        for header, value in response.getheaders():
            logger.info(f"{header}: {value}")

        response_body_bytes = response.read()
        logger.info("Corpo da Resposta:")

        try:
            # Tenta decodificar e formatar como JSON
            decoded_body = response_body_bytes.decode('utf-8')
            parsed_json = json.loads(decoded_body)

            with open('inventory-vivo.json', 'w', encoding='utf-8') as f:
                f.write(json.dumps(parsed_json, indent=2))
            response_data = parsed_json
            # logger.info(json.dumps(parsed_json, indent=2))
        except (UnicodeDecodeError, json.JSONDecodeError):
            # Se não for JSON ou não decodificar, imprime como string (ou bytes)
            try:
                #  logger.info(response_body_bytes.decode('utf-8'))
                 response_data = response_body_bytes.decode('utf-8')
            except UnicodeDecodeError:
                 logger.info(response_body_bytes)
                 response_data = response_body_bytes
        logger.info("-------------------------")
        # --- FIM LOGGING ---

        conn.close()

        return response.status, response_data

    except ssl.SSLError as e:
        logger.error(f"Erro de SSL: {e}")
        if "PEM routines" in str(e) and "bad password read" in str(e):
             logger.error("Verifique se a senha fornecida para a chave privada está correta.")
        elif "CERTIFICATE_VERIFY_FAILED" in str(e):
             logger.error("A verificação do certificado do servidor falhou.")
        return 500, {"error": "SSL Error", "details": str(e)}
    except Exception as e:
        logger.error(f"Erro durante a conexão ou requisição: {e}")
        return 500, {"error": "Connection/Request Error", "details": str(e)}

def get_subscriptions_rest(cert_file, key_file, key_password, max_batch_size=1000, start_index=0, logger=None):
    """
    Busca informações das subscrições usando a API REST GET.

    Args:
        cert_file (str): Caminho para o arquivo de certificado do cliente.
        key_file (str): Caminho para o arquivo de chave privada do cliente.
        key_password (str): Senha da chave privada.
        max_batch_size (int): Número máximo de resultados por página. [cite: 168]
        start_index (int): Índice inicial para paginação. [cite: 169]

    Returns:
        tuple: (status_code, response_data) onde response_data é um dict/list ou None em caso de erro.
    """
    endpoint = f"/services/REST/GlobalM2M/Inventory/v13/r12/sim?maxBatchSize={max_batch_size}&startIndex={start_index}" # [cite: 166]
    status, data = _make_rest_request("GET", endpoint, cert_file, key_file, key_password, logger=logger)

    if status == 200:
        return status, data
    else:
        logger.error(f"Falha ao buscar subscrições. Status: {status}")
        return status, data # Retorna dados mesmo em erro para análise

def network_reset_rest(cert_file, key_file, key_password, iccid, reset_2g3g=False, reset_4g=False, logger=None):
    """
    Executa um network reset em um SIM específico usando a API REST PUT. [cite: 344]

    Args:
        cert_file (str): Caminho para o arquivo de certificado do cliente.
        key_file (str): Caminho para o arquivo de chave privada do cliente.
        key_password (str): Senha da chave privada.
        iccid (str): O ICCID do SIM alvo.
        reset_2g3g (bool): Executar reset 2G/3G. [cite: 346]
        reset_4g (bool): Executar reset 4G. [cite: 347]

    Returns:
        tuple: (status_code, response_data) onde response_data é um dict ou None em caso de erro.
    """
    if not iccid or iccid == "SEU_ICCID_AQUI":
         logger.error("Erro: ICCID alvo não fornecido.")
         return 400, {"error": "Missing ICCID"}

    # Endpoint REST para networkReset, formato icc:{ICC value} [cite: 54]
    endpoint = f"/services/REST/GlobalM2M/Inventory/v13/r12/sim/icc:{iccid}/networkReset" # [cite: 344]

    # Corpo da requisição JSON
    request_body_dict = {}
    if reset_2g3g:
        request_body_dict["network2g3g"] = True # [cite: 346]
    if reset_4g:
        request_body_dict["network4g"] = True # [cite: 347]

    if not request_body_dict:
        logger.error("Erro: Pelo menos um tipo de reset (network2g3g ou network4g) deve ser selecionado.")
        return 400, {"error": "No reset type selected"}

    request_body_json = json.dumps(request_body_dict)

    status, data = _make_rest_request("PUT", endpoint, cert_file, key_file, key_password, body=request_body_json, logger=logger)

    # Status 200 OK é esperado para sucesso nesta operação PUT específica [cite: 348, 571]
    if status == 200:
        logger.info("Network Reset executado com sucesso.")
        return status, data
    elif status == 204: # Algumas operações PUT retornam 204, embora 200 seja o documentado aqui
         logger.info("Network Reset executado com sucesso (Status 204 No Content).")
         return status, {} # Retorna dict vazio para indicar sucesso sem corpo
    else:
        logger.error(f"Falha ao executar Network Reset. Status: {status}")
        return status, data # Retorna dados mesmo em erro para análise

def main(recipient, logger):
    try:
        logger.info("--- PASSO 1: Obtendo lista de subscrições (para encontrar o ICCID) ---")
        sub_status, sub_data = get_subscriptions_rest(CERT_FILE, KEY_FILE, KEY_PASSWORD, logger=logger)

        for sub in sub_data['subscriptionData']:
            if sub.get('msisdn') == recipient:
                ICCID_ALVO = sub.get('icc')

        if sub_status == 200 and sub_data and 'subscriptionData' in sub_data:
            logger.info("\nLista de subscrições recebida com sucesso.")

            # Exemplo de como acessar o primeiro ICCID (APENAS PARA DEMONSTRAÇÃO)
            if sub_data['subscriptionData']:
                primeiro_iccid = sub_data['subscriptionData'][0].get('icc', 'NÃO ENCONTRADO')
                logger.info(f"\nO ICCID da primeira subscrição na lista é: {primeiro_iccid}")
            else:
                logger.info("\nNenhuma subscrição encontrada na resposta.")

        else:
            logger.error("\nNão foi possível obter a lista de subscrições.")
            logger.error("Verifique os logs de erro acima e a configuração dos certificados/rede.")

        logger.info("\n--- PASSO 2: Executando Network Reset (se ICCID_ALVO foi definido) ---")
        if ICCID_ALVO == "SEU_ICCID_AQUI":
            logger.error("AVISO: A variável 'ICCID_ALVO' ainda não foi definida com um ICCID real.")
            logger.error("Execute o script novamente após definir o ICCID correto.")
        else:
            logger.info(f"Tentando executar Network Reset para o ICCID: {ICCID_ALVO}...")
            reset_status, reset_data = network_reset_rest(CERT_FILE, KEY_FILE, KEY_PASSWORD, ICCID_ALVO, RESET_2G3G, RESET_4G, logger=logger)

            # Verifica a resposta específica de sucesso para networkReset
            if reset_status == 200 and reset_data and reset_data.get('result') is True:
                logger.info("\nResultado do Network Reset: Sucesso (result: true)")
            elif reset_status == 204:
                logger.info("\nResultado do Network Reset: Sucesso (Status 204 No Content)")
            else:
                logger.error(f"\nResultado do Network Reset: Falha (Status: {reset_status})")
                if reset_data:
                    logger.error("Detalhes do erro (se disponíveis):")
                    logger.error(json.dumps(reset_data, indent=2))
    except Exception as e:
        logger.error(f'Houve um erro não tratado na execução do reset de rede vivo para o telefone {recipient}, {e}.')

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    main('5577999575140', logger)
