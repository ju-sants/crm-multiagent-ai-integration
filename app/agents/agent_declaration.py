from crewai import Agent
import yaml

from app.config.llm_config import *

from app.utils.funcs.funcs import obter_caminho_projeto



base_path = obter_caminho_projeto()
config_path = base_path / 'app/config/crew_definitions/agents.yaml'

agents_config = yaml.safe_load(open(config_path, 'r').read())



def get_context_analysis_agent() -> Agent:
    return Agent(
        config=agents_config['ContextAnalysisAgent'],
        llm=fast_reasoning_X_llm,
        verbose=True,
        allow_delegation=False,
    )

def get_strategic_advisor_agent() -> Agent:
    return Agent(
        config=agents_config['StrategicAdvisor'],
        llm=pro_Google_llm,
        verbose=True,
        allow_delegation=False,
    )

def get_system_operations_agent() -> Agent:
    return Agent(
        config=agents_config['SystemOperationsAgent'],
        llm=fast_reasoning_X_llm,
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