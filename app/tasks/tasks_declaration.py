# app/tasks/tasks_declaration.py
from crewai import Task, Agent
from app.agents.agent_declaration import (
    get_triage_agent,
    get_strategic_advisor_agent,
    get_response_craftsman_agent,
    get_delivery_coordinator_agent
)
from app.utils.funcs.funcs import obter_caminho_projeto
import yaml

base_path = obter_caminho_projeto()
config_path = base_path / 'app/config/crew_definitions/tasks.yaml'

tasks_config = yaml.safe_load(open(config_path, 'r').read())


def create_triage_task() -> Task:
    return Task(
            config=tasks_config['triage_initial_message_task'],
            agent=get_triage_agent(),
        )

def create_profile_customer_task() -> Task:
    return Task(
        config=tasks_config['profile_customer_task'],
        agent=get_triage_agent(),
    )
    
def create_execute_system_operations_task() -> Task:
    return Task(
        config=tasks_config['execute_system_operations_task'],
        agent=get_triage_agent(),
    )

def create_develop_strategy_task() -> Task:
    return Task(
        config=tasks_config['develop_strategy_task'],
        agent=get_strategic_advisor_agent(),
    )

def create_craft_response_task() -> Task:
    return Task(
        config=tasks_config['craft_response_task'],
        agent=get_response_craftsman_agent(),
        )

def create_coordinate_delivery_task() -> Task:
    return Task(
        config=tasks_config['coordinate_delivery_task'],
        agent=get_delivery_coordinator_agent(),
    )