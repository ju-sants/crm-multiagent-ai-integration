from app.core.logger import get_logger

import requests

from time import sleep

logger = get_logger()


def send_telegram_report(report_lines: list, chat_id: str, job_name: str):
    if not chat_id:
        logger.warning("TELEGRAM_CHAT_ID não configurado. Não é possível enviar o relatório.")
        return

    report_header = f"<b>Relatório de Execução do Job: {job_name}</b>\n\n"
    full_message = report_header + "\n\n".join(report_lines)
    
    max_length = 4000 # Deixando uma margem
    message_parts = [full_message[i:i + max_length] for i in range(0, len(full_message), max_length)]

    success = True
    for part in message_parts:
        if not send_single_telegram_message(part, chat_id):
            success = False
            break 
    
    if success:
        logger.info(f"Relatório do job '{job_name}' enviado com sucesso para o Telegram.")
    else:
        logger.error(f"Falha ao enviar o relatório completo do job '{job_name}' para o Telegram.")


def send_single_telegram_message(message_part: str, chat_id: str) -> bool:
    """Envia uma única parte da mensagem para um chat_id."""
    if not message_part or not message_part.strip():
        logger.debug(f"Ignorando envio de mensagem vazia para {chat_id}")
        return True

    payload = {'message': message_part}
    url = f'https://web-production-493b.up.railway.app/sendMessage?chat_id={chat_id}&parse_mode=HTML'
    max_retries = 2
    delay = 2

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(url, json=payload, timeout=20)

            if response.status_code == 200:
                logger.debug(f"Parte da mensagem enviada com sucesso para {chat_id}.")
                return True
            else:
                logger.error(f"Falha ao enviar parte da mensagem para {chat_id}. Status: {response.status_code}, Resposta: {response.text}. Tentativa {attempt + 1} de {max_retries + 1}.")
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro de requisição ao enviar parte da mensagem para {chat_id}: {e}. Tentativa {attempt + 1} de {max_retries + 1}.")
        
        if attempt < max_retries:
            sleep(delay)
    
    logger.error(f"Falha ao enviar parte da mensagem para {chat_id} após {max_retries + 1} tentativas.")
    return False