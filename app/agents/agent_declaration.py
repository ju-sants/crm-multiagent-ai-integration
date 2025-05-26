from crewai import Agent
from app.config.llm_config import default_llm
from app.tools.callbell_tools import CallbellSendTool
import yaml


callbell_send_tool = CallbellSendTool()

agents_config = yaml.safe_load(open('app/config/agents_config.yaml', 'r').read())

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
        config=agents_config['StrategicAdvisorAgent'],
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
        config=agents_config['ResponseCraftsmanAgent'],
        llm=default_llm,
        tools=[],
        verbose=True,
        allow_delegation=False
    )
    

    
def get_delivery_coordinator_agent() -> Agent:
    return Agent(
        config=agents_config['DeliveryCoordinatorAgent'],
        llm=default_llm,
        tools=[callbell_send_tool],
        verbose=True,
        allow_delegation=False
    )