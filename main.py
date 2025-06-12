from flask import Flask, jsonify, request
import json
import requests
import threading

import os
from time import sleep
import datetime

import logging


from app.core.logger import get_logger
from app.crews.conversation_crew import run_mvp_crew, run_mvp_crew_2
from app.config.settings import settings
from app.services.redis_service import get_redis
from app.services.transcript_service import transcript
from app.services.image_describer_service import ImageDescriptionAPI

CALLBELL_API_KEY = os.environ.get("CALLBELL_API_KEY", "test_gshuPaZoeEG6ovbc8M79w0QyM")
CALLBELL_API_BASE_URL = "https://api.callbell.eu/v1"
IMAGE_EXTENSIONS = ['.png', '.jpg', '.gif', '.webp', '.jpeg']


app = Flask(__name__)
redis_client = get_redis()
redis_client.delete(f'processing:71464be80c504971ae263d710b39dd1f')
print(redis_client.hgetall("71464be80c504971ae263d710b39dd1f:attachments"))

client_description = ImageDescriptionAPI(settings.APPID_IMAGE_DESCRIPTION, settings.SECRET_IMAGE_DESCRIPTION)
logger:  logging.Logger = get_logger(__name__)

def get_callbell_headers():
    """Retorna os headers padrão para as requisições Callbell."""
    return {
        'Authorization': f'Bearer {CALLBELL_API_KEY}',
        'Content-Type': 'application/json',
    }

def send_callbell_message(phone_number, text):
    """Envia uma mensagem de texto simples via Callbell."""
    url = f"{CALLBELL_API_BASE_URL}/messages/send"
    payload = {
        'to': phone_number,
        'from': 'whatsapp',
        'type': 'text',
        'content': {'text': text},
    }
    logger.info(f"Enviando mensagem simples para {phone_number}: {text}")
    try:
        response = requests.post(url, headers=get_callbell_headers(), json=payload)
        response.raise_for_status()
        logger.info(f"Mensagem simples enviada com sucesso para {phone_number}.")
        return True
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao enviar mensagem simples para {phone_number}: {e}")
        logger.error(f"Payload enviado: {json.dumps(payload)}")
        logger.error(f"Resposta recebida (se houver): {e.response.status_code} - {e.response.text if e.response else 'N/A'}")
        return False
    
    except Exception as e:
        logger.error(f"Erro inesperado ao processar envio de mensagem simples para {phone_number}: {e}")
        return False

def get_allowed_chats():
    return [
        '71464be80c504971ae263d710b39dd1f', # Juan
        # '2fa9529f9c1e4ed9b8ddea6c6a4272e8', # valdir ou ana paula
        # '7b337e574d63473ba0aba7e7de543a48', # valdir ou ana paula
        # 'd3c9a42068b44b47bfbf6fc8adf62f71', # deibisson empresa
        # 'e426520a46f54bbeb5b98a76e95b1bbb', # cristiane
        # 'ff1b97c206e544f89127600a1a074d27', # aila
        # '8544e093bcdd4f47bb3a5d7da1ac1ad7', # jenifer
        # '7fee5fb4c62d41f98e027e86f57c16c8', # deibisson pessoal
        # 'acfe198b10254da0b8c6f1b46df07c94', # Roberta
        # 'ecad1a70b0004d7580398f96f8074489' # Gisele
        ]

def process_requisitions(payload):
    logger.info(f'[{payload.get("uuid", "N/A")}] - INICIANDO process_requisitions para payload: {payload.get("uuid", "N/A")} de {payload.get("from", "N/A")}')

    contact_info = payload.get("contact")
    if not contact_info:
        logger.error(f'[{payload.get("uuid", "N/A")}] - ERRO: Informações de contato não encontradas no payload.')
        return

    contact_uuid = contact_info.get("uuid")
    phone_number = str(contact_info.get("phoneNumber", "")).replace('+', '')
    logger.info(f'[{contact_uuid}] - Extraídas informações do contato: UUID={contact_uuid}, Telefone={phone_number}')

    allowed_chats = get_allowed_chats()
    logger.info(f'[{contact_uuid}] - Chats permitidos carregados.')

    if contact_uuid in allowed_chats:
        logger.info(f'[{contact_uuid}] - Contato {contact_uuid} ENCONTRADO na lista de chats permitidos.')
        
        text = str(payload.get('text', ''))
        text = '' if text == 'None' else text
        
        content = payload.get('attachments', [])
        logger.info(f'[{contact_uuid}] - Texto inicial: "{text}", Anexos encontrados: {len(content)}')

        content_audio = [attach for attach in content if '.mp3' in attach]
        logger.info(f'[{contact_uuid}] - Áudios identificados ({len(content_audio)}): {content_audio}')

        content_image = [attach for attach in content if any([extension in attach for extension in IMAGE_EXTENSIONS])]
        logger.info(f'[{contact_uuid}] - Imagens identificadas ({len(content_image)}): {content_image}')

        transcription = None
        if content_audio:
            try:
                url = content_audio[0]
                logger.info(f'[{contact_uuid}] - Iniciando transcrição de áudio para {len(content_audio)} anexos.')
                transcription = transcript(url)
                if transcription:
                    logger.info(f'[{contact_uuid}] - Transcrição de áudio CONCLUÍDA. Conteúdo: "{transcription[:50]}..."')
                    logger.info(f'[{contact_uuid}] - Adicionando transcrição de áudio ao texto final.')
                    text += f'\n{transcription}'

                    static_url_part = url.split('uploads/')[1].split('?')[0]
                    redis_client.hset(f'{contact_uuid}:attachments', static_url_part, transcription)
                else:
                    logger.warning(f'[{contact_uuid}] - Transcrição de áudio RETORNOU VAZIO.')
            except Exception as e:
                logger.error(f'[{contact_uuid}] - ERRO durante a transcrição de áudio: {e}', exc_info=True)
                transcription = None

        for attach in content_image:
            logger.info(f'[{contact_uuid}] - Processando imagem: {attach}')
            description = None
            try:
                description_json = client_description.describe_image(image_url=attach)
                description = description_json.get('data', {}).get('content')
                if description:
                    logger.info(f'[{contact_uuid}] - Descrição da imagem obtida. Adicionando ao texto.')
                    text += f'\n\n(SISTEMA): O CLIENTE MANDOU UMA IMAGEM QUE FOI DESCRITA POR UMA IA:\n\n{description}\nFIM DA DESCRIÇÃO DE IMAGEM.'

                    static_url_part = attach.split('uploads/')[1].split('?')[0]
                    redis_client.hset(f'{contact_uuid}:attachments', static_url_part, description)
                else:
                    logger.warning(f'[{contact_uuid}] - Descrição da imagem VAZIA para {attach}.')
            except Exception as e:
                logger.error(f'[{contact_uuid}] - ERRO ao descrever imagem {attach}: {e}', exc_info=True)
            

        logger.info(f'[{contact_uuid}] - Texto FINAL a ser salvo no Redis: "{text[:100]}..."')
        try:
            redis_client.rpush(f'contacts_messages:waiting:{contact_uuid}', text)
            logger.info(f'[{contact_uuid}] - Texto adicionado à fila Redis "contacts_messages:waiting:{contact_uuid}".')
        except Exception as e:
            logger.error(f'[{contact_uuid}] - ERRO ao adicionar texto ao Redis: {e}', exc_info=True)
            return

        try:
            messages_before = redis_client.lrange(f'contacts_messages:waiting:{contact_uuid}', 0, -1)
            logger.info(f'[{contact_uuid}] - Mensagens ANTES do sleep no Redis: {len(messages_before)} itens.')
        except Exception as e:
            logger.error(f'[{contact_uuid}] - ERRO ao obter messages_before do Redis: {e}', exc_info=True)
            messages_before = []

        logger.info(f'[{contact_uuid}] - Iniciando sleep de 4 segundos para agregação de mensagens.')
        sleep(4)
        logger.info(f'[{contact_uuid}] - Sleep concluído.')

        try:
            messages_after = redis_client.lrange(f'contacts_messages:waiting:{contact_uuid}', 0, -1)
            logger.info(f'[{contact_uuid}] - Mensagens DEPOIS do sleep no Redis: {len(messages_after)} itens.')
        except Exception as e:
            logger.error(f'[{contact_uuid}] - ERRO ao obter messages_after do Redis: {e}', exc_info=True)
            messages_after = []

        if messages_after == messages_before:
            logger.info(f'[{contact_uuid}] - NENHUMA nova mensagem chegou durante o período de espera. Tentando obter lock de processamento.')

            contact_lock = None
            # if contact_uuid == "71464be80c504971ae263d710b39dd1f":
            #     redis_client.delete(f'state:{contact_uuid}')
            #     redis_client.delete(f"{contact_uuid}:customer_profile")
            #     redis_client.delete(f"contact:{contact_uuid}")
                
            try:
                contact_lock = redis_client.set(f'processing:{contact_uuid}', value='1', nx=True, ex=300)
                logger.info(f'[{contact_uuid}] - Tentativa de obter lock "processing:{contact_uuid}" com resultado: {contact_lock}.')
            except Exception as e:
                logger.error(f'[{contact_uuid}] - ERRO ao tentar obter lock no Redis: {e}', exc_info=True)

            if contact_lock:
                logger.info(f'[{contact_uuid}] - Lock de processamento OBTIDO com sucesso.')
                try:
                    logger.info(f'[{contact_uuid}] - Buscando histórico de mensagens na Callbell API.')
                    headers = {
                        "Authorization": f"Bearer {settings.CALLBELL_API_KEY}",
                        "Content-Type": "application/json"
                    }
                    history_response = requests.get(f'https://api.callbell.eu/v1/contacts/{contact_uuid}/messages', headers=headers)
                    history_response.raise_for_status()
                    history = history_response.json()
                    logger.info(f'[{contact_uuid}] - Histórico da Callbell obtido (status {history_response.status_code}). Total de mensagens no histórico: {len(history)}')

                    run_mvp_crew_2(contact_uuid, phone_number, redis_client, history)
                    logger.info(f'[{contact_uuid}] - CHAMADA da função run_mvp_crew (comentada no código).')

                except requests.exceptions.RequestException as e:
                    logger.error(f'[{contact_uuid}] - ERRO de requisição HTTP ao obter histórico da Callbell: {e}', exc_info=True)
                except Exception as e:
                    logger.error(f'[{contact_uuid}] - ERRO INESPERADO ao processar a mensagem do contato {contact_uuid}. Erro:\n\n{e}', exc_info=True)
                finally:
                    logger.info(f'[{contact_uuid}] - Bloco try/except/finally da lógica principal CONCLUÍDO. Tentando liberar lock.')
                    tries = 1
                    while True:
                        if tries > 5:
                            logger.error(f'[{contact_uuid}] - Não foi possível liberar o lock "processing:{contact_uuid}" após 5 tentativas. Possível lock órfão.')
                            break
                        
                        try:
                            redis_client.delete(f'processing:{contact_uuid}')
                            logger.info(f'[{contact_uuid}] - Lock "processing:{contact_uuid}" LIBERADO no Redis.')
                            break
                        except Exception as e:
                            logger.error(f'[{contact_uuid}] - Ocorreu um erro ao tentar liberar o lock (tentativa {tries}/5): {e}', exc_info=True)
                            tries += 1
                            sleep(1)
            else:
                logger.warning(f'[{contact_uuid}] - Não foi possível obter o lock "processing:{contact_uuid}". Outro processo já está processando ou o lock já existe.')
        else:
            logger.info(f'[{contact_uuid}] - NOVAS mensagens chegaram durante o período de espera. A tarefa atual será ignorada para evitar processamento duplicado/concorrência. As novas mensagens serão processadas por uma nova execução da tarefa.')
    else:
        logger.info(f'[{contact_uuid}] - Contato {contact_uuid} NÃO ENCONTRADO na lista de chats permitidos. Ignorando processamento.')

    logger.info(f'[{payload.get("uuid", "N/A")}] - FINALIZANDO process_requisitions para payload: {payload.get("uuid", "N/A")}.')


                        
@app.route('/receive_message', methods=['POST'])
def receive_message():
    webhook_payload = request.get_json()
    print(webhook_payload)
    if not webhook_payload:
        logger.info("Webhook: Payload vazio recebido.")
        return jsonify({"status": "ok", "message": "Empty payload"}), 200

    event = webhook_payload.get("event")
    payload = webhook_payload.get("payload")
    logger.debug(f"Webhook recebido: Evento='{event}' Payload='{json.dumps(payload, indent=4)}'") # Log detalhado
    logger.info('recebida uma mensagem via webhook')

    # --- Processamento de Mensagens Recebidas ---
    if event == "message_created" and payload and payload.get("status") == "received":

        contact_info = payload.get("contact")

        if not contact_info or not contact_info.get("uuid"):
            logger.warning("Webhook: Mensagem recebida sem 'contact.uuid'. Ignorando.")
            return jsonify({"status": "ok", "message": "No contact UUID"}), 200

        thread = threading.Thread(
            target=process_requisitions,
            args=(payload,),
            daemon=True
        )
        
        thread.start()
                
    return jsonify({'status': 'ok'}), 200


if __name__ == '__main__':
    app.run('0.0.0.0', port=8080)