# app/crews/conversation_crew.py
import asyncio
import json
from crewai import Crew, Process
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

logger = get_logger(__name__)

async def run_mvp_crew(contact_id: str, chat_id: str, message_text: str): # Adapted from run_full_processing_crew [cite: 265]
    logger.info(f"MVP Crew: Iniciando processamento para contact_id: {contact_id}, chat_id: {chat_id}, mensagem: '{message_text}'")

    triage_agent_instance = get_triage_agent()
    strategic_advisor_instance = get_strategic_advisor_agent()
    response_craftsman_instance = get_response_craftsman_agent()
    delivery_coordinator_instance = get_delivery_coordinator_agent()

    # 1. Triage Task
    # This input is passed to the task description string directly for MVP.
    # Alternatively, use placeholders in description and pass inputs to kickoff.
    triage_task_input_for_description = {
        "contact_id": contact_id,
        "chat_id": chat_id,
        "message_text": message_text
    }
    triage_task = create_triage_task(context_input=triage_task_input_for_description)

    # For MVP, TriageAgent's output will directly feed the next agent.
    # So, we create a single crew. A more complex system might have a separate TriageCrew.

    # 2. Strategy Task
    # This task will use the context (output) from triage_task.
    strategy_task = create_develop_strategy_task(strategic_advisor_instance)
    strategy_task.context = [triage_task] # Depends on triage_task output

    # 3. Craft Response Task
    craft_task = create_craft_response_task(response_craftsman_instance)
    craft_task.context = [strategy_task] # Depends on strategy_task output

    # 4. Delivery Task
    # Delivery task needs contact_id from triage_task and message from craft_task.
    # We need to ensure the context is correctly passed or structured.
    # For CrewAI, often the full context of previous tasks is available.
    # The description for coordinate_delivery_task expects 'primary_single_message' and 'contact_id'.
    # The Triage task output has contact_id. The Craft task output has primary_single_message.
    delivery_task = create_coordinate_delivery_task(delivery_coordinator_instance)
    delivery_task.context = [craft_task, triage_task] # Depends on craft_task (for message) and triage_task (for contact_id)


    mvp_crew = Crew(
        agents=[
            triage_agent_instance,
            strategic_advisor_instance,
            response_craftsman_instance,
            delivery_coordinator_instance
        ],
        tasks=[
            triage_task,
            strategy_task,
            craft_task,
            delivery_task
        ],
        process=Process.sequential,
        verbose=2,
        # memory=... # Not for initial MVP
    )

    # Inputs for kickoff: CrewAI can use these to populate placeholders in task descriptions if they are {{like_this}}.
    # Since we embedded initial inputs in triage_task's description directly,
    # this initial_inputs_for_kickoff might be less critical for the *first* task,
    # but good practice if tasks are designed to use them.
    initial_inputs_for_kickoff = {
        "contact_id": contact_id,
        "chat_id": chat_id,
        "message_text": message_text
    }

    logger.info(f"MVP Crew: Executando kickoff com inputs: {initial_inputs_for_kickoff}")
    try:
        # For async FastAPI, run synchronous CrewAI kickoff in a thread pool
        loop = asyncio.get_event_loop()
        # result = await loop.run_in_executor(None, mvp_crew.kickoff, initial_inputs_for_kickoff)
        # If your tools are async, and CrewAI version supports kickoff_async:
        # result = await mvp_crew.kickoff_async(inputs=initial_inputs_for_kickoff)
        
        # Let's assume kickoff can be called and its internal tool calls are handled (e.g. CallbellSendTool is sync for now)
        # For a simple MVP test without threading:
        result = mvp_crew.kickoff(inputs=initial_inputs_for_kickoff)

        logger.info(f"MVP Crew: Resultado final do processamento: {result}")

        # The 'result' is typically the output of the LAST task in a sequential crew.
        # In our case, it's the output of `coordinate_delivery_task`.
        # You might want to parse it or handle it. Example:
        if isinstance(result, str): # Sometimes LLMs output raw strings
            try:
                result_data = json.loads(result)
            except json.JSONDecodeError:
                logger.warning(f"MVP Crew: Output final não é JSON válido: {result}")
                result_data = {"raw_output": result}
        else: # Hopefully it's already a dict
            result_data = result

        if result_data and result_data.get("delivery_status") == "COMPLETED":
            logger.info(f"MVP Crew: Mensagem para {chat_id} entregue com sucesso.")
        elif result_data:
            logger.warning(f"MVP Crew: Entrega da mensagem para {chat_id} pode ter falhado ou status desconhecido: {result_data}")
        else:
            logger.error(f"MVP Crew: Resultado inesperado do crew: {result}")

    except Exception as e:
        logger.error(f"MVP Crew: Erro durante a execução do crew para chat_id {chat_id}: {e}", exc_info=True)