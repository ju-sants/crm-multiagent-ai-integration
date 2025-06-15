from crewai import Crew, Process, Task
import datetime
import json
import litellm
from qdrant_client import models
import uuid
from typing import Any, Dict
import redis
import copy


from app.agents.agent_declaration import *
from app.tasks.tasks_declaration import *

from app.tools.qdrant_tools import SaveFastMemoryMessages, FastMemoryMessages, GetUserProfile
from app.tools.cache_tools import L1CacheQueryTool

from app.services.qdrant_service import get_client
from app.services.telegram_service import send_single_telegram_message
from app.services.state_manager_service import StateManagerService
from app.services.eleven_labs_service import main as eleven_labs_service
from app.services.callbell_service import send_callbell_message
from app.services.redis_service import get_redis

from app.core.logger import get_logger

# =======================================================================
logger = get_logger(__name__)
redis_client = get_redis()


original_completition = litellm.completion

def patched_completition(*args, **kwargs):
    """
    Patch robusto para litellm.completion.
    Identifica o nome do modelo se foi passado como argumento posicional (args)
    ou nomeado (kwargs) e remove o parâmetro 'stop' APENAS para modelos 'grok'.
    """
    model_name = None

    if 'model' in kwargs:
        model_name = kwargs['model']
    elif args:
        model_name = args[0]

    model_name_str = str(model_name).lower() if model_name else ""

    if 'grok' in model_name_str and 'stop' in kwargs:
        print(f"PATCH ATIVO: Removendo parâmetro 'stop' para o modelo '{model_name}'.")
        kwargs.pop('stop')

    return original_completition(*args, **kwargs)

litellm.completion = patched_completition

state_manager = StateManagerService()


def parse_json_from_string(json_string, update=True):
    try:
        if '```json' in json_string:
                    json_string = json_string.split('```json')[-1].split('```')[0]
                
        if '```' in json_string:
            json_string = json_string.replace('```', '')
    
        json_response = json.loads(json_string)

        if 'task_output' and 'updated_state' in json_response and update:
            task_output = json_response['task_output']
            updated_state = json_response['updated_state']

            return task_output, updated_state
        
        elif not update:
            return json_response
        
        return json_response, None
    except json.JSONDecodeError as e:
        return None, None

def distill_conversation_state(agent_name: str, full_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Destila o objeto de estado completo, criando um "briefing" leve e de alta qualidade
    para um agente específico.
    """
    if not isinstance(full_state, dict):
        return {}

    # --- Componentes Base ---
    distilled_state = {
        "metadata": {
            "current_turn_number": full_state.get("metadata", {}).get("current_turn_number")
        },
        "current_context": full_state.get("current_context"),
        "communication_preference": full_state.get("communication_preference")
    }

    # --- Destilação Específica por Agente ---


    if agent_name == "ContextAnalysisAgent":
        distilled_state['strategic_plan'] = full_state.get("strategic_plan")

        distilled_state["session_summary"] = full_state.get("session_summary", "")

        all_entities = full_state.get("entities_extracted", [])
        
        high_value_entities = [
            entity for entity in all_entities 
            if entity and entity.get("entity") not in ["greeting", "confirmation"]
        ]
        distilled_state["recent_key_entities"] = high_value_entities[-7:]

        disclosure_items = full_state.get("disclosure_checklist", [])
        if disclosure_items:
            distilled_state["checklist_status_summary"] = {
                "total_items": len(disclosure_items),
                "items_communicated": sum(1 for item in disclosure_items if item and item.get("status") == "communicated")
            }


    elif agent_name == "StrategicAdvisor":
        distilled_state["session_summary"] = full_state.get("session_summary")
        
        entities = full_state.get("entities_extracted", [])
        key_entities_map = {}
        for entity in reversed(entities): # Começa do mais recente
            if entity and entity.get("entity") not in key_entities_map:
                key_entities_map[entity.get("entity")] = entity.get("value")
        
        distilled_state["current_key_entities"] = {
            "customer_name": key_entities_map.get("customer_name"),
            "vehicle_type": key_entities_map.get("vehicle_type"),
            "use_case": key_entities_map.get("use_case"),
            "key_concern": key_entities_map.get("key_concern")
        }

        # Sintetiza os produtos discutidos para uma lista de nomes únicos, evitando redundância.
        discussed_plan_names = [p.get("plan_name") for p in full_state.get("products_discussed", []) if p]
        if discussed_plan_names:
            distilled_state["products_being_discussed"] = list(set(discussed_plan_names))

        distilled_state['disclosure_checklist'] = full_state.get("disclosure_checklist", [])
        
    elif agent_name == "CommunicationAgent":
        entities = full_state.get("entities_extracted", [])
        distilled_state["customer_name"] = next((e.get("value") for e in reversed(entities) if e.get("entity") == "customer_name"), None)
        
        user_sentiment_history = full_state.get("user_sentiment_history", [])
        last_sentiment_entry = user_sentiment_history[-1] if user_sentiment_history else {}
        distilled_state["sentiment_of_last_turn"] = last_sentiment_entry.get("sentiment")

    return distilled_state


def distill_customer_profile(full_profile: dict) -> dict:
    """
    Recebe o perfil completo de longo prazo e o destila em um "briefing"
    leve para ser usado pelos agentes.
    """
    if not full_profile:
        return None

    distilled_profile = {
        "contact_id": full_profile.get("contact_id"),
        "customer_identity": full_profile.get("customer_identity"),
        "executive_summary": full_profile.get("executive_summary"),
        "strategic_insights": full_profile.get("strategic_insights"),
        "assets": full_profile.get("assets")
    }

    timeline = full_profile.get("relationship_timeline", [])
    distilled_profile["recent_timeline_events"] = timeline[-5:]

    return distilled_profile


def run_mvp_crew(contact_id: str, phone_number: str, redis_client: redis.Redis, history: Any):

    # litellm._turn_on_debug()

    mensagem = '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1))
    logger.info(f"MVP Crew: Iniciando processamento para contact_id: {contact_id}, mensagem: '{mensagem}'")

    contact_data = redis_client.hgetall(f"contact:{contact_id}")
    if not contact_data:
        redis_client.hset(f"contact:{contact_id}", mapping={"system_input": "nenhum"})

    history_messages = ''
    if history:
        history_messages = '\n'.join([f'{"AI" if "Alessandro" in str(message.get("text", "")) else "collaborator" if not message.get("status", "") == "received" else "customer"} - {message.get("text")}' if message.get("text") else '' for message in reversed(history.get('messages', [])[:10])])
    
    state = state_manager.get_state(contact_id)
    state["user_sentiment_history"] = state.get("user_sentiment_history", [])[-5:]

    state["metadata"]["current_turn_number"] += 1

    if 'disclousure_checklist' not in state:
        state["disclousure_checklist"] = []
    
    if 'communication_preference' not in state:
        state["communication_preference"] = {
                "prefers_audio": False,
                "reason": "default"
          },

    jump_to_registration_task = False
    registration_task = False
    
    
    if redis_client.get(f"{contact_id}:getting_data_from_user") and redis_client.get(f"{contact_id}:plan_details"):
        jump_to_registration_task = True
    
    if not jump_to_registration_task:
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
        "l2_cache": str(FastMemoryMessages()._run(contact_id)),
        "history": history_messages,
        "conversation_state": str(state),
        "turn": state["metadata"]["current_turn_number"]
        }

        logger.info(f"MVP Crew: Executando kickoff com inputs: {inputs_triage}")
        triage_crew.kickoff(inputs_triage)
        logger.info(f"MVP Crew: Kickoff executado com sucesso para contact_id {contact_id}")

        response_triage = triage_task.output.raw
        logger.info(f"MVP Crew: Resposta gerada pelo crew: {response_triage}")

        if response_triage:
            json_response, updated_state = parse_json_from_string(response_triage)
            
            if json_response:
        
                if redis_client.get(f"{contact_id}:getting_data_from_user"):
                    json_response['operational_context'] = 'BUDGET_ACCEPTED'
                    
                if 'operational_context' in json_response and json_response['operational_context'] == 'BUDGET_ACCEPTED':
                    registration_task = True
                    redis_client.set(f"{contact_id}:plan_details", json_response.get('plan_details', ""))

            if updated_state and isinstance(updated_state, dict):
                state_manager.save_state(contact_id, updated_state)
                state = updated_state
                state["user_sentiment_history"] = state.get("user_sentiment_history", [])[-5:]

        else:
            logger.warning(f"MVP Crew: Nenhuma resposta gerada para contact_id {contact_id}")
    

    if registration_task or jump_to_registration_task:
        qdrant_client = get_client()

        if not redis_client.get(f"{contact_id}:confirmed_plan") and 'json_response' in locals() and json_response:
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
                "message_text_original": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
                "operational_context": json_response.get('operational_context', ''),
                "identified_topic": json_response.get('identified_topic', ''),
                "customer_profile": str(GetUserProfile()._run(contact_id)),
                "history": history_messages,
                "contact_id": contact_id,
                "conversation_state": str(state),
                "timestamp": datetime.datetime.now().isoformat(),
                "turn": state["metadata"]["current_turn_number"]
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
                
        if not qdrant_client.collection_exists("CustomersDataForSignUp"):
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
        
        plan_details = redis_client.get(f"{contact_id}:plan_details")
        
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
            "plan_details": str(plan_details),
            "turn": state["metadata"]["current_turn_number"],
            "timestamp": datetime.datetime.now().isoformat(),
            "conversation_state": str(state),
        }

        registration_crew.kickoff(inputs_for_registration)
        
        registration_task_str = registration_task.output.raw
        registration_task_json, updated_state = parse_json_from_string(registration_task_str)
        
        if updated_state and isinstance(updated_state, dict):
            state = updated_state
            state["user_sentiment_history"] = state.get("user_sentiment_history", [])[-5:]

            state_manager.save_state(contact_id, state)

        if registration_task_json and all([registration_task_json.get("is_data_collection_complete"), registration_task_json.get("status") == 'COLLECTION_COMPLETE']):
            send_single_telegram_message(registration_task_str, '-4854533163')
            redis_client.delete(f"{contact_id}:getting_data_from_user")
        
        elif registration_task_json and "next_message_to_send" in registration_task_json and registration_task_json["next_message_to_send"]:
            send_callbell_message(phone_number=phone_number, messages=[registration_task_json["next_message_to_send"]])
            
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
                "history": history_messages,
                "conversation_state": str(state),
                "timestamp": datetime.datetime.now().isoformat(),
                "turn": state["metadata"]["current_turn_number"]
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
            
            profile_customer_task_json, updated_state = parse_json_from_string(profile_customer_task.output.raw)
            if updated_state and isinstance(updated_state, dict):
                state = updated_state
                state["user_sentiment_history"] = state.get("user_sentiment_history", [])[-5:]
                state_manager.save_state(contact_id, state)

            inputs_strategic = {
                "profile_customer_task_output": str(profile_customer_task_json),
                "message_text_original": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
                "operational_context": json_response.get('operational_context', ''),
                "identified_topic": json_response.get('identified_topic', ''),
                "conversation_state": str(state),
                "timestamp": datetime.datetime.now().isoformat(),
                "turn": state["metadata"]["current_turn_number"]
            }
            
            crew_strategic.kickoff(inputs_strategic)
            
            # Saving Profile and Strategic Plan
            qdrant_client = get_client()
            
            strategic_advise_task_str = strategic_advise_task.output.raw
            strategic_advise_task_json, updated_state = parse_json_from_string(strategic_advise_task_str)

            if updated_state and isinstance(updated_state, dict):
                state = updated_state
                state["user_sentiment_history"] = state.get("user_sentiment_history", [])[-5:]
                state_manager.save_state(contact_id, state)

            payload = {
                'profile_customer': profile_customer_task_json,
                'strategic_plan': strategic_advise_task_json,
            }


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

            recently_sent_catalogs = []
            for k in redis_client.keys(f"contact:{contact_id}:sendend_catalog_*"):
                recently_sent_catalogs.append(k.split("sendend_catalog_")[-1])
            

            inputs_craft = {
                "develop_strategy_task_output": str(strategic_advise_task_json),
                "profile_customer_task_output": str(profile_customer_task_json),
                "message_text_original": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
                "operational_context": json_response.get('operational_context', ''),
                "identified_topic": json_response.get('identified_topic', ''),
                "recently_sent_catalogs": ', '.join(recently_sent_catalogs),
                "conversation_state": str(state),
                "timestamp": datetime.datetime.now().isoformat(),
                "turn": state["metadata"]["current_turn_number"]
            }

            
            crew_craft_messages.kickoff(inputs_craft)
            
            response_craft_json = None
            response_craft_str = response_craft_task.output.raw

            response_craft_json, updated_state = parse_json_from_string(response_craft_str)

            if updated_state and isinstance(updated_state, dict):
                state = updated_state
                state["user_sentiment_history"] = state.get("user_sentiment_history", [])[-5:]
                state_manager.save_state(contact_id, state)
                
            redo = False
            if response_craft_json:
                if 'Final Answer' in response_craft_json:
                    if not 'primary_messages_sequence' in response_craft_json.get('Final Answer', {}):
                        redo = True
                    
                    if not 'primary_messages_sequence' in response_craft_json:
                        redo = True

                    else:
                        primary_messages = response_craft_json['Final Answer']['primary_messages_sequence']
                        proactive_content = response_craft_json['Final Answer'].get('proactive_content_generated', [])
                        
                        del response_craft_json['Final Answer']
                        
                        response_craft_json['primary_messages_sequence'] = primary_messages
                        response_craft_json['proactive_content_generated'] = proactive_content
                
                plan = response_craft_json.get('plan_names', [])
                if plan:
                    redis_client.hset(f'contact:{contact_id}', 'plan', ', '.join(plan))
                    
            else:
                redo = True
                
            
            if redo:
                run_mvp_crew(contact_id, phone_number, redis_client, history)
            
            else:
                response_craft_json['contact_id'] = contact_id
                
                SaveFastMemoryMessages()._run(
                    response_craft_json,
                    contact_id
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
        
        plans = redis_client.hget(f'contact:{contact_id}', 'plan')
        if plans:
            if ', ' in plans:
                plans = plans.split(', ')
            else:
                plans = [plans]
            
            messages_plans_to_send = []
            plans_names_to_send = []
            for plan in plans:
                if not redis_client.get(f"contact:{contact_id}:sendend_catalog_{plan}"):
                    plans_messages = {
                "MOTO GSM/PGS": """
MOTO GSM/PGS

🛵🏍️ Para sua moto, temos duas opções incríveis:

Link do Catálogo Visual: Acesse e confira todos os detalhes:
https://wa.me/p/9380524238652852/558006068000

Adesão Única: R$ 120,00

Plano Rastreamento (sem cobertura FIPE):
Apenas R$ 60/mês, com plantão 24h incluso para sua segurança!

Plano Proteção Total PGS (com cobertura FIPE):
Com este plano, se não recuperarmos sua moto, você recebe o valor da FIPE!
    Até R$ 15 mil: R$ 77/mês
    De R$ 16 a 22 mil: R$ 85/mês
    De R$ 23 a 30 mil: R$ 110/mês
""",
                "GSM Padrão": """
GSM Padrão

🚗 Nosso Plano GSM Padrão é ideal para seu veículo!

    Adesão: R$ 200,00
    Mensalidade:
        Sem bloqueio: R$ 65/mês
        Com bloqueio: R$ 75/mês

Confira mais detalhes no nosso catálogo:
https://wa.me/p/9356355621125950/558006068000""",
                "GSM FROTA": """
GSM FROTA

🚚 Gerencie sua frota com eficiência e segurança!

Conheça nosso Plano GSM FROTA: https://wa.me/p/9321097734636816/558006068000
""",
                "SATELITAL FROTA": """
SATELITAL FROTA

🌍 Para sua frota, conte com a alta precisão do nosso Plano SATELITAL FROTA!

Confira os detalhes: https://wa.me/p/9553408848013955/558006068000
""",
                "HÍBRIDO": """
HÍBRIDO

📡 O melhor dos dois mundos para seu rastreamento!

Descubra o Plano HÍBRIDO: https://wa.me/p/8781199928651103/558006068000
""",
                "GSM+WiFi": """
GSM+WiFi

📶 Conectividade e segurança aprimoradas para sua fazenda!

Saiba mais sobre o Plano GSM+WiFi: https://wa.me/p/9380395508713863/558006068000
""",
                "Scooters/Patinetes": """
Scooters/Patinetes

🛴 Mantenha seus veículos de mobilidade pessoal sempre seguros!

    Plano exclusivo para Scooters e Patinetes: https://wa.me/p/8478546275590970/558006068000
"""
            }
                    
                    if plan in plans_messages:
                        messages_plans_to_send.append(plans_messages[plan])
                        plans_names_to_send.append(plan)

                messages_join = '\n\n'.join(messages_plans_to_send)
                system_input = f"""
o sistema enviará o(s) catálogo(s) do(s) plano(s) {', '.join(plans_names_to_send)} para o cliente, conte com isso em suas mensagens, mensagem que será enviada:

{messages_join}
"""
                redis_client.hset(f"contact:{contact_id}", 'system_input', system_input)    
            

        if memory and profile:
            history_messages = ''
            if history:
                history_messages = '\n'.join([f'{"AI" if "Alessandro" in str(message.get("text", "")) else "collaborator" if not message.get("status") == "received" else "customer"} - {message.get("text")}' for message in reversed(history.get('messages', [])[:5])])
            
            last_messages_processed = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
            
            inputs_delivery_crew = {
                "identified_topic": json_response.get('identified_topic', ''),
                "operational_context": json_response.get('operational_context', ''),
                "message_text_original": '\n'.join(last_messages_processed),
                "primary_messages_sequence": json.dumps(memory.get('primary_messages_sequence', ''), indent=4),
                "proactive_content_generated": json.dumps(memory.get('proactive_content_generated', ''), indent=4),
                "client_profile": str(profile.get('profile_customer', '')),
                "history": history_messages,
                "timestamp": datetime.datetime.now().isoformat(),
                "conversation_state": str(state),
                "turn": state["metadata"]["current_turn_number"]
            }
            
                                
            delivery_crew.kickoff(inputs_delivery_crew)
            
            response_delivery_str = delivery_coordinator_task.output.raw
            response_delivery_json, updated_state = parse_json_from_string(response_delivery_str)

            if updated_state and isinstance(updated_state, dict):
                state = updated_state
                state["user_sentiment_history"] = state.get("user_sentiment_history", [])[-5:]
                state_manager.save_state(contact_id, state)

            if response_delivery_json:
                logger.info(f'[{contact_id}] - response_delivery_json existe.')

                if not 'primary_messages_sequence_choosen_index' in response_delivery_json:
                    logger.info(f'[{contact_id}] - "primary_messages_sequence_choosen_index" NÃO está em response_delivery_json. Chamando run_mvp_crew.')
                    run_mvp_crew(contact_id, phone_number, redis_client, history)
                else:
                    logger.info(f'[{contact_id}] - "primary_messages_sequence_choosen_index" está em response_delivery_json. Prosseguindo com a lógica de order/Final Answer.')

                payload = point_memory.payload.copy()
                if 'order' in response_delivery_json:
                    logger.info(f'[{contact_id}] - "order" encontrado em response_delivery_json. Enviando mensagens Callbell.')

                    try:
                        if state.get('communication_preference').get("prefers_audio"):
                            logger.info(f'[{contact_id}] - "prefers_audio" encontrado em state. Enviando mensagem de áudio.')
                            audio_url = eleven_labs_service(response_delivery_json['order'])
                            send_callbell_message(phone_number=phone_number, type="audio", audio_url=audio_url)

                        
                        else:
                        
                            has_long_message = False
                            for message in response_delivery_json['order']:
                                if len(message) > 250:
                                    has_long_message = True
                            
                            if has_long_message and not all([len(message) > 250 for message in response_delivery_json['order']]):
                                logger.info(f"[{contact_id}] - Encontrada mensagem com mais de 250 caracteres. Enviando mensagem de áudio.")
                                            
                                for message in response_delivery_json['order']:
                                    if len(message) > 250:
                                        audio_url = eleven_labs_service([message])
                                        send_callbell_message(phone_number=phone_number, type="audio", audio_url=audio_url)
                                        redis_client.hset(f"{contact_id}:attachments", audio_url, message)

                                    else:
                                        send_callbell_message(phone_number=phone_number, messages=[message])
                            
                            else:
                                logger.info(f"[{contact_id}] - Não encontrada mensagem com mais de 250 caracteres.")
                                
                                messages_all_str = '\n'.join(response_delivery_json['order'])
                                if len(messages_all_str) > 300:
                                    logger.info(f"[{contact_id}] - Todas as mensagens somam mais de 300 caracteres. Enviando mensagem de áudio.")

                                    audio_url = eleven_labs_service(messages_all_str)
                                    send_callbell_message(phone_number=phone_number, type="audio", audio_url=audio_url)
                                    redis_client.hset(f"{contact_id}:attachments", audio_url, messages_all_str)
                                else:
                                    logger.info(f"[{contact_id}] - Todas as mensagens somam menos de 300 caracteres. Enviando mensagens de texto.")
                                    send_callbell_message(phone_number=phone_number, messages=response_delivery_json['order'])

                    except Exception as e:
                        logger.error(f'[{contact_id}] - Erro ao enviar mensagens para Callbell: {e}')


                    new_payload = point_memory.payload.copy()
                    logger.info(f'[{contact_id}] - Payload de point_memory copiado para new_payload.')

                    if response_delivery_json['primary_messages_sequence_choosen_index']:
                        logger.info(f'[{contact_id}] - "primary_messages_sequence_choosen_index" existe e não está vazio. Removendo mensagens primárias.')
                        for index in response_delivery_json['primary_messages_sequence_choosen_index']:
                            
                            try:
                                logger.debug(f'[{contact_id}] - Removendo índice {index} de primary_messages_sequence.')
                                new_payload['primary_messages_sequence'].remove(payload['primary_messages_sequence'][index])
                            except (ValueError, IndexError) as e:
                                logger.error(f"[{contact_id}] - Índice {index} não encontrado em primary_messages_sequence.")

                        logger.info(f'[{contact_id}] - Remoção de mensagens primárias concluída.')

                    if 'proactive_content_choosen_index' in response_delivery_json and response_delivery_json['proactive_content_choosen_index']:
                        logger.info(f'[{contact_id}] - "proactive_content_choosen_index" existe e não está vazio. Removendo conteúdo proativo.')
                        for index in response_delivery_json['proactive_content_choosen_index']:
                            
                            try:
                                logger.debug(f'[{contact_id}] - Removendo índice {index} de proactive_content_choosen_index.')
                                new_payload['proactive_content_generated'].remove(payload['proactive_content_generated'][index])
                            except (ValueError, IndexError) as e:
                                logger.error(f"[{contact_id}] - Erro ao remover índice {index} de proactive_content_generated: {e}", exc_info=True)

                        logger.info(f'[{contact_id}] - Remoção de conteúdo proativo concluída.')

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
                        logger.error(f'[{contact_id}] - ERRO ao fazer upsert no Qdrant para FastMemoryMessages: {e}', exc_info=True)

                elif 'Final Answer' in response_delivery_json and 'choosen_messages' in response_delivery_json['Final Answer']:
                    logger.info(f'[{contact_id}] - "Final Answer" e "choosen_messages" encontrados em response_delivery_json. Enviando mensagens Callbell.')
                    try:
                        send_callbell_message(phone_number=phone_number, messages=response_delivery_json['Final Answer']['choosen_messages'])
                        logger.info(f'[{contact_id}] - Mensagens do "Final Answer" enviadas via CallbellSendTool.')
                    except Exception as e:
                        logger.error(f'[{contact_id}] - ERRO ao enviar mensagens do "Final Answer" via CallbellSendTool: {e}', exc_info=True)

                    new_response_json = {}
                    new_payload = point_memory.payload.copy()
                    logger.info(f'[{contact_id}] - Payload de point_memory copiado para new_payload.')

                    logger.info(f'[{contact_id}] - Copiando itens de response_craft_json["Final Answer"] para new_response_json.')
                    for k, v in response_craft_json['Final Answer'].items():
                        new_response_json[k] = v
                    logger.info(f'[{contact_id}] - Cópia para new_response_json concluída. Conteúdo: {list(new_response_json.keys())}.')

                    if new_response_json.get('primary_messages_sequence_choosen_index'):
                        logger.info(f'[{contact_id}] - "primary_messages_sequence_choosen_index" existe em new_response_json. Removendo mensagens primárias.')
                        for index in new_response_json['primary_messages_sequence_choosen_index']:
                            
                            try:
                                logger.debug(f'[{contact_id}] - Removendo índice {index} de primary_messages_sequence.')
                                new_payload['primary_messages_sequence'].remove(payload['primary_messages_sequence'][index])
                            except (ValueError, IndexError) as e:
                                logger.error(f"[{contact_id}] - Índice {index} não encontrado em primary_messages_sequence.")

                        logger.info(f'[{contact_id}] - Remoção de mensagens primárias do payload concluída.')

                    if 'proactive_content_choosen_index' in new_response_json and new_response_json['proactive_content_choosen_index']:
                        logger.info(f'[{contact_id}] - "proactive_content_choosen_index" existe em new_response_json. Removendo conteúdo proativo.')
                        for index in new_response_json['proactive_content_choosen_index']:
                            
                            try:
                                logger.debug(f'[{contact_id}] - Removendo índice {index} de proactive_content_choosen_index.')
                                new_payload['proactive_content_generated'].remove(payload['proactive_content_generated'][index])
                            except (ValueError, IndexError) as e:
                                logger.error(f"[{contact_id}] - Índice {index} não encontrado em proactive_content_generated.")

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

                if 'messages_plans_to_send' in locals() and 'plans_names_to_send' in locals() and messages_plans_to_send and plans_names_to_send:
                    send_callbell_message(phone_number=phone_number, messages=messages_plans_to_send)

                    for plan in plans_names_to_send:
                        redis_client.set(f"contact:{contact_id}:sendend_catalog_{plan}", "1")

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

def run_mvp_crew_2(contact_id: str, phone_number: str, redis_client: redis.Redis, history: Any):

    # litellm._turn_on_debug()

    mensagem = '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1))
    logger.info(f"MVP Crew: Iniciando processamento para contact_id: {contact_id}, mensagem: '{mensagem}'")

    contact_data = redis_client.hgetall(f"contact:{contact_id}")
    if not contact_data:
        redis_client.hset(f"contact:{contact_id}", mapping={"system_input": "nenhum"})

    history_messages = ''
    if history:
        for message in reversed(history.get('messages', [])[:10]):
            if message.get("text"):
                history_messages += f'{"AI" if "Alessandro" in str(message.get("text", "")) else "collaborator" if not message.get("status", "") == "received" else "customer"} - {message.get("text")}\n'
            elif message.get("attachments"):
                attachments = message.get("attachments", [])

                list_of_dicts = False
                if isinstance(attachments[0], dict):
                    list_of_dicts = True
                
                elif isinstance(attachments[0], str):
                    list_of_dicts = False

                for attachment in attachments:
                    raw_url = attachment.get("payload", {}).get('url', '') if list_of_dicts else attachment

                    if "audio_eleven_agent_AI" in raw_url:
                        url = raw_url

                    else:
                        url = raw_url.split('uploads/')[1].split('?')[0] if 'uploads/' in raw_url else ''

                    if url:
                        mapped_attachments = redis_client.hgetall(f"{contact_id}:attachments")
                        if mapped_attachments:
                            attachment_text = mapped_attachments.get(url, "")
                            if attachment_text:
                                history_messages += f'{"AI" if message.get("status", "") == "sent" and "audio_eleven_agent_AI" in url else "collaborator" if not message.get("status", "") == "received" else "customer"} - {attachment_text}\n'

    state = state_manager.get_state(contact_id)

    state["metadata"]["current_turn_number"] += 1

    jump_to_registration_task = False
    registration_task = False
    
    
    if redis_client.get(f"{contact_id}:getting_data_from_user") and redis_client.get(f"{contact_id}:plan_details"):
        jump_to_registration_task = True
    
    if not jump_to_registration_task:
        context_analisys_agent_instance = get_context_analysis_agent()

        context_analisys_task: Task = create_context_analysis_task(context_analisys_agent_instance)

        triage_crew = Crew(
            agents=[
                context_analisys_agent_instance,
            ],
            tasks=[
                context_analisys_task,
            ],
            process=Process.sequential,
            verbose=True,
            planning=False,
        )

        inputs_context_analysis = {
        "contact_id": contact_id,
        "message_text": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
        "timestamp": datetime.datetime.now().isoformat(), 
        "l0l1_cache": str(L1CacheQueryTool()._run(contact_id)),
        "l2_cache": str(redis_client.get(f'{contact_id}:fast_memory_messages')),
        "history": history_messages,
        "conversation_state": str(distill_conversation_state('ContextAnalysisAgent', state)),
        "turn": state["metadata"]["current_turn_number"],
        "customer_profile": str(redis_client.get(f"{contact_id}:customer_profile")),
        }

        logger.info(f"MVP Crew: Executando kickoff com inputs: {inputs_context_analysis}")
        triage_crew.kickoff(inputs_context_analysis)
        logger.info(f"MVP Crew: Kickoff executado com sucesso para contact_id {contact_id}")

        response_context = context_analisys_task.output.raw
        logger.info(f"MVP Crew: Resposta gerada pelo crew: {response_context}")

        if response_context:
            json_response, updated_state = parse_json_from_string(response_context)
            
            if json_response:
                
                if redis_client.get(f"{contact_id}:getting_data_from_user"):
                    json_response['operational_context'] = 'BUDGET_ACCEPTED'
                    
                if 'operational_context' in json_response and json_response['operational_context'] == 'BUDGET_ACCEPTED':
                    registration_task = True
                    redis_client.set(f"{contact_id}:plan_details", json_response.get('plan_details', ""))

                if 'profile' in json_response:
                    redis_client.set(f"{contact_id}:customer_profile", json.dumps(json_response['profile']))

            else:
                logger.warning(f"MVP Crew: Nenhuma resposta JSON válida gerada para contact_id {contact_id}")
                run_mvp_crew_2(contact_id, phone_number, redis_client, history)
                return
            
            if updated_state and isinstance(updated_state, dict):
                
                for k in updated_state:                    
                    if k in ['user_sentiment', 'entities_extracted'] and k in state:
                        state[k].extend(updated_state[k])
                    
                    else:
                        state[k] = updated_state[k]

                state_manager.save_state(contact_id, state)

        else:
            logger.warning(f"MVP Crew: Nenhuma resposta gerada para contact_id {contact_id}")
    

    if registration_task or jump_to_registration_task:
        user_data_so_far = redis_client.get(f"{contact_id}:user_data_so_far")
        
        plan_details = redis_client.get(f"{contact_id}:plan_details")
        
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
            "plan_details": str(plan_details),
            "turn": state["metadata"]["current_turn_number"],
            "timestamp": datetime.datetime.now().isoformat(),
            "conversation_state": str(distill_conversation_state('RegistrationAgent', state)),
        }

        registration_crew.kickoff(inputs_for_registration)
        
        registration_task_str = registration_task.output.raw
        registration_task_json, updated_state = parse_json_from_string(registration_task_str)
        
        if updated_state and isinstance(updated_state, dict):
            state = updated_state

            state_manager.save_state(contact_id, state)

        redis_client.set(f"{contact_id}:user_data_so_far", json.dumps(registration_task_json))

        if registration_task_json and all([registration_task_json.get("is_data_collection_complete"), registration_task_json.get("status") == 'COLLECTION_COMPLETE']):
            send_single_telegram_message(registration_task_str, '-4854533163')
            redis_client.delete(f"{contact_id}:getting_data_from_user")
        
        elif registration_task_json and "next_message_to_send" in registration_task_json and registration_task_json["next_message_to_send"]:
            send_callbell_message(phone_number=phone_number, messages=[registration_task_json["next_message_to_send"]])
            
            redis_client.set(f"{contact_id}:getting_data_from_user", "1")
    else:
        redis_client.delete(f"{contact_id}:confirmed_plan")

        if json_response and 'action' in json_response and json_response['action'] == "INITIATE_FULL_PROCESSING":
            logger.info(f"MVP Crew: Iniciando processamento completo para contact_id {contact_id}")

            if not json_response.get('is_plan_acceptable'):
                strategic_advisor_instance = get_strategic_advisor_agent()
                
                strategic_advise_task = create_develop_strategy_task(strategic_advisor_instance)
                
                logger.info(f"MVP Crew: Iniciando processamento completo para contact_id {contact_id}")

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
                    "profile_customer_task_output": str(redis_client.get(f"{contact_id}:customer_profile")),
                    "message_text_original": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
                    "operational_context": json_response.get('operational_context', ''),
                    "identified_topic": json_response.get('identified_topic', ''),
                    "conversation_state": str(distill_conversation_state('StrategicAdvisor', state)),
                    "timestamp": datetime.datetime.now().isoformat(),
                    "turn": state["metadata"]["current_turn_number"]
                }
                
                crew_strategic.kickoff(inputs_strategic)
                
                strategic_advise_task_str = strategic_advise_task.output.raw
                strategic_advise_task_json, updated_state = parse_json_from_string(strategic_advise_task_str)

                redis_client.set(f"{contact_id}:strategic_plan", strategic_advise_task_str)

                if updated_state and isinstance(updated_state, dict):
                    for k in updated_state:
                        state[k] = updated_state[k]

                    state['strategic_plan'] = strategic_advise_task_json

                    state_manager.save_state(contact_id, state)
            # ===============================================
                
            # Craftando mensagens
            response_craftman_instance = get_response_craftsman_agent()
            response_craft_task = create_craft_response_task(response_craftman_instance)

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

            recently_sent_catalogs = []
            for k in redis_client.keys(f"contact:{contact_id}:sendend_catalog_*"):
                recently_sent_catalogs.append(k.split("sendend_catalog_")[-1])
            

            inputs_craft = {
                "develop_strategy_task_output": str(redis_client.get(f"{contact_id}:strategic_plan")),
                "profile_customer_task_output": str(redis_client.get(f"{contact_id}:customer_profile")),
                "message_text_original": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
                "operational_context": json_response.get('operational_context', ''),
                "identified_topic": json_response.get('identified_topic', ''),
                "recently_sent_catalogs": ', '.join(recently_sent_catalogs),
                "conversation_state": str(distill_conversation_state('ResponseCraftsman', state)),
                "timestamp": datetime.datetime.now().isoformat(),
                "turn": state["metadata"]["current_turn_number"],
                "history": history_messages
            }

            
            crew_craft_messages.kickoff(inputs_craft)
            
            response_craft_json = None
            response_craft_str = response_craft_task.output.raw

            response_craft_json = parse_json_from_string(response_craft_str, update=False)

            redo = False
            if response_craft_json:
                if 'Final Answer' in response_craft_json:
                    if not 'primary_messages_sequence' in response_craft_json.get('Final Answer', {}):
                        redo = True
                    
                    if not 'primary_messages_sequence' in response_craft_json:
                        redo = True

                    else:
                        primary_messages = response_craft_json['Final Answer']['primary_messages_sequence']
                        proactive_content = response_craft_json['Final Answer'].get('proactive_content_generated', [])
                        
                        del response_craft_json['Final Answer']
                        
                        response_craft_json['primary_messages_sequence'] = primary_messages
                        response_craft_json['proactive_content_generated'] = proactive_content
                
                plan = response_craft_json.get('plan_names', [])
                if plan:
                    redis_client.hset(f'contact:{contact_id}', 'plan', ', '.join(plan))
                    
            else:
                redo = True
                
            
            if redo:
                run_mvp_crew_2(contact_id, phone_number, redis_client, history)
            
            else:
                response_json_save = response_craft_json.copy()
                response_json_save['contact_id'] = contact_id

                if 'plan_names' in response_json_save:
                    del response_json_save['plan_names']

                redis_client.set(f'{contact_id}:fast_memory_messages', json.dumps(response_json_save))
        
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
        
        
        plans = redis_client.hget(f'contact:{contact_id}', 'plan')
        if plans:
            if ', ' in plans:
                plans = plans.split(', ')
            else:
                plans = [plans]
            
            messages_plans_to_send = []
            plans_names_to_send = []
            for plan in plans:
                if not redis_client.get(f"contact:{contact_id}:sendend_catalog_{plan}"):
                    plans_messages = {
                "MOTO GSM/PGS": """
MOTO GSM/PGS

🛵🏍️ Para sua moto, temos duas opções incríveis:

Link do Catálogo Visual: Acesse e confira todos os detalhes:
https://wa.me/p/9380524238652852/558006068000

Adesão Única: R$ 120,00

Plano Rastreamento (sem cobertura FIPE):
Apenas R$ 60/mês, com plantão 24h incluso para sua segurança!

Plano Proteção Total PGS (com cobertura FIPE):
Com este plano, se não recuperarmos sua moto, você recebe o valor da FIPE!
    Até R$ 15 mil: R$ 77/mês
    De R$ 16 a 22 mil: R$ 85/mês
    De R$ 23 a 30 mil: R$ 110/mês
""",
                "GSM Padrão": """
GSM Padrão

🚗 Nosso Plano GSM Padrão é ideal para seu veículo!

    Adesão: R$ 200,00
    Mensalidade:
        Sem bloqueio: R$ 65/mês
        Com bloqueio: R$ 75/mês

Confira mais detalhes no nosso catálogo:
https://wa.me/p/9356355621125950/558006068000""",
                "GSM FROTA": """
GSM FROTA

🚚 Gerencie sua frota com eficiência e segurança!

Conheça nosso Plano GSM FROTA: https://wa.me/p/9321097734636816/558006068000
""",
                "SATELITAL FROTA": """
SATELITAL FROTA

🌍 Para sua frota, conte com a alta precisão do nosso Plano SATELITAL FROTA!

Confira os detalhes: https://wa.me/p/9553408848013955/558006068000
""",
                "HÍBRIDO": """
HÍBRIDO

📡 O melhor dos dois mundos para seu rastreamento!

Descubra o Plano HÍBRIDO: https://wa.me/p/8781199928651103/558006068000
""",
                "GSM+WiFi": """
GSM+WiFi

📶 Conectividade e segurança aprimoradas para sua fazenda!

Saiba mais sobre o Plano GSM+WiFi: https://wa.me/p/9380395508713863/558006068000
""",
                "Scooters/Patinetes": """
Scooters/Patinetes

🛴 Mantenha seus veículos de mobilidade pessoal sempre seguros!

    Plano exclusivo para Scooters e Patinetes: https://wa.me/p/8478546275590970/558006068000
"""
            }
                    
                    if plan in plans_messages:
                        messages_plans_to_send.append(plans_messages[plan])
                        plans_names_to_send.append(plan)

                messages_join = '\n\n'.join(messages_plans_to_send)
                system_input = f"""
o sistema enviará o(s) catálogo(s) do(s) plano(s) {', '.join(plans_names_to_send)} para o cliente, conte com isso em suas mensagens, mensagem que será enviada:

{messages_join}
"""
                redis_client.hset(f"contact:{contact_id}", 'system_input', system_input)    
            
        # =============================================================================================================================
        last_messages_processed = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
        
        try:
            fast_memory_messages = json.loads(redis_client.get(f'{contact_id}:fast_memory_messages'))
        except:
            fast_memory_messages = {}

        primary_messages_sequence = fast_memory_messages.get('primary_messages_sequence', [])
        proactive_content_generated = fast_memory_messages.get('proactive_content_generated', [])

        inputs_delivery_crew = {
            "identified_topic": json_response.get('identified_topic', ''),
            "operational_context": json_response.get('operational_context', ''),
            "message_text_original": '\n'.join(last_messages_processed),
            "primary_messages_sequence": str(primary_messages_sequence),
            "proactive_content_generated": str(proactive_content_generated),
            "client_profile": redis_client.get(f'{contact_id}:customer_profile'),
            "history": history_messages,
            "timestamp": datetime.datetime.now().isoformat(),
            "conversation_state": str(distill_conversation_state('DeliveryCoordinator', state)),
            "turn": state["metadata"]["current_turn_number"]
        }
        
        delivery_crew.kickoff(inputs_delivery_crew)
        
        response_delivery_str = delivery_coordinator_task.output.raw
        response_delivery_json, updated_state = parse_json_from_string(response_delivery_str)

        if updated_state and isinstance(updated_state, dict):
            for k in updated_state:
                if k in ['products_discussed'] and k in state:
                    state[k].extend(updated_state[k])
                
                else:
                    state[k] = updated_state[k]

            state_manager.save_state(contact_id, state)

        if response_delivery_json:
            logger.info(f'[{contact_id}] - response_delivery_json existe.')

            if not 'primary_messages_sequence_choosen_index' in response_delivery_json:
                logger.info(f'[{contact_id}] - "primary_messages_sequence_choosen_index" NÃO está em response_delivery_json. Chamando run_mvp_crew_2.')
                run_mvp_crew_2(contact_id, phone_number, redis_client, history)
            else:
                logger.info(f'[{contact_id}] - "primary_messages_sequence_choosen_index" está em response_delivery_json. Prosseguindo com a lógica de order/Final Answer.')


            if 'order' in response_delivery_json:
                logger.info(f'[{contact_id}] - "order" encontrado em response_delivery_json. Enviando mensagens Callbell.')

                try:
                    if state.get('communication_preference').get("prefers_audio"):
                        logger.info(f'[{contact_id}] - "prefers_audio" encontrado em state. Enviando mensagem de áudio.')
                        audio_url = eleven_labs_service(response_delivery_json['order'])
                        send_callbell_message(phone_number=phone_number, type="audio", audio_url=audio_url)
                        redis_client.hset(f"{contact_id}:attachments", audio_url, ' '.join(response_delivery_json['order']))
                    
                    else:
                    
                        has_long_message = False
                        for message in response_delivery_json['order']:
                            if len(message) > 250:
                                has_long_message = True
                        
                        if has_long_message and not all([len(message) > 250 for message in response_delivery_json['order']]):
                            logger.info(f"[{contact_id}] - Encontrada mensagem com mais de 250 caracteres. Enviando mensagem de áudio.")
                                        
                            for message in response_delivery_json['order']:
                                if len(message) > 250:
                                    audio_url = eleven_labs_service([message])
                                    send_callbell_message(phone_number=phone_number, type="audio", audio_url=audio_url)
                                    redis_client.hset(f"{contact_id}:attachments", audio_url, message)

                                else:
                                    send_callbell_message(phone_number=phone_number, messages=[message])
                        
                        else:
                            logger.info(f"[{contact_id}] - Não encontrada mensagem com mais de 250 caracteres.")
                            
                            messages_all_str = '\n'.join(response_delivery_json['order'])
                            if len(messages_all_str) > 300:
                                logger.info(f"[{contact_id}] - Todas as mensagens somam mais de 300 caracteres. Enviando mensagem de áudio.")

                                audio_url = eleven_labs_service(response_delivery_json['order'])
                                send_callbell_message(phone_number=phone_number, type="audio", audio_url=audio_url)
                                redis_client.hset(f"{contact_id}:attachments", audio_url, messages_all_str)
                            else:
                                logger.info(f"[{contact_id}] - Todas as mensagens somam menos de 300 caracteres. Enviando mensagens de texto.")
                                send_callbell_message(phone_number=phone_number, messages=response_delivery_json['order'])

                except Exception as e:
                    logger.error(f'[{contact_id}] - Erro ao enviar mensagens para Callbell: {e}')

                if fast_memory_messages:
                    new_payload = copy.deepcopy(fast_memory_messages)
                    logger.info(f'[{contact_id}] - Payload de point_memory copiado para new_payload.')

                    if response_delivery_json['primary_messages_sequence_choosen_index']:
                        logger.info(f'[{contact_id}] - "primary_messages_sequence_choosen_index" existe e não está vazio. Removendo mensagens primárias.')
                        logger.info(f'[{contact_id}] - {fast_memory_messages["primary_messages_sequence"]}')
                        for index in response_delivery_json['primary_messages_sequence_choosen_index']:
                            
                            try:
                                logger.info(f'[{contact_id}] - Removendo índice {index} de primary_messages_sequence. [{fast_memory_messages["primary_messages_sequence"][index]}]')
                                new_payload['primary_messages_sequence'].remove(fast_memory_messages['primary_messages_sequence'][index])
                            except (ValueError, IndexError) as e:
                                logger.error(f"[{contact_id}] - Índice {index} não encontrado em primary_messages_sequence.")

                        logger.info(f'[{contact_id}] - Remoção de mensagens primárias concluída.')

                    if 'proactive_content_choosen_index' in response_delivery_json and response_delivery_json['proactive_content_choosen_index']:
                        logger.info(f'[{contact_id}] - "proactive_content_choosen_index" existe e não está vazio. Removendo conteúdo proativo.')
                        logger.info(f'[{contact_id}] - {fast_memory_messages["proactive_content_generated"]}')
                        for index in response_delivery_json['proactive_content_choosen_index']:
                            
                            try:
                                logger.debug(f'[{contact_id}] - Removendo índice {index} de proactive_content_choosen. [{fast_memory_messages["proactive_content_generated"][index]}].')
                                new_payload['proactive_content_generated'].remove(fast_memory_messages['proactive_content_generated'][index])
                            except (ValueError, IndexError) as e:
                                logger.error(f"[{contact_id}] - Erro ao remover índice {index} de proactive_content_generated: {e}", exc_info=True)

                        logger.info(f'[{contact_id}] - Remoção de conteúdo proativo concluída.')

                    try:
                        logger.info(f'[{contact_id}] - upload no redis das novas mensagens.')
                        redis_client.set(f'{contact_id}:fast_memory_messages', json.dumps(new_payload))
                        logger.info(f'[{contact_id}] - Upsert no Qdrant para FastMemoryMessages CONCLUÍDO.')
                    except Exception as e:
                        logger.error(f'[{contact_id}] - ERRO ao fazer upsert no Qdrant para FastMemoryMessages: {e}', exc_info=True)

            elif 'Final Answer' in response_delivery_json and 'choosen_messages' in response_delivery_json['Final Answer']:
                logger.info(f'[{contact_id}] - "Final Answer" e "choosen_messages" encontrados em response_delivery_json. Enviando mensagens Callbell.')
                try:
                    send_callbell_message(phone_number=phone_number, messages=response_delivery_json['Final Answer']['choosen_messages'])
                    logger.info(f'[{contact_id}] - Mensagens do "Final Answer" enviadas via CallbellSendTool.')
                except Exception as e:
                    logger.error(f'[{contact_id}] - ERRO ao enviar mensagens do "Final Answer" via CallbellSendTool: {e}', exc_info=True)

                new_response_json = {}
                new_payload = copy.deepcopy(fast_memory_messages)
                logger.info(f'[{contact_id}] - Payload de point_memory copiado para new_payload.')

                logger.info(f'[{contact_id}] - Copiando itens de response_craft_json["Final Answer"] para new_response_json.')
                for k, v in response_craft_json['Final Answer'].items():
                    new_response_json[k] = v
                logger.info(f'[{contact_id}] - Cópia para new_response_json concluída. Conteúdo: {list(new_response_json.keys())}.')

                if new_response_json.get('primary_messages_sequence_choosen_index'):
                    logger.info(f'[{contact_id}] - "primary_messages_sequence_choosen_index" existe em new_response_json. Removendo mensagens primárias.')
                    for index in new_response_json['primary_messages_sequence_choosen_index']:
                        
                        try:
                            logger.info(f'[{contact_id}] - Removendo índice {index} de primary_messages_sequence.')
                            new_payload['primary_messages_sequence'].remove(fast_memory_messages['primary_messages_sequence'][index])
                        except (ValueError, IndexError) as e:
                            logger.error(f"[{contact_id}] - Índice {index} não encontrado em primary_messages_sequence.")

                    logger.info(f'[{contact_id}] - Remoção de mensagens primárias do payload concluída.')

                if 'proactive_content_choosen_index' in new_response_json and new_response_json['proactive_content_choosen_index']:
                    logger.info(f'[{contact_id}] - "proactive_content_choosen_index" existe em new_response_json. Removendo conteúdo proativo.')
                    for index in new_response_json['proactive_content_choosen_index']:
                        
                        try:
                            logger.info(f'[{contact_id}] - Removendo índice {index} de proactive_content_choosen_index.')
                            new_payload['proactive_content_generated'].remove(fast_memory_messages['proactive_content_generated'][index])
                        except (ValueError, IndexError) as e:
                            logger.error(f"[{contact_id}] - Índice {index} não encontrado em proactive_content_generated.")

                    logger.info(f'[{contact_id}] - Remoção de conteúdo proativo de new_response_json concluída.')

                try:
                    logger.info(f'[{contact_id}] - upload no redis das novas mensagens.')
                    
                    redis_client.set(f'{contact_id}:fast_memory_messages', json.dumps(new_payload))

                    logger.info(f'[{contact_id}] - Upsert no Qdrant para FastMemoryMessages CONCLUÍDO.')
                except Exception as e:
                    logger.error(f'[{contact_id}] - ERRO ao fazer upsert no Qdrant para FastMemoryMessages (Final Answer): {e}', exc_info=True)

            if 'messages_plans_to_send' in locals() and 'plans_names_to_send' in locals() and messages_plans_to_send and plans_names_to_send:
                send_callbell_message(phone_number=phone_number, messages=messages_plans_to_send)

                for plan in plans_names_to_send:
                    redis_client.set(f"contact:{contact_id}:sendend_catalog_{plan}", "1")

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
            logger.info(f'[{contact_id}] - response_delivery_json é vazio ou nulo. Chamando run_mvp_crew_2 (condição principal).')
            run_mvp_crew_2(contact_id, phone_number, redis_client, history)



def send_message(state, messages, contact_id, phone_number):
    try:
        if state.get('communication_preference').get("prefers_audio"):
            logger.info(f'[{contact_id}] - "prefers_audio" encontrado em state. Enviando mensagem de áudio.')
            audio_url = eleven_labs_service(messages)
            send_callbell_message(phone_number=phone_number, type="audio", audio_url=audio_url)
            redis_client.hset(f"{contact_id}:attachments", audio_url, ' '.join(messages))
        
        else:
        
            has_long_message = False
            for message in messages:
                if len(message) > 250:
                    has_long_message = True
            
            if has_long_message and not all([len(message) > 250 for message in messages]):
                logger.info(f"[{contact_id}] - Encontrada mensagem com mais de 250 caracteres. Enviando mensagem de áudio.")
                            
                for message in messages:
                    if len(message) > 250:
                        audio_url = eleven_labs_service([message])
                        send_callbell_message(phone_number=phone_number, type="audio", audio_url=audio_url)
                        redis_client.hset(f"{contact_id}:attachments", audio_url, message)

                    else:
                        send_callbell_message(phone_number=phone_number, messages=[message])
            
            else:
                logger.info(f"[{contact_id}] - Não encontrada mensagem com mais de 250 caracteres.")
                
                messages_all_str = '\n'.join(messages)
                if len(messages_all_str) > 300:
                    logger.info(f"[{contact_id}] - Todas as mensagens somam mais de 300 caracteres. Enviando mensagem de áudio.")

                    audios_messages_qnt = len(messages) // 2 + 1
                    audios_messages = messages[:audios_messages_qnt]
                    audios_messages_str = '/n'.join(audios_messages)

                    messages_left = messages[audios_messages_qnt:]

                    audio_url = eleven_labs_service(audios_messages)
                    send_callbell_message(phone_number=phone_number, type="audio", audio_url=audio_url)
                    redis_client.hset(f"{contact_id}:attachments", audio_url, audios_messages_str)

                    if messages_left:
                        send_callbell_message(phone_number=phone_number, messages=messages_left)
                else:
                    logger.info(f"[{contact_id}] - Todas as mensagens somam menos de 300 caracteres. Enviando mensagens de texto.")
                    send_callbell_message(phone_number=phone_number, messages=messages)

    except Exception as e:
        logger.error(f'[{contact_id}] - Erro ao enviar mensagens para Callbell: {e}')


def run_mvp_crew_3(contact_id: str, phone_number: str, history: Any):

    # litellm._turn_on_debug()

    mensagem = '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1))
    logger.info(f"MVP Crew: Iniciando processamento para contact_id: {contact_id}, mensagem: '{mensagem}'")

    contact_data = redis_client.hgetall(f"contact:{contact_id}")
    if not contact_data:
        redis_client.hset(f"contact:{contact_id}", mapping={"system_input": "nenhum"})

    history_messages = ''
    if history:
        for message in reversed(history.get('messages', [])[:10]):
            if message.get("text"):
                history_messages += f'{"AI" if "Alessandro" in str(message.get("text", "")) else "collaborator" if not message.get("status", "") == "received" else "customer"} - {message.get("text")}\n'
            elif message.get("attachments"):
                attachments = message.get("attachments", [])

                list_of_dicts = False
                if isinstance(attachments[0], dict):
                    list_of_dicts = True
                
                elif isinstance(attachments[0], str):
                    list_of_dicts = False

                for attachment in attachments:
                    raw_url = attachment.get("payload", {}).get('url', '') if list_of_dicts else attachment

                    if "audio_eleven_agent_AI" in raw_url:
                        url = raw_url

                    else:
                        url = raw_url.split('uploads/')[1].split('?')[0] if 'uploads/' in raw_url else ''

                    if url:
                        mapped_attachments = redis_client.hgetall(f"{contact_id}:attachments")
                        if mapped_attachments:
                            attachment_text = mapped_attachments.get(url, "")
                            if attachment_text:
                                history_messages += f'{"AI" if message.get("status", "") == "sent" and "audio_eleven_agent_AI" in url else "collaborator" if not message.get("status", "") == "received" else "customer"} - {attachment_text}\n'

    state = state_manager.get_state(contact_id)

    state["metadata"]["current_turn_number"] += 1

    jump_to_registration_task = False
    registration_task = False
    
    
    if redis_client.get(f"{contact_id}:getting_data_from_user") and redis_client.get(f"{contact_id}:plan_details"):
        jump_to_registration_task = True
    
    if not jump_to_registration_task:
        context_analisys_agent_instance = get_context_analysis_agent()

        context_analisys_task: Task = create_context_analysis_task(context_analisys_agent_instance)

        context_analisys_crew = Crew(
            agents=[
                context_analisys_agent_instance,
            ],
            tasks=[
                context_analisys_task,
            ],
            process=Process.sequential,
            verbose=True,
            planning=False,
        )

        try:
            profile = json.loads(redis_client.get(f"{contact_id}:customer_profile") or "{}")
        except json.JSONDecodeError:
            profile = {}

        inputs_context_analysis = {
        "contact_id": contact_id,
        "message_text": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
        "timestamp": datetime.datetime.now().isoformat(), 
        "l0l1_cache": str(L1CacheQueryTool()._run(contact_id)),
        "l2_cache": str(redis_client.get(f'{contact_id}:fast_memory_messages')),
        "history": history_messages,
        "conversation_state": str(distill_conversation_state('ContextAnalysisAgent', state)),
        "turn": state["metadata"]["current_turn_number"],
        "customer_profile": str(distill_customer_profile(profile)),
        }

        logger.info(f"MVP Crew: Executando kickoff com inputs: {inputs_context_analysis}")
        context_analisys_crew.kickoff(inputs_context_analysis)
        logger.info(f"MVP Crew: Kickoff executado com sucesso para contact_id {contact_id}")

        response_context = context_analisys_task.output.raw
        logger.info(f"MVP Crew: Resposta gerada pelo crew: {response_context}")

        if response_context:
            json_response, updated_state = parse_json_from_string(response_context)
            
            if updated_state and isinstance(updated_state, dict):
                
                for k in updated_state:                    
                    if k in ['user_sentiment', 'entities_extracted'] and k in state:
                        state[k].extend(updated_state[k])
                    
                    else:
                        state[k] = updated_state[k]

                state_manager.save_state(contact_id, state)

            if json_response:
                
                if redis_client.get(f"{contact_id}:getting_data_from_user"):
                    json_response['operational_context'] = 'BUDGET_ACCEPTED'
                    
                if 'operational_context' in json_response and json_response['operational_context'] == 'BUDGET_ACCEPTED':
                    registration_task = True
                    redis_client.set(f"{contact_id}:plan_details", json_response.get('plan_details', ""))

                if 'profile' in json_response:
                    profile_copy = copy.deepcopy(json_response['profile'])

                    for k in profile_copy:
                        if k == "relationship_timeline" and k in profile:
                            profile[k].extend(profile_copy[k])
                        
                        else:
                            profile[k] = profile_copy[k]

                    redis_client.set(f"{contact_id}:customer_profile", json.dumps(profile))

            else:
                logger.warning(f"MVP Crew: Nenhuma resposta JSON válida gerada para contact_id {contact_id}")
                run_mvp_crew_3(contact_id, phone_number, redis_client, history)
                return

        else:
            logger.warning(f"MVP Crew: Nenhuma resposta gerada para contact_id {contact_id}")
    

    if registration_task or jump_to_registration_task:
        user_data_so_far = redis_client.get(f"{contact_id}:user_data_so_far")
        
        plan_details = redis_client.get(f"{contact_id}:plan_details")
        
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
        
        last_messages_processed = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)

        inputs_for_registration = {
            "history": history_messages,
            "message_text_original": '\n'.join(last_messages_processed),
            "collected_data_so_far": str(user_data_so_far),
            "plan_details": str(plan_details),
            "turn": state["metadata"]["current_turn_number"],
            "timestamp": datetime.datetime.now().isoformat(),
            "conversation_state": str(distill_conversation_state('RegistrationAgent', state)),
        }

        registration_crew.kickoff(inputs_for_registration)
        
        all_messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
        messages_left = [x for x in all_messages if x not in last_messages_processed]

        pipe = redis_client.pipeline()
        pipe.delete(f'contacts_messages:waiting:{contact_id}')
        if messages_left:
            pipe.rpush(f'contacts_messages:waiting:{contact_id}', *messages_left)
        
        pipe.execute()

        registration_task_str = registration_task.output.raw
        registration_task_json, updated_state = parse_json_from_string(registration_task_str)
        
        if updated_state and isinstance(updated_state, dict):
            state = updated_state

            state_manager.save_state(contact_id, state)

        redis_client.set(f"{contact_id}:user_data_so_far", json.dumps(registration_task_json))

        if registration_task_json and all([registration_task_json.get("is_data_collection_complete"), registration_task_json.get("status") == 'COLLECTION_COMPLETE']):
            send_single_telegram_message(registration_task_str, '-4854533163')
            redis_client.delete(f"{contact_id}:getting_data_from_user")
        
        elif registration_task_json and "next_message_to_send" in registration_task_json and registration_task_json["next_message_to_send"]:
            send_callbell_message(phone_number=phone_number, messages=[registration_task_json["next_message_to_send"]])
            
            redis_client.set(f"{contact_id}:getting_data_from_user", "1")
    else:
        logger.info(f"MVP Crew: Iniciando processamento para contact_id {contact_id}")

        if not json_response.get('is_plan_acceptable'):
            strategic_advisor_instance = get_strategic_advisor_agent()
            
            strategic_advise_task = create_develop_strategy_task(strategic_advisor_instance)
            
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
                "profile_customer_task_output": str(distill_customer_profile(profile)),
                "message_text_original": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
                "operational_context": json_response.get('operational_context', ''),
                "identified_topic": json_response.get('identified_topic', ''),
                "conversation_state": str(distill_conversation_state('StrategicAdvisor', state)),
                "timestamp": datetime.datetime.now().isoformat(),
                "turn": state["metadata"]["current_turn_number"]
            }
            
            crew_strategic.kickoff(inputs_strategic)
            
            strategic_advise_task_str = strategic_advise_task.output.raw
            strategic_advise_task_json, updated_state = parse_json_from_string(strategic_advise_task_str)

            if strategic_advise_task_json:
                redis_client.set(f"{contact_id}:strategic_plan", str(strategic_advise_task_json))

            if updated_state and isinstance(updated_state, dict):
                for k in updated_state:
                    state[k] = updated_state[k]

                state['strategic_plan'] = strategic_advise_task_json

                state_manager.save_state(contact_id, state)
        # ===============================================
            
        # Criando mensagens
        communication_instance = get_communication_agent()
        communication_task = create_communication_task(communication_instance)

        crew_communication = Crew(
            agents=[
                communication_instance  
            ],
            tasks=[
                communication_task
            ],
            process=Process.sequential,
            verbose=True
        )

        recently_sent_catalogs = redis_client.lrange(f"{contact_id}:sended_catalogs", 0, -1)
        last_messages_processed = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
        

        inputs_communication = {
            "develop_strategy_task_output": str(redis_client.get(f"{contact_id}:strategic_plan")),
            "profile_customer_task_output": str(distill_customer_profile(profile)),
            "message_text_original": '\n'.join(last_messages_processed),
            "operational_context": json_response.get('operational_context', ''),
            "identified_topic": json_response.get('identified_topic', ''),
            "recently_sent_catalogs": ', '.join(recently_sent_catalogs),
            "conversation_state": str(distill_conversation_state('CommunicationAgent', state)),
            "timestamp": datetime.datetime.now().isoformat(),
            "turn": state["metadata"]["current_turn_number"],
            "history": history_messages,
            "disclosure_checklist": str(state.get('disclosure_checklist', [])),
        }

        
        crew_communication.kickoff(inputs_communication)
        
        response_communication_json = None
        response_communication_str = communication_task.output.raw

        response_communication_json, updated_state = parse_json_from_string(response_communication_str)

        # Atualizando estado
        if updated_state and isinstance(updated_state, dict):
            for k in updated_state:
                if k in ['products_discussed'] and k in state:
                    state[k].extend(updated_state[k])
                
                else:
                    state[k] = updated_state[k]

            state_manager.save_state(contact_id, state)

        # ============================================================

        # Parseando resposta do CommunicationAgent
        redo = False
        if response_communication_json:
            if 'Final Answer' in response_communication_json:
                if not 'messages_sequence' in response_communication_json.get('Final Answer', {}):
                    redo = True
                
                else:
                    primary_messages = response_communication_json['Final Answer']['messages_sequence']
                    
                    del response_communication_json['Final Answer']
                    
                    response_communication_json['messages_sequence'] = primary_messages

            if not 'messages_sequence' in response_communication_json:
                redo = True
            
        else:
            redo = True
            
        if redo:
            run_mvp_crew_3(contact_id, phone_number, history)
            return

        # =============================================================================================================================

        # Envio de mensagens


        # Preparando mensagens para envio
        from app.config.utils.messages_plans import plans_messages
        
        messages_plans_to_send = []
        plans_names_to_send = []
        
        plans = response_communication_json.get('plan_names', [])
        for plan in plans if plans else []:
            if plan in plans_messages:
                messages_plans_to_send.append(plans_messages[plan])
                redis_client.rpush(f"{contact_id}:sended_catalogs", plan)

        messages_to_send = response_communication_json.get('messages_sequence', [])
        messages_to_send.extend(messages_plans_to_send)

        # Envio de mensagens para Callbell

        if messages_to_send:
            logger.info(f'[{contact_id}] - Enviando mensagens para Callbell: {messages_to_send}')
            try:
                send_message(state, messages_to_send, contact_id, phone_number)
                logger.info(f'[{contact_id}] - Mensagens enviadas com sucesso para Callbell.')
            except Exception as e:
                logger.error(f'[{contact_id}] - ERRO ao enviar mensagens para Callbell: {e}', exc_info=True)

        # =============================================================================================================================
        
        # Processamento de mensagens na fila Redis
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
