from crewai.tools import BaseTool

from qdrant_client import QdrantClient
from langchain_qdrant.qdrant import QdrantVectorStore
from langchain_qdrant import FastEmbedSparse, RetrievalMode

from langchain_huggingface.embeddings import HuggingFaceEmbeddings

# --- Definição das Ferramentas ---
class IntentClassifierTool(BaseTool):
    name: str = "Classificador de Intenção do Cliente"
    description: str = (
        "Analisa a mensagem do cliente para classificar sua intenção principal. "
        "As categorias de intenção são: 'SUPORTE_TECNICO', 'SOLICITACAO_ORCAMENTO', "
        "'DUVIDA_PRODUTO_SERVICO', 'FINANCEIRO', 'OUTROS'. "
        "Responda APENAS com a string da categoria."
    )

    def _run(self, client_message: str) -> str:
        return f"A intenção para a mensagem '{client_message}' precisa ser classificada pelo LLM do agente."



# ====================================================================================================================

def get_retriever():
    """Establishes a connection to Qdrant and returns the vector store."""
    client = None
    try:
        client = QdrantClient(
            url='https://qdrant-production-fb9f.up.railway.app',
            timeout=600,
            port=None
        )

        client.get_collections()
        print("Conectado ao Qdrant com sucesso!")

        embeddings_dense = HuggingFaceEmbeddings(model_name='RAG/utils/embedder/all-mpnet-base-v2')
        sparse_embeddings = FastEmbedSparse()

        vector_store = QdrantVectorStore(client=client, collection_name="Document", embedding=embeddings_dense, sparse_embedding=sparse_embeddings, retrieval_mode=RetrievalMode.HYBRID, vector_name='default', sparse_vector_name='sparse-text', content_payload_key='content')
        return vector_store.as_retriever(search_kwargs={"k": 5}, retrieval_mode=RetrievalMode.HYBRID, dense_vector_name="default", sparse_vector_name='sparse-text')
    
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        print(f"Erro ao conectar ao Qdrant: {e}")
        return None


retriever = get_retriever()

class RAGTool(BaseTool):
    name: str = "Uma ferramenta usada para extrair informações do seu banco de dados vetorial, usando como parâmetro um texto dizendo de tudo que possa precisar (Técnica HyDE)."
    description: str = """
Você deve passar para essa Tool um Texto que servirá como farol para a busca de embeddings específicos no banco de dados.
Use essa Tool para pesquisar sobre planos, suporte, contrato, modos operandi, técnicas e psicologias de venda e políticas da empresa.
O texto que você enviará deve ser de pelo menos um parágrafo indicando TUDO que você possa precisar para completar com excelência a sua Task atual.
Nome da técnica: HyDE.
"""


    def _run(self, texto_HyDE: str) -> str:
        global retriever

        docs = retriever.invoke(texto_HyDE)
        
        docs_text = ''
        for i, doc in enumerate(docs, 1):
            docs_text += f"""
Doc {i} - {doc.metadata.values()}

{doc.page_content}

""" 
        return docs_text