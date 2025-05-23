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
        return vector_store.as_retriever(search_kwargs={"k": 5}, retrieval_mode=RetrievalMode.HYBRID, dense_vector_name="default", sparse_vector_name='sparse-text', search_type='hybrid')
    
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        print(f"Erro ao conectar ao Qdrant: {e}")
        return None


retriever = get_retriever()

class RAGTool(BaseTool):
    name: str = "ConsultorEstrategicoDaBaseDeConhecimento_HyDE"
    description: str = f"""
Esta é a sua ferramenta MAIS PODEROSA para acessar informações detalhadas e estratégicas da base de conhecimento vetorial da Global System. Utilize-a para embasar suas respostas, personalizar argumentos e resolver problemas complexos com precisão cirúrgica.

**COMO FORMULAR SUA CONSULTA (Técnica HyDE - Hypothetical Document Embeddings):**
Para extrair o máximo desta ferramenta, você NÃO DEVE enviar apenas palavras-chave ou perguntas curtas. Em vez disso, você precisa fornecer um "texto_HyDE" rico e elaborado. Este texto é a sua "isca perfeita" para os documentos que você precisa.

Seu "texto_HyDE" deve ser um parágrafo descritivo (idealmente 3-5 frases) que simule UM DOS SEGUINTES:

1.  **A PERGUNTA MAIS COMPLETA E CONTEXTUALIZADA:** Imagine que você está perguntando a um colega humano expert. Inclua todo o contexto relevante da conversa atual, o perfil do cliente, a dúvida específica ou o objetivo da sua tarefa.
    *Exemplo para vendas:* "Preciso de argumentos para convencer um cliente com foco em custo, que já teve uma experiência ruim com rastreadores baratos, sobre o valor do nosso plano Híbrido (GSM+SAT). Ele tem uma frota de 5 caminhões que operam em áreas remotas e urbanas. Quero destacar a confiabilidade e o custo-benefício a longo prazo."
    *Exemplo para suporte:* "Cliente com equipamento PGS Moto não está recebendo notificações no app Android versão 10, mesmo após reinstalar o app e limpar o cache. A moto está em área com bom sinal GSM. Quais os próximos passos de diagnóstico ou configurações específicas a verificar no app ou no equipamento?"

2.  **A DESCRIÇÃO DO DOCUMENTO IDEAL:** Descreva o conteúdo e as características do documento ou da informação perfeita que você gostaria de encontrar para resolver sua tarefa.
    *Exemplo:* "Estou buscando um documento que detalhe as cláusulas contratuais sobre a política de cancelamento de serviço para planos de frota, incluindo prazos, possíveis taxas e o procedimento exato que o cliente deve seguir."

3.  **UM RASCUNHO DA RESPOSTA PERFEITA:** Escreva um exemplo hipotético da resposta ou da informação que você gostaria de fornecer, e a ferramenta buscará os documentos que melhor sustentam ou complementam esse rascunho.
    *Exemplo:* "Nosso plano PGS Moto oferece cobertura em todo o território nacional utilizando a rede GSM. Em caso de [situação X], o procedimento é [Y]. Além disso, ele conta com [diferencial A] e [diferencial B], que garantem [benefício ao cliente]." (A ferramenta buscará documentos que confirmem/detalhem isso).

**ESCOPO DA CONSULTA (O que você pode encontrar):**
- Planos e Produtos: Detalhes, diferenciais, preços, catálogos (MOTOS, PGS, GSM Padrão, HÍBRIDO, GSM+WiFi, Scooters/Patinetes, Frotas).
- Suporte Técnico: Procedimentos, diagnósticos, manuais, soluções para falhas comuns e específicas.
- Contratos e Políticas: Termos, condições, SLA, política de privacidade, política de cancelamento.
- Processos Internos (Modus Operandi): Procedimentos para instalação, pós-venda, tratamento de roubo/furto.
- Vendas e Persuasão: Técnicas de vendas consultivas, argumentos de valor, gatilhos mentais, psicologia aplicada, estudos de caso de sucesso.
- Manejo de Objeções: Estratégias e respostas para objeções comuns (preço, concorrência, funcionalidade) e complexas.

**O QUE A FERRAMENTA RETORNA:**
Você receberá uma lista numerada dos trechos de documentos mais relevantes encontrados na base vetorial que correspondem ao seu "texto_HyDE". Cada documento incluirá seus metadados (como fonte, data, etc., se disponíveis) e o conteúdo principal. Analise criticamente esses resultados para construir sua resposta final.

Lembre-se: um "texto_HyDE" bem construído, rico em contexto e detalhes, é a chave para desbloquear o conhecimento mais valioso da Global System e permitir que você atue com excelência e máxima eficiência.
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