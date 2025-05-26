from crewai import Agent
import yaml

from app.config.llm_config import default_llm
from app.tools.callbell_tools import CallbellSendTool
from app.utils.funcs.funcs import obter_caminho_projeto


callbell_send_tool = CallbellSendTool()

base_path = obter_caminho_projeto()
config_path = base_path / 'app/config/crew_definitions/agents.yaml'

agents_config = yaml.safe_load(open(config_path, 'r').read())

def get_triage_agent() -> Agent:
    return Agent(
        config=agents_config['TriageAgent'],
        llm=default_llm,
        tools=[],
        verbose=True,
        allow_delegation=False
    )

def get_customer_profile_agent() -> Agent:
    return Agent(
        config=agents_config['CustomerProfileAgent'],
        llm=default_llm,
        tools=[],
        verbose=True,
        allow_delegation=False
    )

def get_strategic_advisor_agent() -> Agent:
    return Agent(
        config=agents_config['StrategicAdvisor'],
        llm=default_llm,
        tools=[],
        verbose=True,
        allow_delegation=False
    )

def get_system_operations_agent() -> Agent:
    return Agent(
        config=agents_config['SystemOperationsAgent'],
        llm=default_llm,
        tools=[],
        verbose=True,
        allow_delegation=False
    )
    
def get_response_craftsman_agent() -> Agent:
    return Agent(
        config=agents_config['ResponseCraftsman'],
        llm=default_llm,
        tools=[],
        verbose=True,
        allow_delegation=False
    )

def get_delivery_coordinator_agent() -> Agent:
    return Agent(
        config=agents_config['DeliveryCoordinator'],
        llm=default_llm,
        tools=[callbell_send_tool],
        verbose=True,
        allow_delegation=False
    )