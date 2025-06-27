from crewai import Agent
import yaml

from app.config.llm_config import *

from app.tools.knowledge_tools import knowledge_service_tool, drill_down_topic_tool
from app.tools.system_operations_tools import system_operations_tool


config_path = 'app/config/crew_definitions/agents.yaml'

agents_config = yaml.safe_load(open(config_path, 'r').read())

def get_context_analysis_agent() -> Agent:
    return Agent(
        config=agents_config['ContextAnalysisAgent'],
        llm=flash_Google_llm_decisive_reason,
        verbose=True,
        allow_delegation=False,
    )

def get_strategic_advisor_agent(llm=None) -> Agent:
    return Agent(
        config=agents_config['StrategicAdvisor'],
        llm=flash_Google_llm_creative_reason if not llm else llm,
        tools=[knowledge_service_tool, drill_down_topic_tool],
        verbose=True,
        allow_delegation=False,
    )

def get_system_operations_agent(llm=None) -> Agent:
    return Agent(
        config=agents_config['SystemOperationsAgent'],
        llm=flash_Google_llm_decisive_reason if not llm else llm,
        tools=[system_operations_tool],
        verbose=True,
        allow_delegation=False,
    )

def get_communication_agent(llm=None) -> Agent:
    return Agent(
        config=agents_config['CommunicationAgent'],
        llm=flash_Google_llm_creative_reason if not llm else llm,
        tools=[drill_down_topic_tool],
        verbose=True,
        allow_delegation=False,
    )

def get_registration_agent() -> Agent:
    return Agent(
        config=agents_config['RegistrationDataCollectorAgent'],
        llm=flash_Google_llm_decisive_reason,
        verbose=True,
        allow_delegation=False
    )

def get_history_summarizer_agent() -> Agent:
    return Agent(
        config=agents_config['HistorySummarizerAgent'],
        llm=flash_Google_llm_creative_reason,
        verbose=True,
        allow_delegation=False,
    )

def get_data_quality_agent() -> Agent:
    return Agent(
        config=agents_config['DataQualityAgent'],
        llm=flash_Google_llm_decisive_reason,
        verbose=True,
        allow_delegation=False,
    )

def get_state_summarizer_agent() -> Agent:
    return Agent(
        config=agents_config['StateSummarizerAgent'],
        llm=flash_Google_llm_decisive_reason,
        verbose=True,
        allow_delegation=False,
    )

def get_profile_enhancer_agent() -> Agent:
    return Agent(
        config=agents_config['ProfileEnhancerAgent'],
        llm=flash_Google_llm_creative_reason,
        verbose=True,
        allow_delegation=False,
    )