from elevenlabs import ElevenLabs, VoiceSettings
from typing import List
import requests
from datetime import datetime
import re

from app.config.settings import settings
from app.utils.funcs.normalize_text_tts import apply_normalizations
from app.services.cache_service import cache_result

def host_audio(audio_bytes: bytes):
    audio_name = f'audio_eleven_agent_AI_{datetime.now().strftime("%Y%m%d%H%M%S")}.mp3'
    headers = {'filename': audio_name}
    response_hosting = requests.post('https://api-data-automa-system-production.up.railway.app/upload_doc?path=docs&ex=3', headers=headers, data=audio_bytes)

    if response_hosting.status_code == 200:
        return f'https://api-data-automa-system-production.up.railway.app/download_doc/{audio_name}?path=docs&mimetype=mp3'
    else:
        return None
    
    
@cache_result(ttl=86400)  # Cache for 24 hours
def get_audio_bytes(messages: List[str]):
    messages_str = '\n'.join(messages)

    messages_normalized = apply_normalizations(messages_str)

    voice_settings = VoiceSettings(
            stability=0.71,
            similarity_boost=0.5,
            style=0.0,
            use_speaker_boost=True,
            speed=1.2
        )

    eleven_labs = ElevenLabs(api_key=settings.ELEVEN_LABS_API_KEY)
    audio = eleven_labs.text_to_speech.convert(
                text=messages_normalized,
                model_id='eleven_multilingual_v2',
                output_format='mp3_22050_32',
                voice_id='CstacWqMhJQlnfLPxRG4',
                voice_settings=voice_settings
                )

    audio_bytes = b''.join(audio)

    return audio_bytes

def main(messages: List[str]):
    
    audio_bytes = get_audio_bytes(messages)

    hosted_url = host_audio(audio_bytes)
    
    return hosted_url