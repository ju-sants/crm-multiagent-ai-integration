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

import litellm

from qdrant_client import models

logger = get_logger(__name__)



def run_mvp_crew(contact_id: str, chat_id: str, phone_number: str, message_text: str):
    litellm._turn_on_debug()
    
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

        response_triage = triage_task.output.raw
        logger.info(f"MVP Crew: Resposta gerada pelo crew: {response_triage}")

        if response_triage:
            json_response = None
            try:
                if '```json' in response_triage:
                    response_triage = response_triage.split('```json')[-1].split('```')[0]
                
                if '```' in response_triage:
                    response_triage = response_triage.replace('```', '')
                    
                json_response = json.loads(response_triage)
                
            except json.JSONDecodeError:
                logger.error(f"MVP Crew: Resposta da triagem não é um JSON válido: {response_triage}")
            
            if json_response:
                if 'action' and json_response['action'] == "INITIATE_FULL_PROCESSING":
                    logger.info(f"MVP Crew: Iniciando processamento completo para chat_id {chat_id}")
                    customer_profile_agent_instance = get_customer_profile_agent()
                    strategic_advisor_instance = get_strategic_advisor_agent()
                    response_craftman_instance = get_response_craftsman_agent()
                    
                    profile_customer_task = create_profile_customer_task(customer_profile_agent_instance)
                    strategic_advise_task = create_develop_strategy_task(strategic_advisor_instance)
                    response_craft_task = create_craft_response_task(response_craftman_instance)
                    
                    logger.info(f"MVP Crew: Iniciando processamento completo para chat_id {chat_id}")
                    
                    # Criando Perfil
                    crew_profile = Crew(
                        agents=[
                            customer_profile_agent_instance,
                        ],
                        tasks=[
                            profile_customer_task,
                        ],
                        process=Process.sequential,
                        verbose=True,
                    )
                    
                    inputs_profile = {
                        "contact_id": contact_id,
                        "chat_id": chat_id,
                        "message_text_original": message_text,
                        "operational_context": json_response.get('operational_context', ''),
                        "identified_topic": json_response.get('identified_topic', ''),
                    }
                    
                    response_profile = crew_profile.kickoff(inputs_profile)
                    
                    # Criando estratégia
                    crew_strategic = Crew(
                        agents=[
                            strategic_advisor_instance
                        ],
                        tasks=[
                            strategic_advise_task
                        ]
                    )
                    
                    inputs_strategic = {
                        "profile_customer_task_output": profile_customer_task.output.raw,
                        "message_text_original": message_text,
                        "operational_context": json_response.get('operational_context', ''),
                        "identified_topic": json_response.get('identified_topic', ''),
                    }
                    
                    response_strategic = crew_strategic.kickoff(inputs_strategic)
                    
                    # Saving Profile and Strategic Plan
                    qdrant_client = get_client()
                    
                    scroll = qdrant_client.scroll(
                        "UserProfiles",
                        limit=1000000000,
                        with_payload=True,
                        with_vectors=False
                    )
                    
                    tasks_map = {
                        'profile_customer': profile_customer_task.output.raw,
                        'strategic_plan': strategic_advise_task.output.raw
                    }
                    
                    payload = {}
                    for name_task, response_task in tasks_map.items():
                        try:
                            if '```json' in response_task:
                                response_task = response_task.split('```json')[-1].split('```')[0]
                            
                            if '```' in response_task:
                                response_task = response_task.replace('```', '')
                                
                            payload[name_task] = json.loads(response_task)
                            
                        except json.JSONDecodeError:
                            pass
                    
                    if payload:                
                        qdrant_client.upsert(
                            'UserProfiles',
                            [
                            models.PointStruct(
                                id=str(point.id),
                                vector={},
                                payload=payload
                            )
                                ],
                        )
                    
                    # ===============================================
                        
                    # Craftando mensagens
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
                    
                    inputs_craft = {
                        "develop_strategy_task_output": strategic_advise_task.output.raw,
                        "profile_customer_task_output": profile_customer_task.output.raw,
                        "message_text_original": message_text,
                        "operational_context": json_response.get('operational_context', ''),
                        "identified_topic": json_response.get('identified_topic', ''),
                    }

                    
                    response_craft = crew_craft_messages.kickoff(inputs_craft)
                    
                    response_craft_json = None
                    try:
                        if '```json' in response_task:
                            response_task = response_task.split('```json')[-1].split('```')[0]
                            
                        if '```' in response_task:
                            response_task = response_task.replace('```', '')
                            
                        response_craft_json = json.loads(response_craft.raw)
                    except json.JSONDecodeError:
                        logger.error('Não foi possível parsear o json de respostas finais')
                        
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
                    limit=1000000000,
                    with_vectors=False,
                    with_payload=True
                    )
                
                point = None
                found = False
                for point in scroll[0]:
                    if point.payload.get('contact_id') == contact_id:
                        found = True
                        break
                
                if point and found:
                    inputs_delivery_crew = {
                        "identified_topic": json_response.get('identified_topic', ''),
                        "operational_context": json_response.get('operational_context', ''),
                        "message_text_original": message_text,
                        "fast_messages": point.payload.get('primary_messages_sequence', ''),
                        "proactive_content_generated": point.payload.get('proactive_content_generated', ''),
                    }
                    
                    response_delivery = delivery_crew.kickoff(inputs_delivery_crew)
                    
                    response_delivery_json = None
                    try:
                        response_delivery_str = delivery_coordinator_task.output.raw
                        
                        if '```json' in response_delivery_str:
                            response_delivery_str = response_delivery_str.split('```json')[-1].split('```')[0]
                        
                        if '```' in response_delivery_str:
                            response_delivery_str = response_delivery_str.replace('```', '')
                            
                        response_delivery_json = json.loads(response_delivery_str)
                        
                    except json.JSONDecodeError:
                        logger.error(f"MVP Crew: Resposta não é um JSON válido: {response}")
                        
                    
                    if response_delivery_json:
                        if 'choosen_messages' in response_delivery_json:
                            CallbellSendTool(phone_number=phone_number, messages=response_delivery_json['choosen_messages'])
                        
                        elif 'Final Answer' in response_delivery_json and 'choosen_messages' in response_delivery_json['Final Answer']:
                            CallbellSendTool(phone_number=phone_number, messages=response_delivery_json['Final Answer']['choosen_messages'])
                            
                        else:
                            run_mvp_crew(contact_id, chat_id, message_text)
                    else:
                        run_mvp_crew(contact_id, chat_id, message_text)
                else:
                    run_mvp_crew(contact_id, chat_id, message_text)
                    
        else:
            logger.warning(f"MVP Crew: Nenhuma resposta gerada para chat_id {chat_id}")
    except Exception as e:
        logger.error(f"MVP Crew: Erro durante a execução do crew para chat_id {chat_id}: {e}", exc_info=True)
        