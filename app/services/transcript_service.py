from app.config.settings import settings
import requests


def transcript(content):
    text = ''
    for attach in content:
        if '.mp3' in attach:
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
                

            transcript = response_transcript.get('result', {}).get('transcription', {}).get('full_transcript', '')
            text += f'\n{transcript}'
            
    
    return text