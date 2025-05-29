from flask import Flask, jsonify, request
import json
import requests

import logging
import os
from time import sleep

from app.crews.conversation_crew import run_mvp_crew
from app.config.settings import settings
from app.services.redis_service import get_redis


CALLBELL_API_KEY = os.environ.get("CALLBELL_API_KEY", "test_gshuPaZoeEG6ovbc8M79w0QyM")
CALLBELL_API_BASE_URL = "https://api.callbell.eu/v1"

app = Flask(__name__)
redis_client = get_redis()


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

def get_allowed_chats():
    return ['71464be80c504971ae263d710b39dd1f']


@app.route('/receive_message', methods=['POST'])
def receive_message():
    webhook_payload = request.get_json()
    print(webhook_payload)
    if not webhook_payload:
        logging.info("Webhook: Payload vazio recebido.")
        return jsonify({"status": "ok", "message": "Empty payload"}), 200

    event = webhook_payload.get("event")
    payload = webhook_payload.get("payload")
    logging.debug(f"Webhook recebido: Evento='{event}' Payload='{json.dumps(payload)}'") # Log detalhado
    logging.info('recebida uma mensagem via webhook')

    # --- Processamento de Mensagens Recebidas ---
    if event == "message_created" and payload and payload.get("status") == "received":

        contact_info = payload.get("contact")

        if not contact_info or not contact_info.get("uuid"):
            logging.warning("Webhook: Mensagem recebida sem 'contact.uuid'. Ignorando.")
            return jsonify({"status": "ok", "message": "No contact UUID"}), 200

        contact_uuid = contact_info.get("uuid")
        phone_number = contact_info.get("phoneNumber")
        
        allowed_chats = get_allowed_chats()
        
        if contact_uuid in allowed_chats:
            text = str(payload.get('text', ''))
            
            redis_client.rpush(f'contacts_messages:waiting:{contact_uuid}', text)
            
            messages_before = redis_client.lrange(f'contacts_messages:waiting:{contact_uuid}', 0, -1)
            
            sleep(3.5)
            
            messages_after = redis_client.lrange(f'contacts_messages:waiting:{contact_uuid}', 0, -1)
            
            if messages_after == messages_before:
                
                contact_lock = redis_client.set(f'processing:{contact_uuid}', value='1', nx=True)
                
                if contact_lock:
                    
                    try:
                        headers = {
                            "Authorization": f"Bearer {settings.CALLBELL_API_KEY}",
                            "Content-Type": "application/json"
                        }
                        
                        history = requests.get(f'https://api.callbell.eu/v1/contacts/{contact_uuid}/messages', headers=headers).json()
                        run_mvp_crew(contact_uuid, phone_number, redis_client, history)
                        
                    except Exception as e:
                        logging.error(f'Ocorreu um erro processando a mensagem do contato {contact_uuid}. Erro:\n\n{e}')
                    
                    finally:
                        
                        tries = 1
                        while True:
                            if tries > 5:
                                break
                            
                            try:
                                redis_client.delete(f'processing:{contact_uuid}')
                                
                            except Exception as e:
                                logging.error(f'Ocorreu um erro: {e}')
                                tries += 1
                                
                            else:
                                break
                
    return jsonify({'status': 'ok'}), 200