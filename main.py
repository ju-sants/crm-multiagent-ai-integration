from crewai import Agent, Crew, Process, Task, LLM, Knowledge
from crewai.project import CrewBase, agent, crew, task
from crewai.knowledge.source.string_knowledge_source import StringKnowledgeSource
from dotenv import load_dotenv

import os
from typing import Literal, List
from tools import RAGTool

load_dotenv()


GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
XAI_API_KEY = os.getenv('XAI_API_KEY')


# --- A Classe CrewAITeam ---

@CrewBase
class GlobalAgentCrew:
    """Crew para o Atendimento Global da Global System Rastreamento."""

    # ====================================================================================
    # CONFIGURAÇÕES INCIIAIS
    # ====================================================================================

    llm = LLM(
    model='xai/grok-3-mini-beta',
    api_key=XAI_API_KEY,
    reasoning_effort='high',
    stream=True
    )

    # Caminhos para os arquivos de configuração
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    # ====================================================================================
    # AGENTES
    # ====================================================================================

    @agent
    def triage_agent(self) -> Agent:
        """Define o agente de triagem de intenção."""
        return Agent(
            config=self.agents_config['triage_agent'],
            llm=self.llm 
        )

    @agent
    def general_support_agent(self) -> Agent:
        """Define o agente de atendimento geral."""
        return Agent(
            config=self.agents_config['general_support_agent'],
            tools=[RAGTool()], 
            llm=self.llm 
        )

    @agent
    def sales_agent(self) -> Agent:
        """Define o agente de vendas."""
        return Agent(
            config=self.agents_config['sales_agent'],
            tools=[RAGTool()], 
            llm=self.llm 
        )

    # ====================================================================================
    # TASKS
    # ====================================================================================

    @task
    def triage_task(self) -> Task:
        """Define a tarefa de triagem."""
        return Task(
            config=self.tasks_config['triage_task'],
            agent=self.triage_agent(), 
        )

    @task
    def support_task(self) -> Task:
        """Define a tarefa de atendimento geral."""
        return Task(
            config=self.tasks_config['support_task'],
            agent=self.general_support_agent(), 
            context=[self.triage_task()], 
        )

    @task
    def sales_task(self) -> Task:
        """Define a tarefa de vendas."""
        return Task(
            config=self.tasks_config['sales_task'],
            agent=self.sales_agent(), 
            context=[self.triage_task()], 
        )

    
    # ====================================================================================
    # CREWS
    # ====================================================================================

    @crew
    def triage_flow_crew(self) -> Crew:
        """Crew específica para realizar a triagem da intenção do cliente."""
        return Crew(
            agents=[self.triage_agent()],
            tasks=[self.triage_task()],
            process=Process.sequential,
            verbose=True,
        )

    @crew
    def sales_flow_crew(self) -> Crew:
        """Crew específica para o fluxo de vendas."""
        return Crew(
            agents=[self.sales_agent()],
            tasks=[self.sales_task()],
            process=Process.sequential,
            verbose=True,
        )

    @crew
    def support_flow_crew(self) -> Crew:
        """Crew específica para o fluxo de atendimento/suporte."""
        return Crew(
            agents=[self.general_support_agent()],
            tasks=[self.support_task()],
            process=Process.sequential,
            verbose=True,
        )
    
    # ====================================================================================
    # LOGICA PRINCIPAL
    # ====================================================================================

    def run_client_interaction(self, client_message: str):
        print(f"\n💬 Mensagem do Cliente: {client_message}")

        triage_crew_instance = self.triage_flow_crew()
        triage_result = triage_crew_instance.kickoff(inputs={'client_message': client_message})
        client_intention = triage_result.raw.strip().replace("'", "")

        print(f"🧠 Intenção Identificada: {client_intention}")

        # 2. Direcionar para a Crew apropriada
        if client_intention == 'SOLICITACAO_ORCAMENTO':
            print("\n🚀 Acionando Crew de Vendas...")
            sales_crew_instance = self.sales_flow_crew()
            sales_interaction_result = sales_crew_instance.kickoff(inputs={
                'client_message': client_message,
                'client_intention': client_intention
            })
            print("\n✅ Resultado da Interação de Vendas:")
            print(sales_interaction_result)

        elif client_intention in ['SUPORTE_TECNICO', 'DUVIDA_PRODUTO_SERVICO', 'FINANCEIRO', 'OUTROS']:
            print("\n🛠️ Acionando Crew de Atendimento Geral...")
            support_crew_instance = self.support_flow_crew()
            support_interaction_result = support_crew_instance.kickoff(inputs={
                'client_message': client_message,
                'client_intention': client_intention
            })
            print("\n✅ Resultado da Interação de Atendimento:")
            print(support_interaction_result)
        else:
            print(f"⚠️ Intenção não reconhecida ou não mapeada para uma crew: {client_intention}")

# --- Simulação de Interações ---
if __name__ == "__main__":
    crew_team = GlobalAgentCrew()

    while True:
        query = input('Usuário: ')
        if query == '1':
            break

        crew_team.run_client_interaction(query)