import logging
import os
import requests
import json
import dotenv
from datetime import datetime, timedelta, timezone, time
from time import sleep
import threading
import redis # Importado redis
import pytz
from app.services.redis_service import get_redis

# Carrega variáveis de ambiente do arquivo .env
dotenv_path = dotenv.find_dotenv(raise_error_if_not_found=True)
dotenv.load_dotenv(dotenv_path)

# Configurações da API Callbell
CALLBELL_API_KEY = os.getenv('CALLBELL_API_KEY')
CALLBELL_API_BASE_URL = os.getenv('CALLBELL_API_BASE_URL', 'https://api.callbell.eu/v1')
TRACKER_LINE_PROVIDER_NUMBER = os.getenv('TRACKER_LINE_PROVIDER_NUMBER', '5511997178223')
TRACKER_LINE_PROVIDER_NUMBER2 = os.getenv('TRACKER_LINE_PROVIDER_NUMBER2', '558382334462')

# Configurações do Redis
REDIS_HOST = os.getenv('REDIS_HOST_2', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT_2', 6379))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD_2')
REDIS_DB = int(os.getenv('REDIS_DB_2', 5))


# Nomes das chaves no Redis (usando o que você definiu)
REDIS_NUMBERS_TIME_HASH_KEY = 'numbers:time'

# Configuração básica de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

redis_client = get_redis(REDIS_DB, REDIS_HOST, REDIS_PORT, REDIS_PASSWORD)

def get_callbell_headers():
    """Retorna os headers padrão para as requisições Callbell."""
    if not CALLBELL_API_KEY:
        logging.error("CALLBELL_API_KEY não configurado no arquivo .env.")
        raise ValueError("CALLBELL_API_KEY não pode ser nulo.")
    return {
        'Authorization': f'Bearer {CALLBELL_API_KEY}',
        'Content-Type': 'application/json',
    }

def send_callbell_template(phone_number, template_variables, template_uuid): # Renomeado 'text' para 'text_content' para evitar conflito com o tipo
    """Envia uma mensagem de texto simples via Callbell."""
    if not phone_number:
        logging.error("Número de telefone do destinatário (TRACKER_LINE_PROVIDER_NUMBER) não configurado.")
        return False
    if not CALLBELL_API_KEY: # Adicionada verificação aqui também
        logging.error("CALLBELL_API_KEY não configurado. Não é possível enviar mensagem.")
        return False

    url = f"{CALLBELL_API_BASE_URL}/messages/send"
    payload = {
        'to': phone_number,
        'from': 'whatsapp',
        'channel_uuid': 'b3501c231325487086646e19fc647b0d',
        "content": {'text': 'template'},
        'type': 'text',
        "fields": "conversation,contact",
        'template_uuid': template_uuid,
        'template_values': template_variables,
        'optin_contact': True, # Garante que podemos enviar
    }

    logging.info(f"Enviando mensagem para {phone_number}") # Log reduzido para clareza
    try:
        response = requests.post(url, headers=get_callbell_headers(), json=payload, timeout=30) # Adicionado timeout
        response.raise_for_status()  # Levanta HTTPError para respostas 4xx/5xx
        logging.info(f"Mensagem enviada com sucesso para {phone_number}.")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao enviar mensagem para {phone_number}: {e}")
        if e.response is not None:
            logging.error(f"Payload enviado: {json.dumps(payload)}")
            logging.error(f"Resposta recebida: {e.response.status_code} - {e.response.text}")
        else:
            logging.error(f"Payload enviado: {json.dumps(payload)}")
            logging.error("Nenhuma resposta recebida do servidor (possível problema de rede ou timeout).")
        return False
    except ValueError as ve: # Captura o erro de CALLBELL_API_KEY não configurado
        logging.error(f"Erro de configuração ao tentar enviar mensagem: {ve}")
        return False
    except Exception as e:
        logging.error(f"Erro inesperado ao processar envio de mensagem para {phone_number}: {e}")
        return False

def solicitar_envio(recipient_phone_number): # Renomeado 'recipient' para maior clareza
    """
    Adiciona um número de telefone e o timestamp atual ao hash no Redis.
    """
    global redis_client
    if redis_client is None:
        logging.error("Cliente Redis não inicializado. Não é possível solicitar envio.")
        return

    try:
        current_timestamp = datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%Y-%m-%dT%H:%M:%S')
        print(f"Solicitando envio para {recipient_phone_number} às {current_timestamp}")
        redis_client.hset(REDIS_NUMBERS_TIME_HASH_KEY, recipient_phone_number, current_timestamp)
        logging.info(f"Solicitação de reset para {recipient_phone_number} registrada às {current_timestamp}.")
    except redis.exceptions.RedisError as e: # Captura exceções específicas do Redis
        logging.error(f"Erro no Redis ao solicitar envio para {recipient_phone_number}: {e}")
    except Exception as e:
        logging.error(f"Erro inesperado ao solicitar envio para {recipient_phone_number}: {e}")

def get_contact_uuid_by_phone(phone_number):
    """Busca o UUID do contato pelo número de telefone."""
    url = f"{CALLBELL_API_BASE_URL}/contacts/phone/{phone_number}"
    try:
        response = requests.get(url, headers=get_callbell_headers())
        response.raise_for_status()
        data = response.json()
        if data and "contact" in data and data["contact"]:
            # A API pode retornar um objeto ou uma lista com um objeto
            contact_data = data["contact"][0] if isinstance(data["contact"], list) else data["contact"]
            uuid = contact_data.get("uuid")
            link_conversation = contact_data.get("conversationHref")
            name = contact_data.get("name")
            # Verifica se o UUID foi encontrado
            if uuid:
                 return uuid, link_conversation, name
            else:
                logging.warning(f"Campo 'uuid' não encontrado nos dados do contato para {phone_number}. Resposta: {data}")
                return None, None, None
        else:
            logging.warning(f"Contato não encontrado ou formato de resposta inesperado para o telefone: {phone_number}. Resposta: {data}")
            return None, None, None
    except requests.exceptions.RequestException as e:
        if e.response is not None and e.response.status_code == 404:
             logging.warning(f"Contato não encontrado (404) para o telefone: {phone_number}")
             return None, None, None
        logging.error(f"Erro ao buscar UUID do contato {phone_number}: {e}")
        logging.error(f"Resposta recebida (se houver): {e.response.text if e.response else 'N/A'}")
        return None, None, None
    except Exception as e:
        logging.error(f"Erro inesperado ao processar resposta de get_contact_uuid_by_phone para {phone_number}: {e}")
        return None, None, None
    
    
def get_last_message_time(contact_uuid):
    """Busca a data/hora da última mensagem relevante (enviada ou recebida)."""
    if not contact_uuid:
        return None
    url = f"{CALLBELL_API_BASE_URL}/contacts/{contact_uuid}/messages"
    try:
        response = requests.get(url, headers=get_callbell_headers(), params={'page': 1})
        response.raise_for_status()
        data = response.json()
        if data and "messages" in data and data["messages"]:
            for message in sorted(data["messages"], key=lambda m: m.get('createdAt', '0'), reverse=True): # Ordena por mais recente
                if message.get("status") in ["sent", "received"]:
                    created_at_str = message.get("createdAt")
                    if created_at_str:
                        # Lida com diferentes formatos de data
                        try:
                            # Tenta analisar com o formato ISO 8601 padrão
                            return datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                        except ValueError:
                             # Tenta analisar formatos ligeiramente diferentes, se necessário
                             try:
                                return datetime.strptime(created_at_str, '%Y-%m-%d %H:%M:%S.%f%z')
                             except ValueError:
                                logging.warning(f"Formato de data inesperado em get_last_message_time: {created_at_str}")
                                # Retorna None se não conseguir analisar nenhum formato esperado
                                return None # Não encontrou mensagem com data válida
            logging.info(f"Nenhuma mensagem 'sent' ou 'received' encontrada recentemente para {contact_uuid}")
            return None
        else:
            logging.info(f"Nenhuma mensagem encontrada para o contato UUID: {contact_uuid}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao buscar mensagens do contato {contact_uuid}: {e}")
        logging.error(f"Resposta recebida (se houver): {e.response.text if e.response else 'N/A'}")
        return None
    except Exception as e:
        logging.error(f"Erro inesperado ao processar resposta de get_last_message_time para {contact_uuid}: {e}")
        return None

def send_callbell_message(phone_number, text):
    """Envia uma mensagem de texto simples via Callbell."""
    url = f"{CALLBELL_API_BASE_URL}/messages/send"
    payload = {
        'to': phone_number,
        'from': 'whatsapp',
        'type': 'text',
        'content': {'text': text},
    }
    logging.info(f"Enviando mensagem simples para {phone_number}: {text}")
    try:
        response = requests.post(url, headers=get_callbell_headers(), json=payload)
        response.raise_for_status()
        logging.info(f"Mensagem simples enviada com sucesso para {phone_number}.")
        return True
    
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao enviar mensagem simples para {phone_number}: {e}")
        logging.error(f"Payload enviado: {json.dumps(payload)}")
        logging.error(f"Resposta recebida (se houver): {e.response.status_code} - {e.response.text if e.response else 'N/A'}")
        return False
    
    except Exception as e:
        logging.error(f"Erro inesperado ao processar envio de mensagem simples para {phone_number}: {e}")
        return False

        
def verify_redis():
    """
    Verifica o Redis periodicamente. Se houver solicitações e a mais recente
    for mais antiga que o 'interval', agrupa os números e envia a mensagem.
    Esta função é destinada a rodar em uma thread separada.
    """
    global redis_client
    idle_timeout_minutes = int(os.getenv('IDLE_TIMEOUT_MINUTES', 120)) # Pega do .env ou usa 2 horas
    
    check_interval_seconds = 60 # Verifica a cada 1 minuto

    logging.info(f"Worker: Verificando Redis a cada {check_interval_seconds}s. Timeout de inatividade: {idle_timeout_minutes} min.")

    while True:
        if redis_client is None:
            logging.warning("Worker: Cliente Redis não está pronto. Tentando reconectar em init_worker.")
            sleep(check_interval_seconds) # Espera antes de verificar novamente
            continue # Pula para a próxima iteração

        try:
            waiting_requests = redis_client.hgetall(REDIS_NUMBERS_TIME_HASH_KEY)
            if not waiting_requests:
                sleep(check_interval_seconds)
                continue # Volta para o início do loop
            latest_request_time_str = None
            all_phone_numbers = []

            # Encontra o timestamp da solicitação mais recente
            for phone_number, timestamp in waiting_requests.items():
                all_phone_numbers.append(phone_number)
                if latest_request_time_str is None or timestamp > latest_request_time_str:
                    latest_request_time_str = timestamp
            
            if latest_request_time_str is None: 
                sleep(check_interval_seconds)
                continue

            latest_request_datetime = datetime.strptime(latest_request_time_str, '%Y-%m-%dT%H:%M:%S')
            now_str = datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%Y-%m-%dT%H:%M:%S')
            now_datetime = datetime.strptime(now_str, '%Y-%m-%dT%H:%M:%S')

            # Verifica se o tempo desde a última solicitação excedeu o timeout de inatividade
            if (now_datetime > latest_request_datetime + timedelta(minutes=idle_timeout_minutes)) or len(all_phone_numbers) >= 30:
                logging.info(f"Worker: Timeout de inatividade ({idle_timeout_minutes} min) atingido. Preparando para enviar mensagem.")
                
                time_now = datetime.now(pytz.timezone('America/Sao_Paulo'))
                
                if time_now.weekday() in [5, 6]: # Sábado ou Domingo:
                    if time_now.hour > 20 and time_now.hour < 8:
                        return
                else:
                    if time_now.time() > time(22, 30, 0) or time_now.hour < 8:
                        return
                
                greeting = 'Bom dia!' if time_now.hour < 12 else 'Boa tarde!' if time_now.hour < 18 else 'Boa noite!'
                
                # Ordena os números para consistência, se desejado
                all_phone_numbers.sort() 

                message_variables = [greeting, ', '.join(list(set(all_phone_numbers)))]

                logging.info(f"Worker: Enviando mensagem consolidada para {TRACKER_LINE_PROVIDER_NUMBER} com {len(all_phone_numbers)} números.")
                
                uuid, link_conversation, name = get_contact_uuid_by_phone(TRACKER_LINE_PROVIDER_NUMBER if time_now.hour < 19 else TRACKER_LINE_PROVIDER_NUMBER2)
                
                if uuid:
                    last_msg_time = get_last_message_time(uuid)
                    now_utc = datetime.now(timezone.utc)

                    if last_msg_time:
                        time_diff = now_utc - last_msg_time
                        
                        if time_diff.days < 1:
                            success = send_callbell_message(TRACKER_LINE_PROVIDER_NUMBER if time_now.hour < 19 else TRACKER_LINE_PROVIDER_NUMBER2, f"{greeting}\n\nPreciso que um reset de rede seja enviado para as seguintes linhas:\n\n{', '.join(list(set(all_phone_numbers)))}")
                            if success:
                                logging.info("Worker: Mensagem enviada com sucesso.")
                                redis_client.delete(REDIS_NUMBERS_TIME_HASH_KEY)
                            else:
                                logging.error("Worker: Falha ao enviar a mensagem para o provedor. As solicitações permanecerão no Redis para a próxima tentativa.")
                                
                        else:
                            success = send_callbell_template(TRACKER_LINE_PROVIDER_NUMBER if time_now.hour < 19 else TRACKER_LINE_PROVIDER_NUMBER2, message_variables, '6e748fa791a843daa938f75cd7eec1fb' if time_now.hour < 19 else 'b6b583e5da7e4c7ab7829e9f39aced7f')
                            if success:
                                logging.info("Worker: Mensagem enviada com sucesso.")
                                redis_client.delete(REDIS_NUMBERS_TIME_HASH_KEY)
                            else:
                                logging.error("Worker: Falha ao enviar a mensagem para o provedor. As solicitações permanecerão no Redis para a próxima tentativa.")
                                
                    else:
                        success = send_callbell_template(TRACKER_LINE_PROVIDER_NUMBER if time_now.hour < 19 else TRACKER_LINE_PROVIDER_NUMBER2, message_variables, '6e748fa791a843daa938f75cd7eec1fb' if time_now.hour < 19 else 'b6b583e5da7e4c7ab7829e9f39aced7f')
                        if success:
                            logging.info("Worker: Mensagem enviada com sucesso.")
                            redis_client.delete(REDIS_NUMBERS_TIME_HASH_KEY)
                        else:
                            logging.error("Worker: Falha ao enviar a mensagem para o provedor. As solicitações permanecerão no Redis para a próxima tentativa.")

                else:
                    success = send_callbell_template(TRACKER_LINE_PROVIDER_NUMBER if time_now.hour < 19 else TRACKER_LINE_PROVIDER_NUMBER2, message_variables, '6e748fa791a843daa938f75cd7eec1fb' if time_now.hour < 19 else 'b6b583e5da7e4c7ab7829e9f39aced7f')

                if success:
                    redis_client.delete(REDIS_NUMBERS_TIME_HASH_KEY)
                    logging.info(f"Worker: Mensagem enviada. Hash '{REDIS_NUMBERS_TIME_HASH_KEY}' removido do Redis.")
                else:
                    logging.error("Worker: Falha ao enviar a mensagem para o provedor. As solicitações permanecerão no Redis para a próxima tentativa.")

        except redis.exceptions.RedisError as e:
            logging.error(f"Worker: Erro de Redis no loop de verificação: {e}")
        except Exception as e:
            logging.error(f"Worker: Erro inesperado no loop de verificação: {e}")
        
        sleep(check_interval_seconds)


def init_worker():
    """
    Inicializa a conexão com o Redis e inicia a thread do worker.
    """
    global redis_client

    # Tenta conectar ao Redis com backoff exponencial
    max_retries = 10
    base_backoff_seconds = 2 # Começa com 2 segundos

    for attempt in range(max_retries):
        try:
            # decode_responses=True faz com que o cliente Redis retorne strings em vez de bytes
            redis_client_candidate = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD, decode_responses=True)
            redis_client_candidate.ping() # Testa a conexão
            redis_client = redis_client_candidate # Atribui à global se bem-sucedido
            logging.info(f"Conectado ao Redis em {REDIS_HOST}:{REDIS_PORT} na tentativa {attempt + 1}.")
            break # Sai do loop se conectado
        except redis.exceptions.ConnectionError as e:
            logging.error(f"Tentativa {attempt + 1} de conectar ao Redis falhou: {e}")
            if attempt < max_retries - 1:
                sleep_time = base_backoff_seconds * (2 ** attempt) # Backoff exponencial
                logging.info(f"Tentando novamente em {sleep_time} segundos...")
                sleep(sleep_time)
            else:
                logging.critical("Não foi possível conectar ao Redis após várias tentativas. O worker não será iniciado.")
                return # Não inicia a thread se não conseguir conectar

    if redis_client is None:
        logging.error("Worker não iniciado devido à falha na conexão com o Redis.")
        return

    worker_thread = threading.Thread(
        target=verify_redis,
        daemon=True
    )
    worker_thread.start()
    logging.info("Thread do worker iniciada.")

# Exemplo de como usar:
if __name__ == '__main__':
    # Verifica se as variáveis de ambiente essenciais estão configuradas
    if not CALLBELL_API_KEY:
        logging.critical("CALLBELL_API_KEY não está definido no arquivo .env. O programa não pode continuar.")
        exit(1)
    if not TRACKER_LINE_PROVIDER_NUMBER:
        logging.critical("TRACKER_LINE_PROVIDER_NUMBER não está definido no arquivo .env. O programa não pode continuar.")
        exit(1)

    # 1. Inicializa o worker (conecta ao Redis e inicia a thread de verificação)
    init_worker()

    # Simulação de chegada de solicitações de reset
    if redis_client: # Verifica se a conexão com o Redis foi bem-sucedida
        logging.info("Simulando o recebimento de solicitações de reset...")
        try:
            # solicitar_envio("5517936344805")
            # sleep(10) # Simula um pequeno intervalo entre as solicitações
            # solicitar_envio("5511900000002")
            # sleep(15)
            # solicitar_envio("5511900000003")
            
            logging.info("Solicitações de exemplo adicionadas. O worker processará em segundo plano.")
            logging.info(f"Aguarde aproximadamente {os.getenv('IDLE_TIMEOUT_MINUTES', 5)} minutos de inatividade para o envio.")

            while True:
                sleep(180) # Mantém o script principal vivo

        except KeyboardInterrupt:
            logging.info("Programa interrompido pelo usuário.")
        finally:
            logging.info("Encerrando o programa.")
    else:
        logging.error("Não foi possível iniciar a simulação pois a conexão com o Redis falhou.")

