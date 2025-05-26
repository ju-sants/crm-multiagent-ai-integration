from crewai import Crew, Process, Task
from app.core.logger import get_logger
from app.agents.agent_declaration import (
    get_triage_agent,
    get_strategic_advisor_agent,
    get_response_craftsman_agent,
    get_delivery_coordinator_agent
)
from app.tasks.tasks_declaration import (
    create_triage_task,
    create_develop_strategy_task,
    create_craft_response_task,
    create_coordinate_delivery_task
)
from app.tools.callbell_tools import CallbellSendTool

import datetime



logger = get_logger(__name__)



def run_mvp_crew(contact_id: str, chat_id: str, message_text: str): # Adapted from run_full_processing_crew [cite: 265]
    logger.info(f"MVP Crew: Iniciando processamento para contact_id: {contact_id}, chat_id: {chat_id}, mensagem: '{message_text}'")

    triage_agent_instance = get_triage_agent()
    strategic_advisor_instance = get_strategic_advisor_agent()
    response_craftsman_instance = get_response_craftsman_agent()
    delivery_coordinator_instance = get_delivery_coordinator_agent()

    triage_task_input_for_description = {
        "contact_id": contact_id,
        "chat_id": chat_id,
        "message_text": message_text
    }
    triage_task: Task = create_triage_task()

    # strategy_task: Task = create_develop_strategy_task()
    # strategy_task.context = [triage_task]

    # craft_task: Task = create_craft_response_task()
    # craft_task.context = [strategy_task]

    # delivery_task: Task = create_coordinate_delivery_task()
    # delivery_task.context = [craft_task, triage_task]


    mvp_crew = Crew(
        agents=[
            triage_agent_instance,
            # strategic_advisor_instance,
            # response_craftsman_instance,
            # delivery_coordinator_instance
        ],
        tasks=[
            triage_task,
            # strategy_task,
            # craft_task,
            # delivery_task
        ],
        process=Process.sequential,
        verbose=True,
    )

    initial_inputs_for_kickoff = {
        "contact_id": contact_id,
        "chat_id": chat_id,
        "message_text": message_text,
        "timestamp": datetime.datetime.now().isoformat(), 
    }

    logger.info(f"MVP Crew: Executando kickoff com inputs: {initial_inputs_for_kickoff}")
    try:
        mvp_crew.kickoff(initial_inputs_for_kickoff)
        logger.info(f"MVP Crew: Kickoff executado com sucesso para chat_id {chat_id}")

        # Send the response to Callbell
        response = triage_task.output.raw
        logger.info(f"MVP Crew: Resposta gerada pelo crew: {response}")
        if response:
            logger.info(f"MVP Crew: Enviando resposta para Callbell: {response}")
        else:
            logger.warning(f"MVP Crew: Nenhuma resposta gerada para chat_id {chat_id}")
    except Exception as e:
        logger.error(f"MVP Crew: Erro durante a execução do crew para chat_id {chat_id}: {e}", exc_info=True)