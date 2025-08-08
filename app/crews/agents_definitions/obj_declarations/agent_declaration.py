from crewai import Agent
import yaml

from app.config.llm_config import *

from app.tools.knowledge_tools import knowledge_service_tool, drill_down_topic_tool
from app.tools.system_operations_tools import system_operations_tool


config_path = 'app/crews/agents_definitions/prompts/agents.yaml'

agents_config = yaml.safe_load(open(config_path, 'r').read())

def get_routing_agent() -> Agent:
    return Agent(
        config=agents_config['RoutingAgent'],
        llm=X_llm,
        verbose=True,
        allow_delegation=False,
    )

def get_strategic_advisor_agent(llm=None) -> Agent:
    return Agent(
        config=agents_config['StrategicAdvisor'],
        llm=X_llm if not llm else llm,
        tools=[knowledge_service_tool, drill_down_topic_tool],
        verbose=True,
        allow_delegation=False,
    )

def get_system_operations_agent(llm=None) -> Agent:
    return Agent(
        config=agents_config['SystemOperationsAgent'],
        llm=X_llm if not llm else llm,
        tools=[system_operations_tool],
        verbose=True,
        allow_delegation=False,
    )

def get_incremental_strategic_planner_agent(llm=None) -> Agent:
    return Agent(
        config=agents_config['IncrementalStrategicPlannerAgent'],
        llm=X_llm if not llm else llm,
        tools=[knowledge_service_tool, drill_down_topic_tool],
        verbose=True,
        allow_delegation=False,
    )

def get_communication_agent(llm=None) -> Agent:
    return Agent(
        config=agents_config['CommunicationAgent'],
        llm=X_llm if not llm else llm,
        tools=[drill_down_topic_tool],
        verbose=True,
        allow_delegation=False,
    )

def get_registration_agent() -> Agent:
    return Agent(
        config=agents_config['RegistrationDataCollectorAgent'],
        llm=X_llm,
        verbose=True,
        allow_delegation=False
    )

def get_history_summarizer_agent() -> Agent:
    return Agent(
        config=agents_config['HistorySummarizerAgent'],
        llm=default_openai_llm,
        verbose=True,
        allow_delegation=False,
    )

def get_data_quality_agent() -> Agent:
    return Agent(
        config=agents_config['DataQualityAgent'],
        llm=default_openai_llm,
        verbose=True,
        allow_delegation=False,
    )

def get_state_summarizer_agent() -> Agent:
    return Agent(
        config=agents_config['StateSummarizerAgent'],
        llm=default_openai_llm,
        verbose=True,
        allow_delegation=False,
    )

def get_profile_enhancer_agent() -> Agent:
    return Agent(
        config=agents_config['ProfileEnhancerAgent'],
        llm=default_openai_llm,
        verbose=True,
        allow_delegation=False,
    )

def get_follow_up_agent() -> Agent:
    return Agent(
        config=agents_config['FollowUpAgent'],
        llm=default_openai_llm,
        verbose=True,
        allow_delegation=False,
    )