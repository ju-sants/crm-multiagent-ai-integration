import requests
import json
import logging

def parse_services_to_msisdn_keys(json_data, logger):
    """
    Parses the input JSON data, transforming pipe-separated service strings
    into a dictionary keyed by MSISDN for each operator. Excludes non-service
    information like 'stats', 'currency', etc.

    Args:
        json_data (dict): The original JSON data loaded as a Python dictionary.

    Returns:
        dict: A new dictionary where each operator maps to a dictionary
              keyed by MSISDN, with each value being the parsed service data.
              Example: {"ALGAR": {"5516998353369": {...service_data...}}}
    """
    parsed_data = {}
    msisdn_key_name_original = "MSISDN" # The exact name in the 'syntax' string

    for operator, data in json_data.items():
        msisdn_keyed_services = {}
        syntax_keys = []
        msisdn_index = -1

        if "syntax" in data:
            syntax_keys = data["syntax"].split('|')
            # Find the index of the MSISDN field in the syntax
            try:
                # Find the original key name first
                msisdn_index = syntax_keys.index(msisdn_key_name_original)
            except ValueError:
                # Fallback if the original name isn't found (shouldn't happen based on input)
                logger.warning(f"'{msisdn_key_name_original}' not found in syntax for operator {operator}")
                msisdn_index = -1 # Indicate not found

        cleaned_msisdn_key = msisdn_key_name_original.replace(' ', '_').replace('/', '_').lower()

        for key, value in data.items():
            # Only process keys that represent service data
            if key.startswith("service_") and msisdn_index != -1:
                service_values = value.split('|')
                service_dict = {}

                # Create the service dictionary with cleaned keys
                for i in range(min(len(syntax_keys), len(service_values))):
                    clean_key = syntax_keys[i].replace(' ', '_').replace('/', '_').lower()
                    service_dict[clean_key] = service_values[i] if service_values[i] else None

                # Get the MSISDN value using the determined index or cleaned key name
                msisdn_value = None
                if 0 <= msisdn_index < len(service_values):
                    msisdn_value = service_values[msisdn_index]

                # If MSISDN is found and not empty, use it as the key
                if msisdn_value:
                    msisdn_keyed_services[msisdn_value] = service_dict
                else:
                    logger.warning(f"MSISDN not found or empty for {operator} -> {key}")

        # Only add the operator to the result if it has parsed services
        if msisdn_keyed_services:
            parsed_data[operator] = msisdn_keyed_services

    return parsed_data

def main(recipient, session):
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    LINHA = recipient

    json_login = {
        'Function': 'GetAllUsers',
        'output_type': 'json',
        'company': settings.VS_COMPANY,
        'na': 'no',
        'Admin': settings.VS_LOGIN,
        'AdminPwd': settings.VS_SENHA,
    }

    try:
        response_login = session.post('https://vendersolucoes.parlacom.net/cgi-bin/parla', data=json_login).json()
        sessionid = response_login.get('sessionid')

        all_sims_VS = session.get('https://api-data-production-35b8.up.railway.app/jsons/download/6').json()['data']

        if LINHA in all_sims_VS:
            iccid = all_sims_VS[LINHA]['iccid']
            linha = all_sims_VS[LINHA]['msisdn']
            pincarrier = all_sims_VS[LINHA]['operadora']

            json_reset = {
                'function': 'resetpincarrier',
                'output_type': 'json',
                'sessionid': sessionid,
                'login': settings.VS_LOGIN,
                'company': settings.VS_COMPANY,
                'pincarrier': pincarrier,
                'iccid': iccid,
                'group': '1',
                'serviceidtmp': f"{linha}/{iccid}/1",
            }

            response_reset = session.post('https://vendersolucoes.parlacom.net/cgi-bin/parla', data=json_reset)

            logger.info(response_reset.text)
            logger.info(f"Response status code: {response_reset.status_code}")

    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed: {e}")
        if 'response' in locals():
            logger.error(f"Response status: {response_reset.status_code}")
            try:
                logger.error(f"Response body: {response_reset.json()}")
            except json.JSONDecodeError:
                logger.error(f"Response body: {response_reset.text}")

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

if __name__ == '__main__':
    main("5583987504096", requests.Session())
