from crewai import Crew, Process, Task
import datetime
import json

from app.core.logger import get_logger

from app.agents.agent_declaration import (
    get_triage_agent,
    get_strategic_advisor_agent,
    get_response_craftsman_agent,
    get_delivery_coordinator_agent,
    get_customer_profile_agent,
    get_system_operations_agent
)
from app.tasks.tasks_declaration import (
    create_triage_task,
    create_develop_strategy_task,
    create_craft_response_task,
    create_coordinate_delivery_task,
    create_profile_customer_task,
    create_execute_system_operations_task
)

from app.tools.qdrant_tools import SaveFastMemoryMessages
from app.tools.callbell_tools import CallbellSendTool

from app.services.qdrant_service import get_client


logger = get_logger(__name__)



def run_mvp_crew(contact_id: str, chat_id: str, message_text: str): # Adapted from run_full_processing_crew [cite: 265]
    logger.info(f"MVP Crew: Iniciando processamento para contact_id: {contact_id}, chat_id: {chat_id}, mensagem: '{message_text}'")

    triage_agent_instance = get_triage_agent()

    triage_task: Task = create_triage_task(triage_agent_instance)



    mvp_crew = Crew(
        agents=[
            triage_agent_instance,
        ],
        tasks=[
            triage_task,
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

        response = triage_task.output.raw
        logger.info(f"MVP Crew: Resposta gerada pelo crew: {response}")

        if response:
            json_response = None
            try:
                json_response = json.loads(response)
            except json.JSONDecodeError:
                logger.error(f"MVP Crew: Resposta não é um JSON válido: {response}")
            
            if json_response:
                if 'action' and json_response['action'] == "INITIATE_FULL_PROCESSING":
                    logger.info(f"MVP Crew: Iniciando processamento completo para chat_id {chat_id}")
                    customer_profile_agent_instance = get_customer_profile_agent()
                    strategic_advisor_instance = get_strategic_advisor_agent()
                    response_craftman_instance = get_response_craftsman_agent()
                    
                    profile_customer_task = create_profile_customer_task(customer_profile_agent_instance)
                    strategic_advise_task = create_develop_strategy_task(strategic_advisor_instance)
                    response_craft_task = create_craft_response_task(response_craftman_instance)
                    
                    strategic_advise_task.context = profile_customer_task
                    response_craft_task.context = strategic_advise_task
                    
                    crew_full_processing = Crew(
                        agents=[
                            customer_profile_agent_instance,
                            strategic_advisor_instance,
                        ],
                        tasks=[
                            profile_customer_task,
                            strategic_advise_task,
                        ],
                        process=Process.sequential,
                        verbose=True,
                    )
                    
                    crew_craft_messages = Crew(
                        agents=[
                            response_craftman_instance  
                        ],
                        tasks=[
                            response_craft_task
                        ],
                        process=Process.sequential,
                        verbose=True
                    )
                    
                    inputs_for_full_processing = {
                        "contact_id": contact_id,
                        "chat_id": chat_id,
                        "message_text_original": message_text,
                        "operational_context": json_response.get('operational_context', ''),
                        "identified_topic": json_response.get('identified_topic', ''),
                    }
                    
                    response_full_processing = crew_full_processing.kickoff(inputs_for_full_processing)
                    logger.info(f"MVP Crew: Processamento completo iniciado com sucesso para chat_id {chat_id}")
                    
                    inputs_for_full_processing["develop_strategy_task_output"] = str(response_full_processing.tasks_output[0].raw)
                    inputs_for_full_processing["profile_customer_task_output"] = str(response_full_processing.tasks_output[1].raw)
                    
                    response_craft = crew_craft_messages.kickoff(inputs_for_full_processing)
                    
                    response_craft_json = json.loads(response_craft.raw)
                    
                    redo = False
                    if 'Final Answer' in response_craft_json:
                        if not 'primary_messages_sequence' in response_craft_json.get('Final Answer', {}):
                            redo = True
                        
                        else:
                            primary_messages = response_craft_json['Final Answer']['primary_messages_sequence']
                            proactive_content = response_craft_json['Final Answer'].get('proactive_content_generated', [])
                            
                            del response_craft_json['Final Answer']
                            
                            response_craft_json['primary_messages_sequence'] = primary_messages
                            response_craft_json['proactive_content_generated'] = proactive_content
                            
                    else:
                        if not 'primary_messages_sequence' in response_craft_json:
                            redo = True
                    
                    if redo:
                        run_mvp_crew(contact_id, chat_id, message_text)
                    
                    else:
                        SaveFastMemoryMessages()._run(
                            response_craft_json
                        )
                
                delivery_coordinator_instance = get_delivery_coordinator_agent()
                delivery_coordinator_task = create_coordinate_delivery_task(delivery_coordinator_instance)
                
                delivery_crew = Crew(
                    agents=[
                        delivery_coordinator_instance
                    ],
                    tasks=[
                        delivery_coordinator_task   
                    ],
                    process=Process.sequential,
                    verbose=True
                )
                
                qdrant_client = get_client()
                
                scroll = qdrant_client.scroll(
                    collection_name="FastMemoryMessages",
                    limit=500,
                    with_vectors=False,
                    with_payload=True
                    )
            
                inputs_delivery_crew = {
                    "identified_topic": json_response.get('identified_topic', ''),
                    "operational_context": json_response.get('operational_context', ''),
                    "message_text_original": message_text,
                    "fast_messages": scroll[0][0].payload.get('primary_messages_sequence', ''),
                    "proactive_content_generated": scroll[0][0].payload.get('proactive_content_generated', ''),
                }
                
                response_delivery = delivery_crew.kickoff(inputs_delivery_crew)
                
                response_delivery_json = json.loads(response_delivery.raw)
                
                if 'choosen_messages' in response_delivery_json:
                    # CallbellSendTool(phone_number='555198906538', messages=response_delivery_json['choosen_messages'])
                    for message in response_delivery_json['choosen_messages']:
                        print(message)
                        
                else:
                    run_mvp_crew(contact_id, chat_id, message_text)
                print()
        else:
            logger.warning(f"MVP Crew: Nenhuma resposta gerada para chat_id {chat_id}")
    except Exception as e:
        logger.error(f"MVP Crew: Erro durante a execução do crew para chat_id {chat_id}: {e}", exc_info=True)