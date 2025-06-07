# app/tasks/tasks_declaration.py
from crewai import Task, Agent
from app.utils.funcs.funcs import obter_caminho_projeto

from app.tools.qdrant_tools import RAGTool
from app.tools.knowledge_tools import BusinessGuidelinesTool, KnowledgeServiceTool

from app.config.settings import settings

import yaml

base_path = obter_caminho_projeto()
config_path = base_path / 'app/config/crew_definitions/tasks.yaml'

tasks_config = yaml.safe_load(open(config_path, 'r').read())


def create_triage_task(agent: Agent) -> Task:
    return Task(
            config=tasks_config['triage_initial_message_task'],
            agent=agent,
            max_retries=settings.MAX_RETRIES_MODEL
        )

def create_profile_customer_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['profile_customer_task'],
        agent=agent,
        max_retries=settings.MAX_RETRIES_MODEL
    )
    
def create_profile_customer_task_purchased(agent: Agent) -> Task:
    return Task(
        config=tasks_config['profile_customer_task_purchased'],
        agent=agent,
        max_retries=settings.MAX_RETRIES_MODEL
    )
    
def create_execute_system_operations_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['execute_system_operations_task'],
        agent=agent,
        max_retries=settings.MAX_RETRIES_MODEL,
    )

def create_develop_strategy_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['develop_strategy_task'],
        tools=[
            # BusinessGuidelinesTool(), RAGTool(),
            KnowledgeServiceTool(),
        ],
        agent=agent,
        max_retries=settings.MAX_RETRIES_MODEL
    )

def create_craft_response_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['craft_response_task'],
        agent=agent,
        max_retries=settings.MAX_RETRIES_MODEL
    )
    
def create_coordinate_delivery_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['coordinate_delivery_task'],
        agent=agent,
        max_retries=settings.MAX_RETRIES_MODEL
    )

def create_collect_registration_data_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['collect_registration_data_task'],
        agent=agent,
        max_retries=settings.MAX_RETRIES_MODEL
    )