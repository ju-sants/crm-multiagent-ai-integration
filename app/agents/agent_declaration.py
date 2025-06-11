from crewai import Agent
import yaml

from app.config.llm_config import default_X_llm, reasoning_X_llm, fast_reasoning_X_llm, pro_Google_llm, pro_Google_llm, default_openai_llm, flash_Google_llm, flash_Google_llm_reason

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

def get_triage_agent() -> Agent:
    return Agent(
        config=agents_config['TriageAgent'],
        llm=fast_reasoning_X_llm,
        verbose=True,
        allow_delegation=False,
    )

def get_customer_profile_agent() -> Agent:
    return Agent(
        config=agents_config['CustomerProfiler'],
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
    
def get_response_craftsman_agent() -> Agent:
    return Agent(
        config=agents_config['ResponseCraftsman'],
        llm=fast_reasoning_X_llm,
        verbose=True,
        allow_delegation=False,
    )

def get_delivery_coordinator_agent() -> Agent:
    return Agent(
        config=agents_config['DeliveryCoordinator'],
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