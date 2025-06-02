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
    get_system_operations_agent,
    get_registration_agent
)
from app.tasks.tasks_declaration import (
    create_triage_task,
    create_develop_strategy_task,
    create_craft_response_task,
    create_coordinate_delivery_task,
    create_profile_customer_task,
    create_profile_customer_task_purchased,
    create_execute_system_operations_task,
    create_collect_registration_data_task
)

from app.tools.qdrant_tools import SaveFastMemoryMessages, FastMemoryMessages, GetUserProfile
from app.tools.cache_tools import L1CacheQueryTool
from app.tools.callbell_tools import CallbellSendTool

from app.services.qdrant_service import get_client
from app.services.telegram_service import send_single_telegram_message

import litellm

from qdrant_client import models

import uuid

from typing import Any

import redis

logger = get_logger(__name__)



def run_mvp_crew(contact_id: str, phone_number: str, redis_client: redis.Redis, history: Any):
    # litellm._turn_on_debug()
    mensagem = '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1))
    logger.info(f"MVP Crew: Iniciando processamento para contact_id: {contact_id}, mensagem: '{mensagem}'")

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
    
    history_messages = ''
    if history:
        history_messages = '\n'.join([f'{"AI" if "Alessandro" in str(message.get("text", "")) else "collaborator" if not message.get("status", "") == "received" else "customer"} - {message.get("text")}' if message.get("text") else '' for message in reversed(history.get('messages', [])[:10])])

    inputs_triage = {
        "contact_id": contact_id,
        "message_text": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
        "timestamp": datetime.datetime.now().isoformat(), 
        "l0l1_cache": str(L1CacheQueryTool()._run(contact_id)),
        "l2_cache": str(FastMemoryMessages()._run(contact_id)),
        "history": history_messages
    }
    
   
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
                if redis_client.get(f"{contact_id}:getting_data_from_user"):
                    json_response['operational_context'] = 'BUDGET_ACCEPTED'
                    
                if 'operational_context' in json_response and json_response['operational_context'] == 'BUDGET_ACCEPTED':
                    qdrant_client = get_client()

                    if not redis_client.get(f"{contact_id}:confirmed_plan"):
                        customer_profile_agent_instance = get_customer_profile_agent()
                        profile_task_purchased = create_profile_customer_task_purchased(customer_profile_agent_instance)
                        
                        scroll = qdrant_client.scroll(
                            "UserProfiles",
                            limit=1000000000,
                            with_payload=True,
                            with_vectors=False
                        )
                                
                        new_profile_crew = Crew(
                            agents=[
                                customer_profile_agent_instance
                            ],
                            tasks=[
                                profile_task_purchased
                            ],
                            process=Process.sequential,
                            verbose=True
                        )
                        
                        inputs_profile = {
                            "contact_id": contact_id,
                            "message_text_original": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
                            "operational_context": json_response.get('operational_context', ''),
                            "identified_topic": json_response.get('identified_topic', ''),
                            "customer_profile": str(GetUserProfile()._run(contact_id)),
                            "history": history_messages
                        }
                        
                        new_profile_crew.kickoff(inputs=inputs_profile)
                        
                        profile_task_purchased_str = profile_task_purchased.output.raw
                        
                        if profile_task_purchased_str:
                            profile = None
                            id = str(uuid.uuid4())
                            for point_profile in scroll[0]:
                                if point_profile.payload.get("contact_id") == contact_id:
                                    profile = point_profile.payload.copy()
                                    id = str(point_profile.id)

                            profile['profile_customer'] = profile_task_purchased_str
                            
                            qdrant_client.upsert(
                                "UserProfiles",
                                [
                                    models.PointStruct(
                                        id=id,
                                        vector={},
                                        payload=profile
                                    )
                                ]
                            )
                            
                            redis_client.set(f"{contact_id}:confirmed_plan", '1')
                            
                    if not qdrant_client.collection_exists("CustomersDataForSigUp"):
                        qdrant_client.create_collection(
                            'CustomersDataForSignUp',
                            vectors_config=None,
                        )
                        
                        
                    scroll = qdrant_client.scroll(
                        "CustomersDataForSignUp",
                        limit=1000000000,
                        with_vectors=False,
                        with_payload=True
                    )
                    
                    point_user_data = None
                    for point in scroll[0]:
                        if point.payload.get('contact_id') == contact_id:
                            point_user_data = point
                    
                    user_data_so_far = None
                    if point_user_data:
                        user_data_so_far = point_user_data.payload.copy()
                    
                    plan_details = json_response.get("plan_details", "")
                    
                    registration_agent = get_registration_agent()
                    registration_task = create_collect_registration_data_task(registration_agent)
                    
                    registration_crew = Crew(
                        agents=[
                            registration_agent
                        ],
                        tasks=[
                            registration_task
                        ],
                        process=Process.sequential,
                        verbose=True
                    )
                    
                    inputs_for_registration = {
                        "history": history_messages,
                        "message_text_original": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
                        "collected_data_so_far": str(user_data_so_far),
                        "plan_details": str(plan_details)
                    }

                    registration_crew.kickoff(inputs_for_registration)
                    
                    registration_task_str = registration_task.output.raw
                    registration_task_json = None
                    try:
                        if '```json' in registration_task_str:
                                registration_task_str = registration_task_str.split('```json')[-1].split('```')[0]
                            
                        if '```' in registration_task_str:
                            registration_task_str = registration_task_str.replace('```', '')
                            
                        registration_task_json = json.loads(registration_task_str)
                    except json.JSONDecodeError:
                        pass
                    
                    if registration_task_json and all([registration_task_json.get("is_data_collection_complete"), registration_task_json.get("status") == 'COLLECTION_COMPLETE']):
                        send_single_telegram_message(registration_task_str, '-4854533163')
                        redis_client.delete(f"{contact_id}:getting_data_from_user")
                    
                    if registration_task_json and "next_message_to_send" in registration_task_json and registration_task_json["next_message_to_send"]:
                        CallbellSendTool().run(phone_number=phone_number, messages=[registration_task_json["next_message_to_send"]])
                        
                        redis_client.set(f"{contact_id}:getting_data_from_user", "1")
                else:
                    redis_client.delete(f"{contact_id}:confirmed_plan")
                    
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
                                
                            response_craft_json = json.loads(response_craft_str)
                            
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
                            if not response_craft_json:
                                redo = True
                                
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
                    
                    profile = None
                    for point_profile in scroll_profile[0]:
                        if point_profile.payload.get('contact_id') == contact_id:
                            profile = point_profile.payload.copy()
                            break
                        
                    memory = None
                    for point_memory in scroll_memory[0]:
                        if point_memory.payload.get('contact_id') == contact_id:
                            memory = point_memory.payload.copy()
                            break
                    
                    if memory and profile:
                        history_messages = ''
                        if history:
                            history_messages = '\n'.join([f'{"AI" if "Alessandro" in str(message.get("text", "")) else "collaborator" if not message.get("status") == "received" else "customer"} - {message.get("text")}' for message in reversed(history.get('messages', [])[:5])])
                        
                        last_messages_processed = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
                        
                        inputs_delivery_crew = {
                            "identified_topic": json_response.get('identified_topic', ''),
                            "operational_context": json_response.get('operational_context', ''),
                            "message_text_original": '\n'.join(last_messages_processed),
                            "fast_messages": str(memory.get('primary_messages_sequence', '')),
                            "proactive_content_generated": str(memory.get('proactive_content_generated', '')),
                            "client_profile": str(profile.get('profile_customer', '')),
                            "strategic_plan": str(profile.get('strategic_plan', '')),
                            "history": history_messages
                        }
                        
                                            
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
                            logger.info(f'[{contact_id}] - response_delivery_json existe.')

                            if not 'fast_messages_choosen_index' in response_delivery_json:
                                logger.info(f'[{contact_id}] - "fast_messages_choosen_index" NÃO está em response_delivery_json. Chamando run_mvp_crew.')
                                run_mvp_crew(contact_id, phone_number, redis_client, history)
                            else:
                                logger.info(f'[{contact_id}] - "fast_messages_choosen_index" está em response_delivery_json. Prosseguindo com a lógica de order/Final Answer.')

                            payload = point_memory.payload.copy()
                            if 'order' in response_delivery_json:
                                logger.info(f'[{contact_id}] - "order" encontrado em response_delivery_json. Enviando mensagens Callbell.')
                                try:
                                    CallbellSendTool()._run(phone_number=phone_number, messages=response_delivery_json['order'])
                                    logger.info(f'[{contact_id}] - Mensagens do "order" enviadas via CallbellSendTool.')
                                except Exception as e:
                                    logger.error(f'[{contact_id}] - ERRO ao enviar mensagens do "order" via CallbellSendTool: {e}', exc_info=True)

                                new_payload = point_memory.payload.copy()
                                logger.info(f'[{contact_id}] - Payload de point_memory copiado para new_payload.')

                                if response_delivery_json['fast_messages_choosen_index']:
                                    logger.info(f'[{contact_id}] - "fast_messages_choosen_index" existe e não está vazio. Removendo mensagens primárias.')
                                    for index in response_delivery_json['fast_messages_choosen_index']:
                                        
                                            logger.debug(f'[{contact_id}] - Removendo índice {index} de primary_messages_sequence.')
                                            new_payload['primary_messages_sequence'].remove(payload['primary_messages_sequence'][index])
                                            
                                    logger.info(f'[{contact_id}] - Remoção de mensagens primárias concluída.')

                                if 'proactive_content_choosen_index' in response_delivery_json and response_delivery_json['proactive_content_choosen_index']:
                                    logger.info(f'[{contact_id}] - "proactive_content_choosen_index" existe e não está vazio. Removendo conteúdo proativo.')
                                    for index in response_delivery_json['proactive_content_choosen_index']:
                                        
                                            logger.debug(f'[{contact_id}] - Removendo índice {index} de proactive_content_choosen_index.')
                                            response_delivery_json['proactive_content_choosen_index'].remove(payload['proactive_content_choosen_index'][index])
                                            
                                    logger.info(f'[{contact_id}] - Remoção de conteúdo proativo concluída.')

                                try:
                                    logger.info(f'[{contact_id}] - Fazendo upsert no Qdrant para FastMemoryMessages com ID: {point_memory.id}.')
                                    qdrant_client.upsert(
                                        'FastMemoryMessages',
                                        [
                                            models.PointStruct(
                                                id=str(point_memory.id),
                                                vector={}, # Se o vetor não for atualizado, pode ser um dicionário vazio
                                                payload=new_payload
                                            )
                                        ]
                                    )
                                    logger.info(f'[{contact_id}] - Upsert no Qdrant para FastMemoryMessages CONCLUÍDO.')
                                except Exception as e:
                                    logger.error(f'[{contact_id}] - ERRO ao fazer upsert no Qdrant para FastMemoryMessages: {e}', exc_info=True)

                            elif 'Final Answer' in response_delivery_json and 'choosen_messages' in response_delivery_json['Final Answer']:
                                logger.info(f'[{contact_id}] - "Final Answer" e "choosen_messages" encontrados em response_delivery_json. Enviando mensagens Callbell.')
                                try:
                                    CallbellSendTool()._run(phone_number=phone_number, messages=response_delivery_json['Final Answer']['choosen_messages'])
                                    logger.info(f'[{contact_id}] - Mensagens do "Final Answer" enviadas via CallbellSendTool.')
                                except Exception as e:
                                    logger.error(f'[{contact_id}] - ERRO ao enviar mensagens do "Final Answer" via CallbellSendTool: {e}', exc_info=True)

                                new_response_json = {}
                                new_payload = point_memory.payload.copy()
                                logger.info(f'[{contact_id}] - Payload de point_memory copiado para new_payload.')

                                logger.info(f'[{contact_id}] - Copiando itens de response_craft_json["Final Answer"] para new_response_json.')
                                for k, v in response_craft_json['Final Answer'].items(): # Use .items() para iterar sobre dicionário
                                    new_response_json[k] = v
                                logger.info(f'[{contact_id}] - Cópia para new_response_json concluída. Conteúdo: {list(new_response_json.keys())}.')

                                if new_response_json.get('fast_messages_choosen_index'):
                                    logger.info(f'[{contact_id}] - "fast_messages_choosen_index" existe em new_response_json. Removendo mensagens primárias.')
                                    for index in new_response_json['fast_messages_choosen_index']:
                                        
                                        logger.debug(f'[{contact_id}] - Removendo índice {index} de primary_messages_sequence.')
                                        new_payload['primary_messages_sequence'].remove(payload['primary_messages_sequence'][index])
                                        
                                    logger.info(f'[{contact_id}] - Remoção de mensagens primárias do payload concluída.')

                                if 'proactive_content_choosen_index' in new_response_json and new_response_json['proactive_content_choosen_index']:
                                    logger.info(f'[{contact_id}] - "proactive_content_choosen_index" existe em new_response_json. Removendo conteúdo proativo.')
                                    for index in new_response_json['proactive_content_choosen_index']:
                                        
                                        logger.debug(f'[{contact_id}] - Removendo índice {index} de proactive_content_choosen_index.')
                                        response_delivery_json['proactive_content_choosen_index'].remove(payload['proactive_content_choosen_index'][index])
                                        
                                    logger.info(f'[{contact_id}] - Remoção de conteúdo proativo de new_response_json concluída.')

                                try:
                                    logger.info(f'[{contact_id}] - Fazendo upsert no Qdrant para FastMemoryMessages com ID: {point_memory.id}.')
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
                                    logger.info(f'[{contact_id}] - Upsert no Qdrant para FastMemoryMessages CONCLUÍDO.')
                                except Exception as e:
                                    logger.error(f'[{contact_id}] - ERRO ao fazer upsert no Qdrant para FastMemoryMessages (Final Answer): {e}', exc_info=True)

                            logger.info(f'[{contact_id}] - Iniciando processamento de mensagens restantes no Redis.')
                            try:
                                all_messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
                                logger.info(f'[{contact_id}] - Todas as mensagens na fila Redis antes da filtragem: {len(all_messages)} itens.')
                                messages_left = [x for x in all_messages if x not in last_messages_processed]
                                logger.info(f'[{contact_id}] - Mensagens restantes após filtragem (não processadas): {len(messages_left)} itens.')

                                pipe = redis_client.pipeline()
                                logger.info(f'[{contact_id}] - Pipeline Redis criado.')

                                pipe.delete(f'contacts_messages:waiting:{contact_id}')
                                logger.info(f'[{contact_id}] - Comando DELETE adicionado ao pipeline para contacts_messages:waiting:{contact_id}.')

                                if messages_left:
                                    pipe.rpush(f'contacts_messages:waiting:{contact_id}', *messages_left)
                                    logger.info(f'[{contact_id}] - Comando RPUSH adicionado ao pipeline para {len(messages_left)} mensagens restantes.')

                                pipe.execute()
                                logger.info(f'[{contact_id}] - Pipeline Redis EXECUTADO.')
                            except Exception as e:
                                logger.error(f'[{contact_id}] - ERRO durante o processamento das mensagens restantes no Redis: {e}', exc_info=True)

                        else:
                            logger.info(f'[{contact_id}] - response_delivery_json é vazio ou nulo. Chamando run_mvp_crew (condição principal).')
                            run_mvp_crew(contact_id, phone_number, redis_client, history)
                    
        else:
            logger.warning(f"MVP Crew: Nenhuma resposta gerada para contact_id {contact_id}")
    except Exception as e:
        logger.error(f"MVP Crew: Erro durante a execução do crew para contact_id {contact_id}: {e}", exc_info=True)