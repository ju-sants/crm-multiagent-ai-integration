# app/tasks/tasks_declaration.py
from crewai import Task, Agent

from app.tools.knowledge_tools import KnowledgeServiceTool

import yaml

config_path = 'app/config/crew_definitions/tasks.yaml'

tasks_config = yaml.safe_load(open(config_path, 'r').read())



def create_context_analysis_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['context_analysis_task'],
        agent=agent,
    )

def create_execute_system_operations_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['execute_system_operations_task'],
        agent=agent,
    )

def create_summarize_history_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['summarize_history_task'],
        agent=agent,
    )

def create_clean_noisy_data_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['clean_noisy_data_task'],
        agent=agent,
    )

def create_summarize_state_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['summarize_state_task'],
        agent=agent,
    )

def create_enhance_profile_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['enhance_profile_task'],
        agent=agent,
    )

def create_develop_strategy_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['develop_strategy_task'],
        agent=agent,
    )

def create_communication_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['communication_task'],
        agent=agent,
    )

def create_collect_registration_data_task(agent: Agent) -> Task:
    return Task(
        config=tasks_config['collect_registration_data_task'],
        agent=agent,
    )