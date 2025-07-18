import requests
import json
import logging


BASE_URL = settings.VEYE_BASE_URL

# --- 1. Authorization (Login) ---
def authorize(username, password, session, logger):
    """Logs in the user and returns the authentication token."""
    login_endpoint = f"{BASE_URL}/clienteAPI/login"
    payload = {
        "login": username,
        "senha": password
    }

    headers = {
        'Content-Type': 'application/json'
    }
    try:
        response = session.post(login_endpoint, headers=headers, json=payload)
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

        # Assuming the token is in the response JSON body, e.g., under a key like 'token' or 'access_token'
        # Adjust the key based on the actual API response structure.
        token = response.json().get('conteudo').get("token")
        logger.info("Authorization successful.")
        return token
    except requests.exceptions.RequestException as e:
        logger.error(f"Login failed: {e}")
        if 'response' in locals():
            logger.error(f"Response status: {response.status_code}")
            try:
                logger.error(f"Response body: {response.json()}")
            except json.JSONDecodeError:
                logger.error(f"Response body: {response.text}")
        return None

# --- 2. Send Reset Request ---
def send_reset(token, msisdn, technology, session, logger):
    """Sends a reset request for a given MSISDN."""
    if not token:
        logger.error("Cannot send reset: No valid token provided.")
        return False

    reset_endpoint = f"{BASE_URL}/clienteAPI/autenticado/{msisdn}/reset" # Corrected based on [cite: 2] structure
    headers = {
        'Authorization': f'Bearer {token}', # Assuming Bearer token authentication
        'Content-Type': 'application/json',
        'accept': '*/*'
    }

    payload = {
        "tecnologia": technology
    }

    try:
        # The Swagger doc [cite: 2] indicates a POST request for reset.
        response = session.put(reset_endpoint, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"Reset request sent successfully for MSISDN: {msisdn}")
        # Check response content if needed, based on API documentation
        logger.info(f"Reset response: {response.json()}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Reset request failed: {e}")
        if 'response' in locals():
            logger.error(f"Response status: {response.status_code}")
            try:
                logger.error(f"Response body: {response.json()}")
            except json.JSONDecodeError:
                logger.error(f"Response body: {response.text}")
        return False

# --- 3. De-authentication (Logout) ---
def deauthenticate(token, session, logger):
    """Logs out the user."""
    if not token:
        logger.error("Cannot logout: No valid token provided.")
        return False

    logout_endpoint = f"{BASE_URL}/clienteAPI/logout"
    headers = {
        'Authorization': f'Bearer {token}' # Logout might also require the token
    }
    try:
        # Assuming POST for logout as well, although GET could also be used. Check API spec. [cite: 1] shows POST.
        response = session.post(logout_endpoint, headers=headers)
        response.raise_for_status()
        logger.info("Logout successful.")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Logout failed: {e}")
        if 'response' in locals():
            logger.error(f"Response status: {response.status_code}")
            try:
                logger.error(f"Response body: {response.json()}")
            except json.JSONDecodeError:
                logger.error(f"Response body: {response.text}")
        return False

def main(recipient, session):
    try:
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)

        # Replace with actual credentials and data
        user_login = settings.VEYE_LOGIN
        user_password = settings.VEYE_PASSWORD
        target_msisdn = recipient
        sim_technology = "4G"

        logger.info("Starting API flow...")

        # 1. Authorize
        auth_token = authorize(user_login, user_password, session, logger)

        if auth_token:
            # 2. Send Reset
            reset_success = send_reset(auth_token, target_msisdn, sim_technology, session, logger)

        else:
            logger.error("Aborting flow due to authorization failure.")

        logger.info("API flow finished.")
    except Exception as e:
        logger.error(f"Houve um erro não tratado na execução de reset de rede para o telefone {recipient}. {e}")

# --- Example Usage ---
if __name__ == "__main__":
    main("5551980385792", requests.Session())
