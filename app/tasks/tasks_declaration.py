# app/tasks/tasks_declaration.py
from crewai import Task, Agent
from app.utils.funcs.funcs import obter_caminho_projeto

from app.tools.cache_tools import L1CacheQueryTool
from app.tools.qdrant_tools import (
    SaveFastMemoryMessages, FastMemoryMessages, GetUserProfile, SaveUserProfile,
    RAGTool
    )
from app.tools.knowledge_tools import BusinessGuidelinesTool

import yaml

base_path = obter_caminho_projeto()
config_path = base_path / 'app/config/crew_definitions/tasks.yaml'

tasks_config = yaml.safe_load(open(config_path, 'r').read())


def create_triage_task(agent: Agent) -> Task:
    return Task(
            config=tasks_config['triage_initial_message_task'],
            tools=[
                L1CacheQueryTool(), 
                FastMemoryMessages()
                ],
            agent=agent,
        )

def create_profile_customer_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['profile_customer_task'],
        tools=[
            GetUserProfile(), 
            SaveUserProfile()
            ],
        agent=agent,
    )
    
def create_execute_system_operations_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['execute_system_operations_task'],
        agent=agent,
    )

def create_develop_strategy_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['develop_strategy_task'],
        tools=[
            BusinessGuidelinesTool(), RAGTool()
        ],
        agent=agent,
    )

def create_craft_response_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['craft_response_task'],
        agent=agent,
    )
    
def create_coordinate_delivery_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['coordinate_delivery_task'],
        agent=agent,
    )