from app.core.logger import get_logger

from app.utils.funcs.reset_integration.reset_SMS import reset_eseye, reset_sms
from app.utils.funcs.reset_integration.reset_rede.plataforma_vivo_REST import main as reset_rede_VIVO
from app.utils.funcs.reset_integration.reset_rede.plataforma_VS import main as reset_rede_VS
from app.utils.funcs.reset_integration.reset_rede.plataforma_allcom import main as reset_rede_ALLCOM
from app.utils.funcs.reset_integration.reset_rede.plataforma_veye import main as reset_rede_VEYE
from app.utils.funcs.reset_integration.reset_rede.plataforma_LINK import main as reset_rede_LINK
from app.utils.funcs.reset_integration.reset_rede.plataforma_ESEYE import main as reset_rede_ESEYE
from app.utils.funcs.reset_integration.reset_rede.plataforma_LINKSFIELD import solicitar_envio

from app.utils.funcs.funcs import *

import requests

logger = get_logger(__name__)

session = requests.Session()
    
def process_reset_sending(vehicle_data):
    """Action for initial GSM failure (e.g., send reset SMS)."""
    id_vehicle = vehicle_data.get('id')
    tracker_id = int(vehicle_data.get('tracker_id'))
    recipient = vehicle_data.get('chip_number')
    fabricante = vehicle_data.get('manufacturer_id')
    observation = vehicle_data.get('observation')

    if not recipient:
        return "Nenhum número de telefone encontrado. Crucial para o envio do comando de reset."
    if not fabricante:
        return "Nenhum fabricante encontrado. Crucial para identificar o comando de reset correto."
    if not tracker_id:
        return "ID do rastreador não encontrado. Crucial para compor o comando de reset."
    if not observation:
        return "Nenhuma observação encontrada. É crucial para identificar o provedor do chip para identificar o procedimento de network reset correto."
    
    resets_sent = ["SMS", "NETWORK"]
    resets_not_sent = []

    message = "Tracker reset successfully."
    try:
        logger.info(f"Processing tracker {tracker_id}.")

        command = None
        if fabricante == 1:
            tam_id = len(str(tracker_id))
            command = "SA200CMD;" if tam_id <= 6 else 'ST300CMD;'
            command += f'{tracker_id:06}' if tam_id <= 6 else f'{tracker_id:09}'
            command += ';02;Reboot'

        elif fabricante == 18:
            try:
                tracker_id = vehicle_data.get('imei', '')

                command = f'CMD;{tracker_id};03;03'

            except Exception as e:
                logger.error(f"Error retrieving vehicle details for id {id_vehicle}: {e}")

        elif fabricante == 2:
            command = 'RESET#'

        elif fabricante == 9:
            command = 'reset123456'

        elif fabricante == 15:
            command = 'AT+XRST=0;+XRST=1;+XRST=2;+XRST=3;+XRST=4'

        if command and recipient:
            recipient_sanitized = sanitize_tel(recipient)
            fornecedora = qual_fornecedora(observation)

            # 1: SMS RESET
            if recipient_sanitized:
                is_eseye = (fornecedora == 'ESEYE')

                if not is_eseye:
                    try:
                        logger.info(f'Sending SMS reset command to {recipient_sanitized} for tracker {tracker_id}. Command: {command}')
                        reset_sms(recipient_sanitized, command)

                    except Exception as e:
                        logger.error(f"Error sending SMS reset command: {e}")
                        resets_not_sent.append(resets_sent.pop(resets_sent.index("SMS")))

                else:
                    try:
                        logger.info(f'Sending ESEYE reset for tracker {tracker_id} to {recipient_sanitized}. Command: {command}')
                        reset_eseye(recipient_sanitized, command, session)
                    except Exception as e:
                        logger.error(f"Error sending ESEYE reset command: {e}")
                        resets_not_sent.append(resets_sent.pop(resets_sent.index("SMS")))



            else:
                logger.warning(f"Invalid recipient phone number format for initial SMS: {recipient}")

            # NETWORK RESET
            try:
                if fornecedora == 'ALLCOM':
                    logger.info(f'Resetting network for ALLCOM (tracker {tracker_id}) using recipient: 55{recipient}')
                    reset_rede_ALLCOM(f'55{recipient}', session, logger)

                elif fornecedora == 'ESEYE':
                    logger.info(f'Resetting network for ESEYE (tracker {tracker_id})')
                    reset_rede_ESEYE(f'55{recipient}', logger, session)

                elif fornecedora == 'LINK':
                    logger.info(f'Resetting network for LINK (tracker {tracker_id}) using recipient: 55{recipient}')
                    reset_rede_LINK(session, f'55{recipient}', logger)

                elif fornecedora == 'LINKS':
                    logger.info(f'Resetting network for LINKS (tracker {tracker_id})')
                    solicitar_envio(f'55{recipient}')

                elif fornecedora == 'VEYE':
                    logger.info(f'Resetting network for VEYE (tracker {tracker_id}) using recipient: {recipient}')

                    recipient_regularized = padronizar_telefone(recipient)
                    if recipient_regularized is None:
                        logger.error(f"Invalid phone number format for VEYE: {recipient}")
                        return
                    
                    reset_rede_VEYE(recipient_regularized, session)

                elif fornecedora == 'VIVO':
                    logger.info(f'Resetting network for VIVO (tracker {tracker_id}) using recipient: {recipient}')
                    reset_rede_VIVO(f'55{recipient}', logger)

                elif fornecedora == 'VS':
                    logger.info(f'Resetting network for VS (tracker {tracker_id}) using recipient: {recipient}')
                    reset_rede_VS(f'55{recipient}', session)

                else:
                    logger.warning(f'Unknown provider "{fornecedora}" for tracker {tracker_id}. No reset action taken.')

            except Exception as e:
                logger.error(f"Error during network reset: {e}")
                resets_sent.remove("NETWORK")

        else:
            logger.error(f"No command or recipient for tracker {tracker_id}. Reset action not performed.")
            message = f"Tracker {tracker_id} reset failed. No command or recipient."

    except Exception as e:
        logger.error(f"Unexpected error in process_initial_failure_GSM: {e}", exc_info=True)
        return {"status": "error", "message": f"Error processing tracker {tracker_id}: {e}", "vehicle_details": {"tracker_id": tracker_id, "plate": vehicle_data.get('license_plate', 'N/A'), "model": vehicle_data.get('model', 'N/A'), "owner": vehicle_data.get('owner', {}).get('name', 'N/A')}}
    
    else:
        if resets_not_sent:
            message += "\nSome resets were not sent, you can try again if wanted"
        logger.info(f"Tracker {tracker_id} reset successfully.")
        return {"status": "success", "message": message, "resets_sent": resets_sent, "resets_not_sent": resets_not_sent, "vehicle_details": {"tracker_id": tracker_id, "plate": vehicle_data.get('license_plate', 'N/A'), "model": vehicle_data.get('model', 'N/A'), "owner": vehicle_data.get('owner', {}).get('name', 'N/A')}}