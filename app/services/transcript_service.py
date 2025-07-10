import hashlib
import json
import requests
from app.config.settings import settings
from app.services.redis_service import get_redis
from app.core.logger import get_logger

logger = get_logger(__name__)

def transcript(attach):
    redis_conn = get_redis()

    try:
        audio_bytes = requests.get(attach).content
        content_hash = hashlib.sha256(audio_bytes).hexdigest()
        cache_key = f"transcript:{content_hash}"

        cached_result = redis_conn.get(cache_key)
        if cached_result:
            logger.info(f"Cache hit for key: {cache_key}")
            return json.loads(cached_result)

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch audio from URL: {e}")
        # Proceed to Gladia if fetching fails, as it might be a transient issue
        pass
    except Exception as e:
        logger.error(f"An unexpected error occurred during cache check: {e}")
        pass

    logger.info(f"Cache miss for key: {cache_key}. Executing transcription.")

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
    
    response_initiate = requests.post('https://api.gladia.io/v2/pre-recorded', headers=headers, json=payload)
    id = response_initiate.json().get('id')
    
    while True:
        response_transcript = requests.get(f'https://api.gladia.io/v2/pre-recorded/{id}', headers=headers).json()
        
        if response_transcript.get('status', '') != "done":
            continue
        else:
            break
        

    transcript_text = response_transcript.get('result', {}).get('transcription', {}).get('full_transcript', '')
    text = f'\n{transcript_text}'
            
    try:
        redis_conn.setex(cache_key, 86400, json.dumps(text)) # Cache for 24 hours
    except Exception as e:
        logger.error(f"Failed to write to cache: {e}")

    return text