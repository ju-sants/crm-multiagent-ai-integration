from crewai import Agent, Task, Crew, Process
from langchain_xai import ChatXAI
from dotenv import load_dotenv
import os

# Seus imports e setup de API Keys
load_dotenv()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
XAI_API_KEY = os.getenv('XAI_API_KEY')

# Carregar prompts dos arquivos
# (Você ainda pode fazer isso, e então passar o conteúdo para as descrições das Tasks)
hyde_prompt_template = open('RAG/prompt_hyde.txt', encoding='utf-8').read()
summary_prompt_template = open('RAG/prompt_summary.txt', 'r', encoding='utf-8').read()
system_prompt_content = open('RAG/prompt.txt', encoding='utf-8').read()

# Inicializar LLMs
llm_xai = ChatXAI(model="grok-3-mini-beta", api_key=XAI_API_KEY, temperature=0.7, top_p=0.9)
# llm_gemini = ChatGoogleGenerativeAI(google_api_key=GEMINI_API_KEY, model='gemini-2.5-flash-preview-04-17')

# Ferramentas
retrieval_tool = RetrievalTools().retrieve_documents

# Agentes
query_enhancer = Agent(
    role='Query Enhancer Specialist',
    goal=f'Transformar a consulta do usuário e o histórico da conversa em uma consulta hipotética otimizada para busca vetorial, usando o seguinte template como guia: "{hyde_prompt_template}"',
    backstory='Um especialista em entender a intenção do usuário e formular as melhores queries para encontrar informações.',
    llm=llm_xai,
    verbose=True
)

information_retriever = Agent(
    role='Information Retrieval Expert',
    goal='Encontrar os documentos mais relevantes da base de conhecimento usando a query fornecida.',
    backstory='Um bibliotecário perito em vasculhar arquivos digitais.',
    tools=[retrieval_tool],
    llm=llm_xai, # Pode ser um LLM mais simples se a lógica for direta
    verbose=True
)

summarization_expert = Agent(
    role='Content Summarization Expert',
    goal=f'Extrair a essência dos documentos recuperados, focando na relevância para a consulta original e o histórico, usando o seguinte template como guia: "{summary_prompt_template}"',
    backstory='Um editor conciso que destila informações complexas em resumos claros.',
    llm=llm_xai, # Ou llm_gemini se preferir
    verbose=True
)

response_generator = Agent(
    role='Conversational AI Assistant',
    goal='Fornecer uma resposta útil e contextualizada ao usuário, baseada no resumo e no histórico.',
    backstory=f'Um assistente de conversação amigável e experiente. Siga estas diretrizes de sistema: {system_prompt_content}',
    llm=llm_xai,
    verbose=True
)

# Tarefas
# As descrições agora podem usar placeholders que serão preenchidos pelo `inputs` do kickoff ou outputs de tarefas anteriores.
task_hyde = Task(
    description="""Analise a consulta do usuário: '{query}' e o histórico da conversa: '{history}'.
    Gere um parágrafo hipotético que representaria uma resposta ideal.
    Este parágrafo será usado para buscar documentos. Não inclua saudações ou frases como 'aqui está o parágrafo'. Apenas o parágrafo.""",
    expected_output='Um único parágrafo de texto representando o documento hipotético.',
    agent=query_enhancer
)

task_retrieve = Task(
    description="""Usando a seguinte consulta/documento hipotético, recupere os documentos mais relevantes da base de conhecimento.
    Consulta/Documento Hipotético: {context}""", # {context} será o output da task_hyde
    expected_output='Uma string contendo os documentos recuperados formatados, incluindo seus metadados e conteúdo.',
    agent=information_retriever,
    tools=[retrieval_tool],
    context=[task_hyde] # Especifica que esta tarefa usa o output da task_hyde
)

task_summarize = Task(
    description="""Com base nos seguintes documentos recuperados, no histórico da conversa e na consulta original, crie um resumo conciso.
    Documentos Recuperados: {context}
    Histórico da Conversa: {history}
    Consulta Original: {query}
    O resumo deve focar nos pontos mais relevantes para responder à consulta original. Não inclua saudações.""", # {context} será o output da task_retrieve
    expected_output='Um resumo textual conciso dos documentos recuperados.',
    agent=summarization_expert,
    context=[task_retrieve]
)

task_respond = Task(
    description="""Com base no seguinte resumo do contexto, no histórico da conversa, e na consulta do cliente, formule uma resposta final.
    Resumo do Contexto: {context}
    Histórico da Conversa: {history}
    Consulta do Cliente: {query}
    Responda diretamente à consulta do cliente.""", # {context} será o output da task_summarize
    expected_output='A resposta final textual para o cliente.',
    agent=response_generator,
    context=[task_summarize]
)

# Crew
crew = Crew(
    agents=[query_enhancer, information_retriever, summarization_expert, response_generator],
    tasks=[task_hyde, task_retrieve, task_summarize, task_respond],
    process=Process.sequential,
    verbose=2 # Nível de verbosidade
)

# Gerenciamento de memória (exemplo)
memory_dict = {} # Seu ConversationBufferMemory gerenciado externamente

# Loop de interação (adaptado)
if __name__ == '__main__':
    while True:
        user_id = 'juan444' # Exemplo
        query = input('Prompt: ')
        if query == '1':
            break

        # Obter ou criar memória para o usuário (simplificado aqui, use seu ConversationBufferMemory)
        if user_id not in memory_dict:
            memory_dict[user_id] = "" # Simples string para histórico; adapte para ConversationBufferMemory

        current_history = memory_dict[user_id]
        # No CrewAI, os inputs para kickoff podem ser usados nas descrições das tasks
        # As tasks podem passar contexto umas para as outras.

        # Para task_hyde: precisa de 'query' e 'history'
        # Para task_summarize: precisa de 'history' (dos inputs do kickoff) e 'query' (dos inputs do kickoff)
        #                     e o output da task_retrieve (automático via context=[task_retrieve])
        # Para task_respond: precisa de 'history' (dos inputs do kickoff) e 'query' (dos inputs do kickoff)
        #                    e o output da task_summarize (automático via context=[task_summarize])

        inputs_para_crew = {
            'query': query,
            'history': current_history
            # Se suas task descriptions precisarem de user_id, adicione aqui também.
        }
        
        # O output da task_hyde é passado para task_retrieve como 'context' automaticamente.
        # O output da task_retrieve é passado para task_summarize como 'context' automaticamente.
        # O output da task_summarize é passado para task_respond como 'context' automaticamente.

        result = crew.kickoff(inputs=inputs_para_crew)
        
        print(f"Resposta: {result}")

        # Atualizar memória (simplificado)
        memory_dict[user_id] += f"\nHumano: {query}\nAI: {result}"