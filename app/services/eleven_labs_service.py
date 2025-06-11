from elevenlabs import ElevenLabs
from typing import List
import requests
from datetime import datetime

from app.config.settings import settings


def host_audio(audio_bytes: bytes):
    audio_name = f'audio_eleven_agent_AI_{datetime.now().strftime("%Y%m%d%H%M%S")}.mp3'
    headers = {'filename': audio_name}
    response_hosting = requests.post('https://api-data-automa-system-production.up.railway.app/upload_doc?path=docs&ex=3', headers=headers, data=audio_bytes)

    if response_hosting.status_code == 200:
        return f'https://api-data-automa-system-production.up.railway.app/download_doc/{audio_name}?path=docs&mimetype=mp3'
    else:
        return None


def main(messages: List[str]):
    messages_str = '\n'.join(messages)

    eleven_labs = ElevenLabs(api_key=settings.ELEVEN_LABS_API_KEY)
    audio = eleven_labs.text_to_speech.convert(
                text=messages_str,
                model_id='eleven_multilingual_v2',
                output_format='mp3_22050_32',
                voice_id='NQ10OlqJ7vYH6XwegHSW',
                request_options={
                    'voice_settings': {
                        'speed': 1.2,
                    }
                }
                )

    audio_bytes = b''.join(audio)

    hosted_url = host_audio(audio_bytes)
    
    return hosted_url