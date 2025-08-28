from sentence_transformers import SentenceTransformer
from transformers import pipeline
from functools import lru_cache
import emoji

from app.core.logger import get_logger

logger = get_logger(__name__)

@lru_cache(maxsize=1)
def carregar_modelo_semantico():
    logger.info("Carregando modelo semântico...")
    modelo_semantico = SentenceTransformer('sentence-transformers/paraphrase-multilingual-mpnet-base-v2')
    logger.info("Modelo carregado.")
    return modelo_semantico

@lru_cache(maxsize=1)
def carregar_contact_name_extractor():
    logger.info("Carregando modelo NER...")
    ner = pipeline("ner", "ju-sants/contact-name-extractor")
    logger.info("Modelo NER carregado...")

    return ner


def extrair_nome_contato(nome_contato):
    ner = carregar_contact_name_extractor()

    texto = emoji.replace_emoji(nome_contato, "")

    previous_char = None
    texto_normalizado = ""
    for char in texto:
        if previous_char is None:
            previous_char = char
        elif (previous_char.isalpha() and char.isnumeric()) or (previous_char.isnumeric() and char.isalpha()):
            texto_normalizado += " "
        
        texto_normalizado += char

    results = ner(nome_contato)

    extraction = ""
    last_entity_pos = None

    for result in results:
        if "NOME_CONTATO" in result["entity"]:
            if not last_entity_pos:
                last_entity_pos = result["end"]
            
            else:
                if not last_entity_pos == result["start"]:
                    extraction += " "
                
                last_entity_pos = result["end"]

            if "B-" in result["entity"] and extraction:
                    extraction += "OU "

            extraction += result["word"].replace("##", "")

    return extraction