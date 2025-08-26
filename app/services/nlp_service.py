from sentence_transformers import SentenceTransformer
from functools import lru_cache

from app.core.logger import get_logger

logger = get_logger(__name__)

@lru_cache(maxsize=1)
def carregar_modelo_semantico():
    logger.info("Carregando modelo semântico...")
    modelo_semantico = SentenceTransformer('sentence-transformers/paraphrase-multilingual-mpnet-base-v2')
    logger.info("Modelo carregado.")
    return modelo_semantico