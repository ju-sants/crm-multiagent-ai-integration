from app.services.celery_Service import celery_app
from app.core.logger import get_logger
from app.services.state_manager_service import StateManagerService
from app.services.redis_service import get_redis
from app.tasks.fast_path.strategy import strategy_task
from app.tasks.fast_path.communication import communication_task
from app.tasks.fast_path.system_operations import system_operations_task
from app.tasks.fast_path.registration import registration_task

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

@celery_app.task(name='fast_path.router')
def routing_task(contact_id: str):
    """
    Inspects the state and routes to the next appropriate task in the chain.
    This acts as the central switchboard for the conversation flow.
    """
    logger.info(f"[{contact_id}] - Routing task started.")
    state = state_manager.get_state(contact_id)

    # Determine the next step based on the state
    next_task = None

    # Priority 1: System Operations
    if state.system_action_request:
        logger.info(f"[{contact_id}] - Routing to: system_operations_task")
        next_task = system_operations_task.s(contact_id)
    
    # Priority 2: Registration
    elif redis_client.get(f"{contact_id}:getting_data_from_user"):
        logger.info(f"[{contact_id}] - Routing to: registration_task")
        next_task = registration_task.s(contact_id)

    # Priority 3: Strategy (if needed) -> Communication
    elif not state.is_plan_acceptable:
        logger.info(f"[{contact_id}] - Routing to: strategy_task -> communication_task")
        next_task = (strategy_task.s(contact_id) | communication_task.s())

    # Default: Straight to Communication
    else:
        logger.info(f"[{contact_id}] - Routing to: communication_task")
        next_task = communication_task.s(contact_id)

    if next_task:
        next_task.apply_async()

    return contact_id