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

from typing import Any

import redis

logger = get_logger(__name__)



def run_mvp_crew(contact_id: str, phone_number: str, redis_client: redis.Redis, history: Any):
    # litellm._turn_on_debug()
    logger.info(f"MVP Crew: Iniciando processamento para contact_id: {contact_id}, mensagem: '{'\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1))}'")

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
        "message_text": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
        "timestamp": datetime.datetime.now().isoformat(), 
        "l0l1_cache": str(L1CacheQueryTool()._run(contact_id)),
        "l2_cache": str(FastMemoryMessages()._run(contact_id))
    }
    
    history_messages = ''
    if history:
        history_messages = '\n'.join([f'{"AI" if "Alessandro" in str(message.get("text", "")) else "collaborator" if not message.get("status", "") == "received" else "customer"} - {message.get("text")}' for message in reversed(history.get('messages', []))])

    logger.info(f"MVP Crew: Executando kickoff com inputs: {inputs_triage}")
    try:
        triage_crew.kickoff(inputs_triage)
        logger.info(f"MVP Crew: Kickoff executado com sucesso para contact_id {contact_id}")

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
                    logger.info(f"MVP Crew: Iniciando processamento completo para contact_id {contact_id}")
                    customer_profile_agent_instance = get_customer_profile_agent()
                    strategic_advisor_instance = get_strategic_advisor_agent()
                    response_craftman_instance = get_response_craftsman_agent()
                    
                    profile_customer_task = create_profile_customer_task(customer_profile_agent_instance)
                    strategic_advise_task = create_develop_strategy_task(strategic_advisor_instance)
                    response_craft_task = create_craft_response_task(response_craftman_instance)
                    
                    logger.info(f"MVP Crew: Iniciando processamento completo para contact_id {contact_id}")
                    
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
                        "contact_id": contact_id,
                        "message_text_original": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
                        "operational_context": json_response.get('operational_context', ''),
                        "identified_topic": json_response.get('identified_topic', ''),
                        "customer_profile": str(GetUserProfile()._run(contact_id)),
                        "history": history_messages
                    }
                    
                    crew_profile.kickoff(inputs_profile)
                    
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
                        "message_text_original": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
                        "operational_context": json_response.get('operational_context', ''),
                        "identified_topic": json_response.get('identified_topic', ''),
                    }
                    
                    crew_strategic.kickoff(inputs_strategic)
                    
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
                        scroll = qdrant_client.scroll(
                            'UserProfiles',
                            limit=1000000000,
                            with_payload=True,
                            with_vectors=False
                        )
                        
                        id_point = str(uuid.uuid4())
                        for point_profile in scroll[0]:
                            if point_profile.payload.get('contact_id') == contact_id:
                                id_point = str(point_profile.id)
                        
                        payload['contact_id'] = contact_id
                        
                        qdrant_client.upsert(
                            'UserProfiles',
                            [
                            models.PointStruct(
                                id=id_point,
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
                        "message_text_original": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
                        "operational_context": json_response.get('operational_context', ''),
                        "identified_topic": json_response.get('identified_topic', ''),
                    }

                    
                    response_craft = crew_craft_messages.kickoff(inputs_craft)
                    
                    response_craft_json = None
                    response_craft_str = response_craft_task.output.raw
                    try:
                        if '```json' in response_craft_str:
                            response_craft_str = response_craft_str.split('```json')[-1].split('```')[0]
                            
                        if '```' in response_craft_str:
                            response_craft_str = response_craft_str.replace('```', '')
                            
                        response_craft_json = json.loads(response_craft.raw)
                    except json.JSONDecodeError:
                        logger.error('Não foi possível parsear o json de respostas finais')
                        
                    redo = False
                    if response_craft_json and 'Final Answer' in response_craft_json:
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
                        run_mvp_crew(contact_id, phone_number, redis_client, history)
                    
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
                    
                    history_messages = '\n'.join([f'{"AI" if "Alessandro" in message.get("text", "") else "collaborator" if not message.get("status") == "received" else "customer"}' for message in history.get('messages', [])[:5]])
                    
                    last_messages_processed = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
                    
                    inputs_delivery_crew = {
                        "identified_topic": json_response.get('identified_topic', ''),
                        "operational_context": json_response.get('operational_context', ''),
                        "message_text_original": '\n'.join(last_messages_processed),
                        "fast_messages": str(point_memory.payload.get('primary_messages_sequence', '')),
                        "proactive_content_generated": str(point_memory.payload.get('proactive_content_generated', '')),
                        "client_profile": str(point_profile.payload.get('profile_customer', '')) if found_profile else '',
                        "strategic_plan": str(point_profile.payload.get('strategic_plan', '')) if found_profile else '',
                        "history": history_messages
                    }
                    
                    all_messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
                    messages_left = [x for x in all_messages if x not in last_messages_processed]
                    
                    pipe = redis_client.pipeline()
                    
                    pipe.delete(f'contacts_messages:waiting:{contact_id}')
                    
                    if messages_left:
                        pipe.rpush(f'contacts_messages:waiting:{contact_id}', *messages_left)
                    
                    pipe.execute()


                    
                    found_profile = False
                    
                    delivery_crew.kickoff(inputs_delivery_crew)
                    
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
                        if not 'fast_messages_choosen_index' in response_delivery_json:
                            run_mvp_crew(contact_id, phone_number, redis_client, history)
                        
                        if 'choosen_messages' in response_delivery_json:
                            CallbellSendTool()._run(phone_number=phone_number, messages=response_delivery_json['choosen_messages'])
                            new_payload = point_memory.payload.copy()
                            
                            if response_delivery_json['fast_messages_choosen_index']:
                                for index in response_delivery_json['fast_messages_choosen_index']:
                                    
                                    del new_payload['primary_messages_sequence'][index]
                            
                            if 'proactive_content_choosen_index' in response_delivery_json and response_delivery_json['proactive_content_choosen_index']:
                                for index in response_delivery_json['proactive_content_choosen_index']:
                                    del response_delivery_json['proactive_content_choosen_index'][index]
                            
                            qdrant_client.upsert(
                                'FastMemoryMessages',
                                [
                                    models.PointStruct(
                                        id=str(point_memory.id),
                                        vector={},
                                        payload=new_payload
                                    )
                                ]
                            )
                            
                        elif 'Final Answer' in response_delivery_json and 'choosen_messages' in response_delivery_json['Final Answer']:
                            CallbellSendTool()._run(phone_number=phone_number, messages=response_delivery_json['Final Answer']['choosen_messages'])

                            new_response_json = {}
                            new_payload = point_memory.payload.copy()
                            
                            for k, v in response_craft_json['Final Answer']:
                                new_response_json[k] = v
                                
                            if new_response_json['fast_messages_choosen_index']:
                                for index in new_response_json['fast_messages_choosen_index']:
                                    
                                    del new_payload['primary_messages_sequence'][index]
                            
                            if 'proactive_content_choosen_index' in new_response_json and new_response_json['proactive_content_choosen_index']:
                                for index in new_response_json['proactive_content_choosen_index']:
                                    del new_response_json['proactive_content_choosen_index'][index]
                            
                            qdrant_client.upsert(
                                'FastMemoryMessages',
                                [
                                    models.PointStruct(
                                        id=str(point_memory.id),
                                        vector={},
                                        payload=new_payload
                                    )
                                ]
                            )
                    else:
                        run_mvp_crew(contact_id, phone_number, redis_client, history)
                else:
                    run_mvp_crew(contact_id, phone_number, redis_client, history)
                    
        else:
            logger.warning(f"MVP Crew: Nenhuma resposta gerada para contact_id {contact_id}")
    except Exception as e:
        logger.error(f"MVP Crew: Erro durante a execução do crew para contact_id {contact_id}: {e}", exc_info=True)