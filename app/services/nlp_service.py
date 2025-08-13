from sentence_transformers import SentenceTransformer
from functools import lru_cache
import os

from app.core.logger import get_logger

logger = get_logger(__name__)

_modelo_semantico = None
def carregar_modelo_semantico():
    global _modelo_semantico
    if _modelo_semantico is None:
        logger.info("Carregando modelo...")
        _modelo_semantico = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        logger.info("Modelo carregado.")
    return _modelo_semantico