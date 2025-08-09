from celery import chain
import time

from app.services.celery_service import celery_app
from app.core.logger import get_logger
from app.services.state_manager_service import StateManagerService
from app.services.redis_service import get_redis
from app.crews.src.main_crews.communication import communication_task
from app.crews.src.main_crews.system_operations import system_operations_task
from app.crews.src.main_crews.registration import registration_task
from app.crews.src.main_crews.purchase_confirmation import purchase_confirmation_task

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

@celery_app.task(name='main_crews.backend_routing')
def backend_routing_task(contact_id: str):
    """
    Inspects the state and routes to the next appropriate task in the chain.
    This acts as the central switchboard for the conversation flow.
    """
    logger.info(f"[{contact_id}] - Routing task started.")
    state, _ = state_manager.get_state(contact_id)

    # Determine the next step based on the state
    next_task = None

    # Se RoutingAgent nos informa que estamos num estágio de venda e a venda ainda não está aceita no sistema, acionamos o agente verificador
    if state.is_sales_final_step and not state.budget_accepted:
        purchase_confirmation_task(contact_id)

        state, _ = state_manager.get_state(contact_id)

    # Priority 1: Budget has been explicitly accepted by the user.
    if state.budget_accepted:
        logger.info(f"[{contact_id}] - Budget accepted flag is TRUE. Routing to: registration_task")
        redis_client.set(f"{contact_id}:getting_data_from_user", "1") # Set flag to initiate registration
        next_task = registration_task.s(contact_id)

    # Priority 3: Wait for Strategy (if needed) -> Communication
    elif not state.is_plan_acceptable:

        if redis_client.get(f"refining_strategy:{contact_id}"):
            logger.info(f"[{contact_id}] - Refining strategy in progress. Waiting for completion.")
        if redis_client.get(f"doing_strategy:{contact_id}"):
            logger.info(f"[{contact_id}] - Strategy development in progress. Waiting for completion.")

        while redis_client.get(f"refining_strategy:{contact_id}") or redis_client.get(f"doing_strategy:{contact_id}"):
            time.sleep(1)  # Wait for 1 second
            
        logger.info(f"[{contact_id}] - Strategy development Completed. Routing to: communication_task")
        next_task = communication_task.s(contact_id)
        
    # Default: Straight to Communication
    else:
        logger.info(f"[{contact_id}] - Plan is acceptable. Routing to: communication_task")
        next_task = communication_task.s(contact_id)

    if redis_client.get(f"doing_system_operations:{contact_id}"):
        logger.info(f"[{contact_id}] - Esperando a operação de sistema acabar")
        # Espera qualquer operação de sistema terminar antes de iniciar a próxima task
        while redis_client.get(f"doing_system_operations:{contact_id}"):
            time.sleep(1)  # Wait for 1 second

    if next_task:
        
        state, _ = state_manager.get_state(contact_id)
        if state.pending_system_operation:
            logger.info(f"[{contact_id}] - Theres a pending system operation in progress... skipping.")
            return contact_id
        
        next_task.apply_async()

    return contact_id