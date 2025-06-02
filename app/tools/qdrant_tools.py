from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type

from app.services.qdrant_service import get_client
from qdrant_client import models
from qdrant_client.http.models import Distance
from langchain_qdrant.qdrant import QdrantVectorStore
from langchain_qdrant import FastEmbedSparse, RetrievalMode
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from sentence_transformers import SentenceTransformer

import uuid
import json
import os

from functools import lru_cache


@lru_cache(maxsize=1)
def get_retriever():
    """Establishes a connection to Qdrant and returns the vector store."""
    client = None
    try:
        client = get_client()

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
    

VECTOR_SIZE = 768
DISTANCE_METRIC = Distance.COSINE 
class FastMemoryMessages(BaseTool):
    name: str = "FastMemoryMessages"
    description: str = "Usado para buscar mensagens rápidas na memória do Qdrant. É como se fosse parte do seu cerebro, te dando uma munição de mensagens rápidas para usar em suas respostas."
    
    def _run(self, contact_id) -> str:
        client = get_client()
        if not client:
            return "Erro ao conectar ao Qdrant."
        try:
            if not client.collection_exists("FastMemoryMessages"):
                client.create_collection(
                    collection_name="FastMemoryMessages",
                    vectors_config={'default': models.VectorParams(size=VECTOR_SIZE, distance=DISTANCE_METRIC)},
                )
            
            scroll = client.scroll(
                collection_name="FastMemoryMessages",
                limit=1000000000,
                with_vectors=False,
                with_payload=True
                )
            
            point_memory = None
            for point_memory in scroll[0]:
                if point_memory.payload.get('contact_id') == contact_id:
                    break
            
            return point_memory.payload if point_memory else {'primary_messages_sequence': [], 'proactive_content_generated': []}
        
        except Exception as e:
            return f"Erro ao buscar mensagens rápidas: {str(e)}"

class GetUserProfileInput(BaseModel):
    contact_id: str = Field(..., description="ID do usuário para buscar o perfil no Qdrant.")
class GetUserProfile(BaseTool):
    name: str = "GetUserProfile"
    description: str = "Usado para buscar o perfil do usuário no Qdrant."
    args_schema: Type[BaseModel] = GetUserProfileInput
    
    def _run(self, contact_id: str) -> str:
        client = get_client()
        if not client:
            return "Erro ao conectar ao Qdrant."
        try:
            if not client.collection_exists("UserProfiles"):
                client.create_collection(
                    collection_name="UserProfiles",
                    vectors_config=None,
                )
            
            scroll = client.scroll(
                collection_name="UserProfiles",
                with_payload=True
            )
            
            point = None
            for point in scroll[0]:
                if point.payload.get("contact_id") == contact_id:
                    break
                else:
                    point = None
            
            if point is None:
                return f"Perfil do usuário {contact_id} não encontrado."
            
            return point.payload['profile_customer']
        
        except Exception as e:
            return f"Erro ao buscar perfil do usuário: {str(e)}"

class SaveUserProfileInput(BaseModel):
    user_id: str = Field(..., description="ID do usuário para salvar o perfil no Qdrant.")
    profile_data: str | dict = Field(..., description="Dados do perfil do usuário a serem salvos.")
    
class SaveUserProfile(BaseTool):
    name: str = "SaveUserProfile"
    description: str = "Usado para salvar o perfil do usuário no Qdrant."
    args_schema: Type[BaseModel] = SaveUserProfileInput
    
    def _run(self, user_id: str, profile_data: str | dict) -> str:
        client = get_client()
        if not client:
            return "Erro ao conectar ao Qdrant."
        try:
            if not client.collection_exists("UserProfiles"):
                client.create_collection(
                    collection_name="UserProfiles",
                    vectors_config=None,
                )
            
            profile_data = profile_data if isinstance(profile_data, dict) else json.loads(profile_data)
            
            if 'user_id' not in profile_data:
                profile_data['user_id'] = user_id
            elif profile_data['user_id'] != user_id:
                profile_data['user_id'] = user_id
                
            client.upsert(
                collection_name="UserProfiles",
                points=[
                    models.PointStruct(
                        id=str(uuid.uuid5(uuid.NAMESPACE_URL, user_id)),
                        payload=profile_data,
                        vector={}
                    )
                ],
            )
            
            return f"Perfil do usuário {user_id} salvo com sucesso."
        
        except Exception as e:
            return f"Erro ao salvar perfil do usuário: {str(e)}"

class RAGToolInput(BaseModel):
    texto_HyDE: str = Field(..., description="Um texto que utiliza da ténica HyDE (Embbedings hipotéticos), que consiste em criar um texto que será usado para a busca semântica e por palavras chave na base vetorial, consiste em aprimorar a busca gerando uma consulta personalizada")
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
    args_schema: Type[BaseModel] = RAGToolInput
    
    def _run(self, texto_HyDE: str) -> str:
        retriever = get_retriever()

        if retriever is None:
            print("ALERTA: O Retriever da base vetorial não está disponível ou não foi inicializado corretamente.")
            return "ERRO INTERNO: A conexão com a base de conhecimento (Retriever) falhou. Por favor, informe um administrador do sistema."

        if not texto_HyDE or len(texto_HyDE.split()) < 5:
             return "AVISO: Sua consulta (texto_HyDE) para a base de conhecimento parece muito curta ou vazia. Para melhores resultados, por favor, forneça um texto mais detalhado e contextualizado, conforme as instruções da técnica HyDE."

        print(f"\n[RAGTool] Executando consulta com texto_HyDE: '{texto_HyDE[:150]}...'") # Log da consulta

        try:
            docs = retriever.invoke(texto_HyDE)
        except Exception as e:
            import traceback
            
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
    
class SaveFastMemoryMessagesInput(BaseModel):
    payload: str | dict = Field(..., description="Dados da mensagem rápida a serem salvos no Qdrant.")

class SaveFastMemoryMessages(BaseTool):
    name: str = "SaveFastMemoryMessages"
    description: str = "Usado para salvar mensagens rápidas no Qdrant."
    args_schema: Type[BaseModel] = SaveFastMemoryMessagesInput
    
    def _run(self, payload: str | dict) -> str:
        client = get_client()
        if not client:
            return "Erro ao conectar ao Qdrant."
        try:
            if not client.collection_exists("FastMemoryMessages"):
                client.create_collection(
                    collection_name="FastMemoryMessages",
                    vectors_config={'default': models.VectorParams(size=VECTOR_SIZE, distance=DISTANCE_METRIC)},
                )
            
            payload = payload if isinstance(payload, dict) else json.loads(payload)
            client.upsert(
                collection_name="FastMemoryMessages",
                points=[
                    models.PointStruct(
                        id='0fa08b3c-3b14-42cc-a04f-4fcaa3742da1', # ID fixo para mensagens rápidas
                        payload=payload,
                        vector={'default': SentenceTransformer('all-mpnet-base-v2').encode(str(payload), show_progress_bar=False).tolist()}
                    )
                ],
            )
            
            return "Mensages salvas com sucesso."
        
        except Exception as e:
            return f"Erro ao salvar mensagens: {str(e)}"
if __name__ == "__main__":
    
   g = GetUserProfile()
   print(g._run(user_id="12345"))