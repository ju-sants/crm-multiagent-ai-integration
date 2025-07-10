import base64
import hmac
import hashlib
import time
import secrets
import requests
import json
from typing import Optional, Tuple
from app.services.redis_service import get_redis
from app.core.logger import get_logger

logger = get_logger(__name__)

class ImageDescriptionAPI:
    def __init__(self, appid: str, secret: str):
        self.appid = appid
        self.secret = secret
        self.base_url = "https://imagedescriber.online/api/openapi/describe-image"
    
    def load_image_from_file(self, file_path: str) -> Tuple[str, bytes]:
        """Carrega imagem de arquivo e converte para base64"""
        try:
            with open(file_path, 'rb') as file:
                image_data = file.read()
                base64_image = base64.b64encode(image_data).decode('utf-8')
                
                # Detectar tipo MIME baseado na extensão
                if file_path.lower().endswith('.png'):
                    mime_type = 'image/png'
                elif file_path.lower().endswith('.jpg') or file_path.lower().endswith('.jpeg'):
                    mime_type = 'image/jpeg'
                elif file_path.lower().endswith('.gif'):
                    mime_type = 'image/gif'
                elif file_path.lower().endswith('.webp'):
                    mime_type = 'image/webp'
                else:
                    mime_type = 'image/jpeg'
                
                return f"data:{mime_type};base64,{base64_image}", image_data
        except FileNotFoundError:
            raise Exception(f"Arquivo não encontrado: {file_path}")
        except Exception as e:
            raise Exception(f"Erro ao carregar imagem: {str(e)}")
    
    def build_sign_string(self, appid: str, timestamp: str, nonce: str) -> str:
        """Constrói a string para assinatura"""
        return f"{appid}-{timestamp}-{nonce}"
    
    def generate_signature(self, message: str, secret: str) -> str:
        """Gera assinatura HMAC-SHA256"""
        signature = hmac.new(
            secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest()
        
        return base64.b64encode(signature).decode('utf-8')
    
    def describe_image(self,
                      image_path: str = None,
                      image_url: str = None,
                      prompt: Optional[str] = None,
                      lang: str = 'en') -> dict:
        """
        Descreve uma imagem usando a API
        
        Args:
            image_path: Caminho para o arquivo de imagem
            prompt: Prompt personalizado (opcional)
            lang: Idioma da resposta (en, zh, de, es, fr, ja, ko)
        
        Returns:
            Resposta da API em formato dict
        """
        redis_conn = get_redis()

        if not image_path and not image_url:
            return ValueError('Envie pelo menos um parâmetro com dados de imagem')
        
        elif not image_path and image_url:
            try:
                image_bytes = requests.get(image_url).content
                content_hash = hashlib.sha256(image_bytes).hexdigest()
                cache_key = f"imagedescription:{content_hash}"

                cached_result = redis_conn.get(cache_key)
                if cached_result:
                    logger.info(f"Cache hit for key: {cache_key}")
                    return json.loads(cached_result)
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to fetch image from URL: {e}")
                pass
            except Exception as e:
                logger.error(f"An unexpected error occurred during cache check: {e}")
                pass

            extension = image_url.split('?')[0].split('.')[-1]
            image_path = f'app/services/tmp_files/tmp_image.{extension}'
            with open(image_path, 'wb') as f:
                f.write(image_bytes)
        
        elif not image_url and image_path:
            pass
        
        else:
            raise ValueError('Envie apenas um dos dois parâmetros com dados de imagem.')
        
        
        # 1. Carregar e converter imagem para base64
        image_base64_data, image_bytes = self.load_image_from_file(image_path)
        content_hash = hashlib.sha256(image_bytes).hexdigest()
        cache_key = f"imagedescription:{content_hash}"
        
        cached_result = redis_conn.get(cache_key)
        if cached_result:
            logger.info(f"Cache hit for key: {cache_key}")
            return json.loads(cached_result)

        logger.info(f"Cache miss for key: {cache_key}. Executing image description.")

        # 2. Gerar parâmetros de autenticação
        timestamp = str(int(time.time() * 1000))
        nonce = secrets.token_hex(4)
        
        # 3. Gerar assinatura
        sign_string = self.build_sign_string(self.appid, timestamp, nonce)
        signature = self.generate_signature(sign_string, self.secret)
        
        # 4. Preparar dados da requisição
        if prompt is None:
            prompt = ("Summarize the content of the picture in one sentence, "
                     "then describe in detail what is in the picture, including "
                     "objects, people, animals, and the atmosphere and mood of the picture")
        
        # Dados do formulário
        form_data = {
            'imageBase64Data': image_base64_data,
            'lang': lang,
            'prompt': prompt
        }
        
        # Headers
        headers = {
            'appid': self.appid,
            'timestamp': timestamp,
            'nonce': nonce,
            'signature': signature
        }
        
        # 5. Fazer requisição
        try:
            response = requests.post(
                self.base_url,
                data=form_data,
                headers=headers,
                timeout=30
            )
            
            response.raise_for_status()
            result = response.json()

            try:
                redis_conn.setex(cache_key, 86400, json.dumps(result)) # Cache for 24 hours
            except Exception as e:
                logger.error(f"Failed to write to cache: {e}")

            return result
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Erro na requisição: {str(e)}")
        except ValueError as e:
            raise Exception(f"Erro ao decodificar JSON: {str(e)}")

if __name__ == '__main__':
    client = ImageDescriptionAPI('sum_valid_app', 'sum_valid_key')
    describe = client.describe_image(image_url='https://zhqjfwfhfciewa0c16pfllaqmsq4xlzx.s3-eu-west-3.amazonaws.com/uploads/453bbf16-0c6a-4f74-8d38-3ac4eaf4256f.jpg?X-Amz-Expires=600&X-Amz-Date=20250530T122556Z&X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIA4GCHFIHYAF45Y5MB%2F20250530%2Feu-west-3%2Fs3%2Faws4_request&X-Amz-SignedHeaders=host&X-Amz-Signature=1fb6ce5e9d8c87f9f447ea5ad3190abbb5cb38f77494dd2ee0efb18f6b4a9167')
    
    print(describe)