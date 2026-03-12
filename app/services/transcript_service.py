import hashlib
import json
import time
import requests
from app.config.settings import settings
from app.services.redis_service import get_redis
from app.core.logger import get_logger

logger = get_logger(__name__)

TRANSCRIPTION_POLL_INTERVAL = 2  # seconds between Gladia status checks
TRANSCRIPTION_TIMEOUT = 120  # max seconds to wait for transcription

def transcript(attach):
    redis_conn = get_redis()
    cache_key = None

    try:
        audio_bytes = requests.get(attach, timeout=30).content
        content_hash = hashlib.sha256(audio_bytes).hexdigest()
        cache_key = f"transcript:{content_hash}"

        cached_result = redis_conn.get(cache_key)
        if cached_result:
            logger.info(f"Cache hit for key: {cache_key}")
            return json.loads(cached_result)

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch audio from URL: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during cache check: {e}")

    logger.info(f"Cache miss{f' for key: {cache_key}' if cache_key else ''}. Executing transcription.")

    headers = {
        'x-gladia-key': settings.X_GLADIA_KEY,
        'Content-Type': 'application/json'
    }
    
    payload = {
        "audio_url": attach,
        "language_config": {
            "languages": ["pt"]
        }
    }
    
    response_initiate = requests.post('https://api.gladia.io/v2/pre-recorded', headers=headers, json=payload, timeout=30)
    transcription_id = response_initiate.json().get('id')
    
    elapsed = 0
    response_transcript = None
    while elapsed < TRANSCRIPTION_TIMEOUT:
        time.sleep(TRANSCRIPTION_POLL_INTERVAL)
        elapsed += TRANSCRIPTION_POLL_INTERVAL
        response_transcript = requests.get(f'https://api.gladia.io/v2/pre-recorded/{transcription_id}', headers=headers, timeout=30).json()
        if response_transcript.get('status', '') == "done":
            break
    else:
        logger.error(f"Transcription timed out after {TRANSCRIPTION_TIMEOUT}s for {attach}")
        return None

    transcript_text = response_transcript.get('result', {}).get('transcription', {}).get('full_transcript', '')
    text = f'\n{transcript_text}'
            
    try:
        if cache_key:
            redis_conn.setex(cache_key, 86400, json.dumps(text))
    except Exception as e:
        logger.error(f"Failed to write to cache: {e}")

    return text