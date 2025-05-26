from crewai.tools import BaseTool

from qdrant_client import QdrantClient
from langchain_qdrant.qdrant import QdrantVectorStore
from langchain_qdrant import FastEmbedSparse, RetrievalMode

from langchain_huggingface.embeddings import HuggingFaceEmbeddings

from sentence_transformers import SentenceTransformer

import os

import traceback

# --- Definição das Ferramentas ---


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

        if not os.path.exists('Global-Agent/utils/embedder/all-mpnet-base-v2'):
            model = SentenceTransformer('all-mpnet-base-v2')
            model.save('Global-Agent/utils/embedder/all-mpnet-base-v2')
            
        embeddings_dense = HuggingFaceEmbeddings(model_name='Global-Agent/utils/embedder/all-mpnet-base-v2')
        sparse_embeddings = FastEmbedSparse()

        vector_store = QdrantVectorStore(client=client, collection_name="Document", embedding=embeddings_dense, sparse_embedding=sparse_embeddings, retrieval_mode=RetrievalMode.HYBRID, vector_name='default', sparse_vector_name='sparse-text', content_payload_key='content')
        return vector_store.as_retriever(search_kwargs={"k": 5}, retrieval_mode=RetrievalMode.HYBRID, dense_vector_name="default", sparse_vector_name='sparse-text', search_type='similarity')
    
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        print(f"Erro ao conectar ao Qdrant: {e}")
        return None


retriever = get_retriever()

class RAGTool(BaseTool):
    name: str = "ConsultorEstrategicoDaBaseDeConhecimento_HyDE"
    description: str = f"""
Desbloqueie o Poder Total da Base de Conhecimento Global System com Consultas Estratégicas!

Atenção! A eficácia da sua busca em nossa base de conhecimento vetorial é diretamente proporcional à qualidade da sua consulta. Esqueça perguntas curtas ou palavras-chave isoladas que podem se perder. Para resultados precisos e relevantes, seu texto de busca precisa ser um farol: rico em detalhes, contexto e palavras-chave estratégicas, guiando a inteligência artificial aos documentos exatos que você necessita.

Pense nesta ferramenta como seu especialista interno sob demanda, pronto para fornecer informações detalhadas, embasar argumentos e solucionar problemas complexos com precisão cirúrgica.

A Chave para o Sucesso: A Técnica HyDE (Hypothetical Document Embeddings) Otimizada

Para extrair o máximo de nossa base, você NÃO DEVE enviar apenas termos genéricos. Em vez disso, construa um "Texto-Guia HyDE": um parágrafo elaborado (idealmente 3-5 frases) que simula um dos cenários abaixo, agindo como a "isca perfeita" para os documentos que você procura.

Crie um texto de no mínimo 5 linhas com VÁRIAS palavras chave escritas de forma diferente e explicando a situação com frases chave para maior contexto.
"""
    def _run(self, texto_HyDE: str) -> str:
        global retriever

        if retriever is None:
            print("ALERTA: O Retriever da base vetorial não está disponível ou não foi inicializado corretamente.")
            return "ERRO INTERNO: A conexão com a base de conhecimento (Retriever) falhou. Por favor, informe um administrador do sistema."

        if not texto_HyDE or len(texto_HyDE.split()) < 5:
             return "AVISO: Sua consulta (texto_HyDE) para a base de conhecimento parece muito curta ou vazia. Para melhores resultados, por favor, forneça um texto mais detalhado e contextualizado, conforme as instruções da técnica HyDE."

        print(f"\n[RAGTool] Executando consulta com texto_HyDE: '{texto_HyDE[:150]}...'") # Log da consulta

        try:
            docs = retriever.invoke(texto_HyDE)
        except Exception as e:
            print(f"ERRO ao executar retriever.invoke com texto_HyDE: '{texto_HyDE}'. Erro: {e}")
            print(traceback.format_exc())
            return f"ERRO DURANTE A CONSULTA À BASE DE CONHECIMENTO: Ocorreu um problema ao processar sua solicitação. Detalhe do erro: {str(e)}. Por favor, tente reformular sua consulta ou notifique um administrador."

        if not docs:
            print(f"[RAGTool] Nenhum documento encontrado para texto_HyDE: '{texto_HyDE[:150]}...'")
            return f"Nenhum documento relevante foi encontrado na base de conhecimento para a sua consulta específica (texto_HyDE: '{texto_HyDE[:100]}...'). Tente reformular seu texto_HyDE com mais detalhes, explorando as diferentes formas de elaborá-lo (pergunta completa, descrição do documento ideal ou rascunho da resposta perfeita), ou verifique se os termos usados são os mais comuns em nossa base."
            
        docs_text = f"DOCUMENTOS RELEVANTES ENCONTRADOS NA BASE DE CONHECIMENTO (em resposta ao seu texto_HyDE: '{texto_HyDE[:100]}...'):\n"
        docs_text += "Analise os seguintes documentos para embasar sua resposta:\n"
        for i, doc in enumerate(docs, 1):
            metadata_parts = []
            if isinstance(doc.metadata, dict):
                for k, v in doc.metadata.items():
                    if v:
                        metadata_parts.append(f"{k.replace('_', ' ').capitalize()}: {v}")
            metadata_str = "; ".join(metadata_parts) if metadata_parts else "N/A"
            
            docs_text += f"""
--------------------------------------------------
Documento {i}:
   Metadados: {metadata_str}
   Conteúdo Relevante:
   {doc.page_content}
--------------------------------------------------
""" 
        print(f"[RAGTool] {len(docs)} documentos retornados.")
        return docs_text