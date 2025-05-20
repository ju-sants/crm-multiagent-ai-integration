from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task

from dotenv import load_dotenv

import os
from typing import Literal, List
from tools import IntentClassifierTool, RAGTool

load_dotenv()


GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
XAI_API_KEY = os.getenv('XAI_API_KEY')

llm = LLM(
    model='xai/grok-3-mini-beta',
    api_key=XAI_API_KEY,
    reasoning_effort='high',
    stream=True
)

# --- A Classe CrewAITeam ---

@CrewBase
class GlobalAgentCrew:
    """Crew para o Atendimento Global da Global System Rastreamento."""

    llm = LLM(
    model='xai/grok-3-mini-beta',
    api_key=XAI_API_KEY,
    reasoning_effort='high',
    stream=True
    )

    # Caminhos para os arquivos de configuração
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    @agent
    def triage_agent(self) -> Agent:
        """Define o agente de triagem de intenção."""
        return Agent(
            config=self.agents_config,
            agent_name="triage_agent", 
            tools=[IntentClassifierTool()], 
            llm=self.llm 
        )

    @agent
    def general_support_agent(self) -> Agent:
        """Define o agente de atendimento geral."""
        return Agent(
            config=self.agents_config,
            agent_name="general_support_agent", 
            tools=[RAGTool()], 
            llm=self.llm 
        )

    @agent
    def sales_agent(self) -> Agent:
        """Define o agente de vendas."""
        return Agent(
            config=self.agents_config,
            agent_name="sales_agent", 
            tools=[RAGTool()], 
            llm=self.llm 
        )

    @task
    def triage_task(self, client_message: str) -> Task:
        """Define a tarefa de triagem."""
        return Task(
            config=self.tasks_config,
            task_name="triage_task", 
            agent=self.triage_agent(), 
            inputs={"client_message": client_message} 
        )

    @task
    def support_task(self, client_intention: str, client_message: str) -> Task:
        """Define a tarefa de atendimento geral."""
        return Task(
            config=self.tasks_config,
            task_name="support_task", 
            agent=self.general_support_agent(), 
            context=[self.triage_task()], 
            inputs={
                "client_message": client_message,
                "client_intention": client_intention
            }
        )

    @task
    def sales_task(self, client_intention: str, client_message: str) -> Task:
        """Define a tarefa de vendas."""
        return Task(
            config=self.tasks_config,
            task_name="sales_task", 
            agent=self.sales_agent(), 
            context=[self.triage_task()], 
            inputs={
                "client_message": client_message,
                "client_intention": client_intention
            }
        )

    @crew
    def crew_(self, agents: List[Agent], tasks: List[Task], process: Literal[Process.sequential, Process.hierarchical]) -> Crew:
        """
        Cria e executa a crew principal para direcionar a interação com o cliente.
        """
        return Crew(
            agents=agents,
            tasks=tasks,
            process=process,
            verbose=True,
            manager_llm=self.llm
        )
    
    def run_client_interaction(self, client_message):
        print(f"\n💬 Mensagem do Cliente: {client_message}")

        triage_crew = self.crew_(
            agents=[self.triage_agent()],
            tasks=[self.triage_task(client_message)],
            process=Process.sequential,
        )
        
        triage_result_map = triage_crew.kickoff(inputs={'client_message': client_message})
        client_intention = triage_result_map.raw
        
        print(f"🧠 Intenção Identificada: {client_intention}")

        # 2. Direcionar para a Crew apropriada
        if client_intention.replace("'", '') == 'SOLICITACAO_ORCAMENTO':
            print("\n🚀 Acionando Crew de Vendas...")
            vendas_crew = self.crew_(
                agents=[self.sales_agent()], # Poderia ter mais agentes, ex: um para qualificação, outro para fechamento
                tasks=[self.sales_task(client_intention, client_message)],   # E mais tasks sequenciais ou hierárquicas
                process=Process.sequential,
            )
            # Passamos a mensagem original e a intenção para a task de vendas
            sales_interaction_result = vendas_crew.kickoff(inputs={
                'client_message': client_message,
                'client_intention': client_intention 
            })
            print("\n✅ Resultado da Interação de Vendas:")
            print(sales_interaction_result)

        elif client_intention.replace("'", '') in ['SUPORTE_TECNICO', 'DUVIDA_PRODUTO_SERVICO', 'FINANCEIRO', 'OUTROS']:
            print("\n🛠️ Acionando Crew de Atendimento Geral...")
            atendimento_crew = self.crew_(
                agents=[self.general_support_agent()],
                tasks=[self.support_task(client_intention, client_message)],
                process=Process.sequential,
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
    crew_team = GlobalAgentCrew()

    while True:
        query = input('Usuário: ')
        if query == '1':
            break

        crew_team.run_client_interaction(query)