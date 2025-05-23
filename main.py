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

    memory = {}
    # ====================================================================================
    # AGENTES
    # ====================================================================================

    @agent
    def triage_agent(self) -> Agent:
        """Define o agente de triagem de intenção."""
        return Agent(
            config=self.agents_config['triage_agent'],
            llm=self.llm,
            allow_delegation=True 
        )

    @agent
    def general_support_agent(self) -> Agent:
        """Define o agente de atendimento geral."""
        return Agent(
            config=self.agents_config['general_support_agent'],
            tools=[RAGTool()], 
            llm=self.llm,
            allow_delegation=True 
        )

    @agent
    def sales_agent(self) -> Agent:
        """Define o agente de vendas."""
        return Agent(
            config=self.agents_config['sales_agent'],
            tools=[RAGTool()], 
            llm=self.llm,
            allow_delegation=True
        )

    # ====================================================================================
    # TASKS
    # ====================================================================================

    @task
    def triage_task(self) -> Task:
        """Define a tarefa de triagem."""
        return Task(
            config=self.tasks_config['triage_task'],
            agent=self.triage_agent()
        )

    @task
    def support_task(self) -> Task:
        """Define a tarefa de atendimento geral."""
        return Task(
            config=self.tasks_config['support_task'],
            agent=self.general_support_agent()
        )

    @task
    def sales_task(self) -> Task:
        """Define a tarefa de vendas."""
        return Task(
            config=self.tasks_config['sales_task'],
            agent=self.sales_agent()
        )

    
    # ====================================================================================
    # CREWS
    # ====================================================================================

    @crew
    def dynamic_crew(self) -> Crew:
        """Crew dinâmica que permite delegação entre agentes com base no contexto."""
        return Crew(
            agents=[
                self.triage_agent(),
                self.general_support_agent(), 
                self.sales_agent()
            ],
            tasks=[
                self.triage_task(),
                self.support_task(), 
                self.sales_task()
            ],
            process=Process.hierarchical,
            verbose=True,
            manager_llm=self.llm
        )
    
    # ====================================================================================
    # LOGICA PRINCIPAL
    # ====================================================================================

    def run_client_interaction(self, client_message: str, user_id: str):
        print(f"\n💬 Mensagem do Cliente: {client_message}")

        # Inicializar memória do usuário se não existir
        if user_id not in self.memory:
            self.memory[user_id] = {'intention': None, 'history': ''}

        history = self.memory[user_id]['history']
        intention = self.memory[user_id]['intention']

        # Criar contexto para a interação
        context = {
            'client_message': client_message,
            'history': history,
            'intention': intention or "DESCONHECIDA"
        }

        # Determinar qual tarefa executar primeiro com base na intenção atual
        initial_task = None
        
        # Se não houver intenção definida ou for a primeira interação, começamos com triagem
        if intention is None:
            print("\n🔍 Iniciando com triagem para detectar intenção...")
            
            # Executar a tarefa de triagem primeiro
            triage_crew = Crew(
                agents=[self.triage_agent()],
                tasks=[self.triage_task()],
                process=Process.sequential,
                verbose=True
            )
            
            triage_result = triage_crew.kickoff(inputs=context)
            
            # Verificar se a triagem identificou uma intenção
            if "INTENÇÃO DETECTADA:" in triage_result.raw:
                parts = triage_result.raw.split("INTENÇÃO DETECTADA:")[1].split(' ')[0].strip()
                
                detected_intention = parts[0].split("\n")[0].strip()
                message = ' '.join(parts).strip()
                
                print(f'Agente de suporte diz:\n{message}')
                print(f"🔍 Intenção detectada: {detected_intention}")
                
                # Atualizar a intenção na memória
                self.memory[user_id]['intention'] = detected_intention
                intention = detected_intention
                
                # Determinar qual flow seguir com base na intenção detectada
                if "SOLICITACAO_ORCAMENTO" in intention:
                    # Direcionar para vendas
                    initial_task = self.sales_task()
                    print("\n💰 Direcionando para vendas...")
                else:
                    # Direcionar para suporte
                    initial_task = self.support_task()
                    print("\n🛠️ Direcionando para suporte...")
            else:
                # Se não conseguir detectar uma intenção clara, direcionar para suporte como fallback
                initial_task = self.support_task()
                print("\n🛠️ Intenção não detectada claramente, direcionando para suporte como fallback...")
        
        # Se já temos uma intenção, escolhemos diretamente o agente apropriado
        else:
            if "SOLICITACAO_ORCAMENTO" in intention:
                initial_task = self.sales_task()
                print(f"\n💰 Continuando com vendas baseado na intenção: {intention}")
            else:
                initial_task = self.support_task()
                print(f"\n🛠️ Continuando com suporte baseado na intenção: {intention}")
        
        # Criar crew para a tarefa específica
        if initial_task == self.sales_task():
            # Crew de vendas
            task_crew = Crew(
                agents=[self.sales_agent()],
                tasks=[self.sales_task()],
                process=Process.sequential,
                verbose=True
            )
        else:
            # Crew de suporte
            task_crew = Crew(
                agents=[self.general_support_agent()],
                tasks=[self.support_task()],
                process=Process.sequential,
                verbose=True
            )
        
        # Executar a tarefa específica
        result = task_crew.kickoff(inputs=context)
        
        # Verificar se houve mudança de intenção durante a execução
        if result and "INTENÇÃO DETECTADA:" in result.raw:
            # Extrair nova intenção do resultado
            response_text = result.raw
            new_intention = response_text.split("INTENÇÃO DETECTADA:")[1].strip().split("\n")[0].strip()
            
            # Atualizar a intenção na memória do usuário
            self.memory[user_id]['intention'] = new_intention
            print(f"🔄 Intenção atualizada para: {new_intention}")
            
            # Remover a marcação de intenção da resposta
            clean_response = response_text.split("INTENÇÃO DETECTADA:")[0].strip()
            if len(clean_response) < 5:  # Se a resposta ficou muito curta após a remoção
                # Executar novamente com a nova intenção
                print("🔄 Redirecionando com base na nova intenção...")
                return self.run_client_interaction(client_message, user_id)
            else:
                result.raw = clean_response
        
        # Atualizar histórico
        self.memory[user_id]['history'] += f"\nHuman: {client_message}\nAI: {result.raw}"

        print("\n✅ Resultado da Interação:")
        print(result.raw)
        
        return result.raw

# --- Simulação de Interações ---
if __name__ == "__main__":
    crew_team = GlobalAgentCrew()

    while True:
        query = input('Usuário: ')
        user_id = 'juan144'
        if query == '1':
            break

        crew_team.run_client_interaction(query, user_id)