from crewai import Crew, Process, Task
import datetime
import json
import litellm
from typing import Any, Dict
import copy
import re

from app.agents.agent_declaration import *
from app.tasks.tasks_declaration import *

from app.tools.knowledge_tools import knowledge_service_tool
from app.tools.system_operations_tools import system_operations_tool

from app.config.llm_config import default_openai_llm

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

    if ('grok' in model_name_str or 'o4' in model_name_str) and 'stop' in kwargs:
        print(f"PATCH ATIVO: Removendo parâmetro 'stop' para o modelo '{model_name}'.")
        kwargs.pop('stop')

    return original_completition(*args, **kwargs)

litellm.completion = patched_completition

state_manager = StateManagerService()


def parse_json_from_string(json_string, update=True):
    try:
        match = re.search(r'\{.*\}', json_string, re.DOTALL)
        if not match:
            print("Nenhum objeto JSON (iniciando com '{') foi encontrado na string.")
            return None
        
        json_string = match.group(0)

        # 2. Corrigir erros comuns de sintaxe de LLMs
        json_string = json_string.replace(': True', ': true').replace(': False', ': false')
        json_string = json_string.replace(': None', ': null')
    
        json_response = json.loads(json_string)

        if 'task_output' in json_response and 'updated_state' in json_response and update:
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


def _process_history(history: Any, contact_id: str) -> str:
    """Processes the message history and returns a formatted string."""
    history_messages = ''
    if history:
        for message in reversed(history.get('messages', [])[:10]):
            if message.get("text"):
                history_messages += f'{"AI" if "Alessandro" in str(message.get("text", "")) else "collaborator" if not message.get("status", "") == "received" else "customer"} - {message.get("text")}\n'
            elif message.get("attachments"):
                attachments = message.get("attachments", [])
                if not attachments:
                    continue

                list_of_dicts = isinstance(attachments[0], dict)

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
    return history_messages


def customer_service_orchestrator(contact_id: str, phone_number: str, history: Any, contact_name: str = None):

    # ================================ Initial Setup ====================================
    mensagem = '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1))
    logger.info(f"MVP Crew: Iniciando processamento para contact_id: {contact_id}, mensagem: '{mensagem}'")

    contact_data = redis_client.hgetall(f"contact:{contact_id}")
    if not contact_data:
        redis_client.hset(f"contact:{contact_id}", mapping={"system_input": "nenhum"})

    history_messages = _process_history(history, contact_id)
    state = state_manager.get_state(contact_id)

    state["metadata"]["current_turn_number"] += 1

    jump_to_system_operation = False
    if state.get("system_operation_status") == "INSUFFICIENT_DATA":
        jump_to_system_operation = True

    jump_to_registration_task = False
    registration_task = False
    if redis_client.get(f"{contact_id}:getting_data_from_user") and redis_client.get(f"{contact_id}:plan_details"):
        jump_to_registration_task = True

    # ================================ Context Analysis ====================================
    if not jump_to_registration_task and not jump_to_system_operation:
        context_analisys_agent_instance = get_context_analysis_agent()
        context_analisys_task: Task = create_context_analysis_task(context_analisys_agent_instance)

        context_analisys_crew = Crew(
            agents=[context_analisys_agent_instance],
            tasks=[context_analisys_task],
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
            "history": history_messages,
            "conversation_state": str(distill_conversation_state('ContextAnalysisAgent', state)),
            "turn": state["metadata"]["current_turn_number"],
            "customer_profile": str(distill_customer_profile(profile)),
        }

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
                state["identified_topic"] = json_response.get("identified_topic", "")

                if json_response.get("system_action_request", ""):
                    state["system_action_request"] = json_response["system_action_request"]
                    jump_to_system_operation = True

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
                customer_service_orchestrator(contact_id, phone_number, history)
                return
        else:
            logger.warning(f"MVP Crew: Nenhuma resposta gerada para contact_id {contact_id}")

    # ================================ Registration Task ====================================
    if registration_task or jump_to_registration_task and not jump_to_system_operation:
        user_data_so_far = redis_client.get(f"{contact_id}:user_data_so_far")
        plan_details = redis_client.get(f"{contact_id}:plan_details")
        registration_agent = get_registration_agent()
        registration_task = create_collect_registration_data_task(registration_agent)
        registration_crew = Crew(
            agents=[registration_agent],
            tasks=[registration_task],
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
            send_callbell_message(phone_number=phone_number, messages=[registration_task_json["next_message_to_send"]])
            send_single_telegram_message(registration_task_str, '-4854533163')
            redis_client.delete(f"{contact_id}:getting_data_from_user")
        elif registration_task_json and "next_message_to_send" in registration_task_json and registration_task_json["next_message_to_send"]:
            send_callbell_message(phone_number=phone_number, messages=[registration_task_json["next_message_to_send"]])
            redis_client.set(f"{contact_id}:getting_data_from_user", "1")
        else:
            logger.info(f"MVP Crew: Iniciando processamento para contact_id {contact_id}")

    # ================================ Strategic Advisor ====================================
    if not jump_to_system_operation and ('json_response' in locals() and not json_response.get('is_plan_acceptable')):
        default_openai_llm_with_tools = default_openai_llm.bind_tools([knowledge_service_tool])
        strategic_advisor_instance = get_strategic_advisor_agent(default_openai_llm_with_tools)
        strategic_advise_task = create_develop_strategy_task(strategic_advisor_instance)

        crew_strategic = Crew(
            agents=[strategic_advisor_instance],
            tasks=[strategic_advise_task],
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


    # ================================ System Operations ====================================


    action_requested = None
    if state.get("system_action_request"): action_requested = state.get("system_action_request")
    elif state.get("strategic_plan").get("system_action_request"): action_requested = state.get("strategic_plan").get("system_action_request")

    if action_requested:
        default_openai_llm_with_tools = default_openai_llm.bind_tools([system_operations_tool])
        system_operations_agent_instance = get_system_operations_agent(default_openai_llm_with_tools)
        system_operations_task = create_execute_system_operations_task(system_operations_agent_instance)

        crew_system_operations = Crew(
            agents=[system_operations_agent_instance],
            tasks=[system_operations_task],
            process=Process.sequential,
            verbose=True
        )

        profile = None
        try:
            profile = json.loads(redis_client.get(f"{contact_id}:customer_profile") or "{}")
        except json.JSONDecodeError:
            profile = {}

        messages_processed = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)

        inputs_system_operations = {
            "action_requested": action_requested,
            "customer_profile": str(distill_customer_profile(profile)),
            "message_text_original": '\n'.join(redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)),
            "conversation_state": str(distill_conversation_state('SystemOperations', state)),
            "history": history_messages,
            "customer_name": contact_name if contact_name else '',
        }

        crew_system_operations.kickoff(inputs_system_operations)

        all_messages = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)
        messages_left = [m for m in all_messages if m not in messages_processed]

        system_operations_task_str = system_operations_task.output.raw
        system_operations_task_json = parse_json_from_string(system_operations_task_str, update=False)

        if system_operations_task_json:
            redis_client.set(f"{contact_id}:last_system_operation_output", str(system_operations_task_json))
            if system_operations_task_json.get("status", "") == "INSUFFICIENT_DATA":
                state["system_operation_status"] = "INSUFFICIENT_DATA"
                state_manager.save_state(contact_id, state)
                send_callbell_message(phone_number=phone_number, messages=[system_operations_task_json.get("message_to_user", "")])

                pipe = redis_client.pipeline()
                pipe.delete(f'contacts_messages:waiting:{contact_id}')
                if messages_left:
                    pipe.rpush(f'contacts_messages:waiting:{contact_id}', *messages_left)
                pipe.execute()

                return
            else:
                state["system_operation_status"] = "COMPLETED"

                if "strategic_plan" in state and "system_action_request" in state["strategic_plan"]:
                    del state["strategic_plan"]["system_action_request"]

                state_manager.save_state(contact_id, state)

    # ================================ Communication ====================================
    communication_instance = get_communication_agent()
    communication_task = create_communication_task(communication_instance)

    crew_communication = Crew(
        agents=[communication_instance],
        tasks=[communication_task],
        process=Process.sequential,
        verbose=True
    )

    recently_sent_catalogs = redis_client.lrange(f"{contact_id}:sended_catalogs", 0, -1)
    last_messages_processed = redis_client.lrange(f'contacts_messages:waiting:{contact_id}', 0, -1)

    inputs_communication = {
        "develop_strategy_task_output": str(redis_client.get(f"{contact_id}:strategic_plan")),
        "profile_customer_task_output": str(distill_customer_profile(profile)),
        "system_operations_task_output": str(redis_client.get(f"{contact_id}:last_system_operation_output")),
        "message_text_original": '\n'.join(last_messages_processed),
        "operational_context": state.get('operational_context', ''),
        "identified_topic": state.get('identified_topic', ''),
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

    if updated_state and isinstance(updated_state, dict):
        for k in updated_state:
            if k in ['products_discussed'] and k in state:
                state[k].extend(updated_state[k])
            else:
                state[k] = updated_state[k]

    state_manager.save_state(contact_id, state)

    # ================================ Response Parsing ====================================
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
        customer_service_orchestrator(contact_id, phone_number, history)
        return

    # ================================ Message Sending ====================================
    from app.config.utils.messages_plans import plans_messages
    messages_plans_to_send = []

    plans = response_communication_json.get('plan_names', [])
    for plan in plans if plans else []:
        if plan in plans_messages:
            messages_plans_to_send.append(plans_messages[plan])
            redis_client.rpush(f"{contact_id}:sended_catalogs", plan)

    messages_to_send = response_communication_json.get('messages_sequence', [])
    messages_to_send.extend(messages_plans_to_send)

    if messages_to_send:
        logger.info(f'[{contact_id}] - Enviando mensagens para Callbell: {messages_to_send}')
        try:
            send_message(state, messages_to_send, contact_id, phone_number)
            logger.info(f'[{contact_id}] - Mensagens enviadas com sucesso para Callbell.')
        except Exception as e:
            logger.error(f'[{contact_id}] - ERRO ao enviar mensagens para Callbell: {e}', exc_info=True)

    # ================================ Redis Message Processing ====================================
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
