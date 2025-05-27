from qdrant_client import QdrantClient
from functools import lru_cache

@lru_cache(maxsize=1)
def get_client():
    client = None
    try:
        client = QdrantClient(
            url='https://qdrant-production-fb9f.up.railway.app',
            timeout=600,
            port=None
        )

        client.get_collections()
        print("Conectado ao Qdrant com sucesso!")
        
        return client
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        print(f"Erro ao conectar ao Qdrant: {e}")
        return None