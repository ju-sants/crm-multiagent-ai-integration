from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task

from dotenv import load_dotenv

from langchain_huggingface import HuggingFaceEmbeddings

from sentence_transformers import SentenceTransformer
import os

from tools import IntentClassifierTool

load_dotenv()


GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
XAI_API_KEY = os.getenv('XAI_API_KEY')


# Agente de Triagem (será parte da "Crew de Entrada" ou da primeira etapa)
triage_agent = Agent(
    role='Analista de Intenções do Cliente',
    goal='Analisar a mensagem inicial do cliente e classificar com precisão a sua principal intenção para direcionar ao atendimento correto.',
    backstory=(
        "Você é um especialista em atendimento ao cliente com um olhar aguçado para entender "
        "rapidamente o que o cliente precisa. Sua função é categorizar a solicitação inicial "
        "para que ela seja tratada pela equipe mais adequada da empresa de rastreamento veicular."
    ),
    verbose=True,
    allow_delegation=False,
    tools=[IntentClassifierTool()], # O agente usa esta ferramenta
    llm=llm
)

# Agente de Atendimento Geral
general_support_agent = Agent(
    role='Especialista em Atendimento ao Cliente de Rastreamento Veicular',
    goal='Fornecer suporte informativo e resolver dúvidas gerais dos clientes sobre produtos, serviços e questões técnicas básicas da empresa de rastreamento.',
    backstory=(
        "Você é um especialista experiente nos produtos e serviços de rastreamento veicular. "
        "Seu objetivo é ajudar os clientes, respondendo suas perguntas de forma clara e cordial, "
        "e orientando-os sobre o uso dos rastreadores, aplicativo e site. Você tem acesso à base de conhecimento da empresa."
    ),
    verbose=True,
    allow_delegation=False, # Pode ser True se ele puder delegar para um agente de operações, por exemplo
    # tools=[SuaFerramentaRAG_Tool()], # Adicionar sua ferramenta RAG aqui
    llm=llm
)

# Agente de Vendas
sales_agent = Agent(
    role='Consultor de Vendas de Soluções de Rastreamento',
    goal='Entender as necessidades dos clientes, apresentar as melhores soluções de rastreamento, elaborar orçamentos e fechar vendas, aumentando a taxa de conversão.',
    backstory=(
        "Você é um consultor de vendas proativo e persuasivo, especialista em transformar o interesse "
        "dos clientes em negócios fechados. Você conhece profundamente os planos, produtos e seus benefícios, "
        "e sabe como destacar o valor das soluções de rastreamento da empresa."
    ),
    verbose=True,
    allow_delegation=False,
    # tools=[SuaFerramentaRAG_Tool(), FerramentaDeGeracaoDeOrcamento_Tool()], # Adicionar ferramentas relevantes
    llm=llm
)


# --- Definição das Tasks ---

# Task de Triagem
triage_task = Task(
    description=(
        "Analise a seguinte mensagem do cliente: '{client_message}'. "
        "Usando a ferramenta 'Classificador de Intenção do Cliente', determine a principal intenção do cliente. "
        "As categorias de intenção são: 'SUPORTE_TECNICO', 'SOLICITACAO_ORCAMENTO', "
        "'DUVIDA_PRODUTO_SERVICO', 'FINANCEIRO', 'OUTROS'. "
        "Seu output final DEVE SER APENAS a string da categoria identificada (ex: 'SOLICITACAO_ORCAMENTO')."
    ),
    expected_output="Uma única string representando a categoria da intenção do cliente (ex: 'SOLICITACAO_ORCAMENTO').",
    agent=triage_agent
)

# Task de Atendimento Geral (exemplo)
support_task = Task(
    description=(
        "O cliente entrou em contato com a seguinte dúvida/problema: '{client_message}'. "
        "A intenção foi classificada como {client_intention}. "
        "Forneça uma resposta clara e útil. Se for uma dúvida sobre produto/serviço, explique detalhadamente. "
        "Se for um problema de suporte técnico, ofereça os primeiros passos para solução ou colete mais informações."
        # "Use a ferramenta RAG para buscar informações se necessário."
    ),
    expected_output="Uma resposta completa e cordial para o cliente, abordando sua solicitação de suporte ou dúvida.",
    agent=general_support_agent,
    context=[triage_task] # Esta task depende do resultado da task de triagem
)

# Task de Vendas (exemplo)
sales_task = Task(
    description=(
        "Um cliente demonstrou interesse em um orçamento ou em adquirir nossos serviços. A mensagem inicial foi: '{client_message}'. "
        "A intenção foi classificada como {client_intention}. "
        "Seu objetivo é entender melhor as necessidades do cliente, apresentar os planos e produtos mais adequados e, se possível, gerar um orçamento inicial ou agendar uma conversa."
        # "Use a ferramenta RAG para informações de produto e a ferramenta de orçamento."
    ),
    expected_output="Uma interação de vendas proativa, buscando entender as necessidades do cliente, apresentar soluções e/ou um orçamento.",
    agent=sales_agent,
    context=[triage_task] # Esta task também depende do resultado da task de triagem
)

# --- Lógica de Orquestração e Definição das Crews (Simplificado) ---

def run_customer_interaction(client_message: str):
    print(f"\n💬 Mensagem do Cliente: {client_message}")

    # 1. Executar a triagem para determinar a intenção
    # Para isso, criamos uma "Crew de Triagem" temporária ou executamos a task diretamente
    # (CrewAI espera que tasks sejam executadas dentro de uma crew)
    
    triage_crew = Crew(
        agents=[triage_agent],
        tasks=[triage_task],
        process=Process.sequential,
        verbose=2
    )
    
    # O input para a task de triagem é a mensagem do cliente
    # Usamos o método 'kickoff' e passamos os inputs necessários para as tasks
    # As tasks devem ter placeholders como '{client_message}' em suas descrições
    triage_result_map = triage_crew.kickoff(inputs={'client_message': client_message})
    
    # O resultado da task de triagem (e da crew) será a intenção classificada.
    # Acessando o resultado da última task da crew de triagem:
    # Em versões mais recentes de CrewAI, o resultado é um dicionário onde as chaves são os nomes das tasks
    # ou uma string se for uma única task. Para múltiplas tasks, o resultado da crew
    # é o resultado da última task.
    # Se a task de triagem for a única, `triage_result_map` pode ser diretamente a string da intenção.
    # Vamos assumir que o `kickoff` retorna o resultado da última task se for uma string simples,
    # ou um dicionário se a task retornar um output mais estruturado.
    # A `expected_output` da `triage_task` é uma string, então esperamos uma string.
    
    # O resultado do kickoff é o output da última task da crew.
    # Como a triage_task tem "expected_output": "Uma única string...", o resultado é a string.
    client_intention = triage_result_map 
    
    print(f"🧠 Intenção Identificada: {client_intention}")

    # 2. Direcionar para a Crew apropriada
    if client_intention == 'SOLICITACAO_ORCAMENTO':
        print("\n🚀 Acionando Crew de Vendas...")
        vendas_crew = Crew(
            agents=[sales_agent], # Poderia ter mais agentes, ex: um para qualificação, outro para fechamento
            tasks=[sales_task],   # E mais tasks sequenciais ou hierárquicas
            process=Process.sequential,
            verbose=2
        )
        # Passamos a mensagem original e a intenção para a task de vendas
        sales_interaction_result = vendas_crew.kickoff(inputs={
            'client_message': client_message,
            'client_intention': client_intention 
        })
        print("\n✅ Resultado da Interação de Vendas:")
        print(sales_interaction_result)

    elif client_intention in ['SUPORTE_TECNICO', 'DUVIDA_PRODUTO_SERVICO', 'FINANCEIRO', 'OUTROS']:
        print("\n🛠️ Acionando Crew de Atendimento Geral...")
        atendimento_crew = Crew(
            agents=[general_support_agent], # Poderia ter mais agentes
            tasks=[support_task],          # E mais tasks
            process=Process.sequential,
            verbose=2
        )
        # Passamos a mensagem original e a intenção para a task de suporte
        support_interaction_result = atendimento_crew.kickoff(inputs={
            'client_message': client_message,
            'client_intention': client_intention
        })
        print("\n✅ Resultado da Interação de Atendimento:")
        print(support_interaction_result)
    else:
        print(f"⚠️ Intenção não reconhecida ou não mapeada para uma crew: {client_intention}")

# --- Simulação de Interações ---
if __name__ == "__main__":
    # Exemplo 1: Solicitação de Orçamento
    run_customer_interaction("Olá, gostaria de saber o preço do rastreador para carro e como contratar.")

    # Exemplo 2: Suporte Técnico
    run_customer_interaction("Bom dia, meu aplicativo não está mostrando a localização do meu veículo.")
    
    # Exemplo 3: Dúvida sobre Produto
    run_customer_interaction("Vocês têm algum plano que cubra roubo e furto para motos?")
