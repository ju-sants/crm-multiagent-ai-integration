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

from app.tools.qdrant_tools import SaveFastMemoryMessages, FastMemoryMessages, GetUserProfile
from app.tools.cache_tools import L1CacheQueryTool
from app.tools.callbell_tools import CallbellSendTool

from app.services.qdrant_service import get_client

import litellm

from qdrant_client import models

import uuid

logger = get_logger(__name__)



def run_mvp_crew(contact_id: str, chat_id: str, phone_number: str, message_text: str):
    logger.info(f"MVP Crew: Iniciando processamento para contact_id: {contact_id}, chat_id: {chat_id}, mensagem: '{message_text}'")

    triage_agent_instance = get_triage_agent()

    triage_task: Task = create_triage_task(triage_agent_instance)

    triage_crew = Crew(
        agents=[
            triage_agent_instance,
        ],
        tasks=[
            triage_task,
        ],
        process=Process.sequential,
        verbose=True,
    )

    inputs_triage = {
        "contact_id": contact_id,
        "chat_id": chat_id,
        "message_text": message_text,
        "timestamp": datetime.datetime.now().isoformat(), 
        "l0l1_cache": L1CacheQueryTool()._run(contact_id),
        "l2_cache": FastMemoryMessages()._run(contact_id)
    }

    logger.info(f"MVP Crew: Executando kickoff com inputs: {inputs_triage}")
    try:
        triage_crew.kickoff(inputs_triage)
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
                        "customer_profile": GetUserProfile()._run(contact_id)
                    }
                    
                    response_profile = crew_profile.kickoff(inputs_profile)
                    
                    # Criando estratégia
                    crew_strategic = Crew(
                        agents=[
                            strategic_advisor_instance
                        ],
                        tasks=[
                            strategic_advise_task
                        ],
                        process=Process.sequential,
                        verbose=True
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
                        payload['contact_id'] = contact_id
                        
                        qdrant_client.upsert(
                            'UserProfiles',
                            [
                            models.PointStruct(
                                id=str(uuid.uuid4()),
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
                        response_craft_json['contact_id'] = contact_id
                        
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
                
                scroll_memory = qdrant_client.scroll(
                    collection_name="FastMemoryMessages",
                    limit=1000000000,
                    with_vectors=False,
                    with_payload=True
                    )
                
                scroll_profile = qdrant_client.scroll(
                    collection_name='UserProfiles',
                    limit=1000000000,
                    with_vectors=False,
                    with_payload=True
                )
                
                found_profile = False
                point_profile = None
                for point_profile in scroll_profile[0]:
                    if point_profile.payload.get('contact_id') == contact_id:
                        found_profile = True
                        break
                    
                point_memory = None
                found_memory = False
                for point_memory in scroll_memory[0]:
                    if point_memory.payload.get('contact_id') == contact_id:
                        found_memory = True
                        break
                
                if point_memory and found_memory:
                    found_memory = False
                    
                    inputs_delivery_crew = {
                        "identified_topic": json_response.get('identified_topic', ''),
                        "operational_context": json_response.get('operational_context', ''),
                        "message_text_original": message_text,
                        "fast_messages": point_memory.payload.get('primary_messages_sequence', ''),
                        "proactive_content_generated": point_memory.payload.get('proactive_content_generated', ''),
                        "client_profile": point_profile.payload.get('profile_customer', '') if found_profile else '',
                        "strategic_plan": point_profile.payload.get('strategic_plan', '') if found_profile else ''
                    }
                    
                    found_profile = False
                    
                    response_delivery = delivery_crew.kickoff(inputs_delivery_crew)
                    
                    response_delivery_json = None
                    response_delivery_str = delivery_coordinator_task.output.raw
                    try:
                        if '```json' in response_delivery_str:
                            response_delivery_str = response_delivery_str.split('```json')[-1].split('```')[0]
                        
                        if '```' in response_delivery_str:
                            response_delivery_str = response_delivery_str.replace('```', '')
                            
                        response_delivery_json = json.loads(response_delivery_str)
                        
                    except json.JSONDecodeError:
                        logger.error(f"MVP Crew: Resposta não é um JSON válido: {response_delivery_str}")
                    
                    if response_delivery_json:
                        # if 'choosen_messages' in response_delivery_json:
                        #     CallbellSendTool(phone_number=phone_number, messages=response_delivery_json['choosen_messages'])
                        
                        # elif 'Final Answer' in response_delivery_json and 'choosen_messages' in response_delivery_json['Final Answer']:
                        #     CallbellSendTool(phone_number=phone_number, messages=response_delivery_json['Final Answer']['choosen_messages'])
                            
                        # else:
                        #     run_mvp_crew(contact_id, chat_id, message_text)
                        print(response_delivery_json)
                        
                    else:
                        run_mvp_crew(contact_id, chat_id, message_text)
                else:
                    run_mvp_crew(contact_id, chat_id, message_text)
                    
        else:
            logger.warning(f"MVP Crew: Nenhuma resposta gerada para chat_id {chat_id}")
    except Exception as e:
        logger.error(f"MVP Crew: Erro durante a execução do crew para chat_id {chat_id}: {e}", exc_info=True)
        