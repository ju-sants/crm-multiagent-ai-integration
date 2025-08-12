from sentence_transformers import SentenceTransformer, util
from functools import lru_cache

@lru_cache(maxsize=1)
def carregar_modelo_semantico():
    """
    Carrega o modelo de análise semântica. 
    Este modelo é otimizado para análise de similaridade e será baixado na primeira vez que o código for executado.
    """
    print("Carregando modelo de análise semântica...")
    modelo = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    print("Modelo carregado.")
    return modelo