from crewai import Agent
import yaml

from app.config.llm_config import *

from app.utils.funcs.funcs import obter_caminho_projeto

from app.tools.knowledge_tools import knowledge_service_tool
from app.tools.system_operations_tools import system_operations_tool


base_path = obter_caminho_projeto()
config_path = base_path / 'app/config/crew_definitions/agents.yaml'

agents_config = yaml.safe_load(open(config_path, 'r').read())

def get_context_analysis_agent() -> Agent:
    return Agent(
        config=agents_config['ContextAnalysisAgent'],
        llm=default_openai_llm,
        verbose=True,
        allow_delegation=False,
    )

def get_strategic_advisor_agent(llm=None) -> Agent:
    return Agent(
        config=agents_config['StrategicAdvisor'],
        llm=default_openai_llm if not llm else llm,
        tools=[knowledge_service_tool],
        verbose=True,
        allow_delegation=False,
    )

def get_system_operations_agent(llm=None) -> Agent:
    return Agent(
        config=agents_config['SystemOperationsAgent'],
        llm=default_openai_llm if not llm else llm,
        tools=[system_operations_tool],
        verbose=True,
        allow_delegation=False,
    )

def get_communication_agent() -> Agent:
    return Agent(
        config=agents_config['CommunicationAgent'],
        llm=fast_reasoning_X_llm,
        verbose=True,
        allow_delegation=False,
    )

def get_registration_agent() -> Agent:
    return Agent(
        config=agents_config['RegistrationDataCollectorAgent'],
        llm=fast_reasoning_X_llm,
        verbose=True,
        allow_delegation=False
    )