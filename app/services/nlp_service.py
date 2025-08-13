from sentence_transformers import SentenceTransformer

from app.core.logger import get_logger

logger = get_logger(__name__)

_modelo_semantico = None
def carregar_modelo_semantico():
    global _modelo_semantico
    if _modelo_semantico is None:
        logger.info("Carregando modelo semântico...")
        _modelo_semantico = SentenceTransformer('sentence-transformers/paraphrase-multilingual-mpnet-base-v2')
        logger.info("Modelo carregado.")
    return _modelo_semantico