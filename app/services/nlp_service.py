from sentence_transformers import SentenceTransformer
from functools import lru_cache
import os

from app.core.logger import get_logger

logger = get_logger(__name__)
@lru_cache(maxsize=1)
def carregar_modelo_semantico():
    """
    Carrega o modelo de análise semântica. 
    Este modelo é otimizado para análise de similaridade e será baixado na primeira vez que o código for executado.
    """
    if not os.path.exists('sentence_transformers'):
        os.makedirs('sentence_transformers')

    logger.info("Carregando modelo de análise semântica...")
    if os.path.exists('sentence_transformers/model'):
        logger.info("Modelo já carregado.")
        return SentenceTransformer('sentence_transformers/model')
    else:
        logger.info("Modelo não encontrado, baixando...")
        modelo = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        modelo.save('sentence_transformers/model')

    logger.info("Modelo carregado.")
    return modelo