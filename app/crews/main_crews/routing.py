from app.services.celery_Service import celery_app
from app.core.logger import get_logger
from app.services.state_manager_service import StateManagerService
from app.services.redis_service import get_redis
from app.crews.main_crews.strategy import strategy_task
from app.crews.main_crews.communication import communication_task
from app.crews.main_crews.system_operations import system_operations_task
from app.crews.main_crews.registration import registration_task

logger = get_logger(__name__)
state_manager = StateManagerService()
redis_client = get_redis()

@celery_app.task(name='main_crews.router')
def routing_task(contact_id: str):
    """
    Inspects the state and routes to the next appropriate task in the chain.
    This acts as the central switchboard for the conversation flow.
    """
    logger.info(f"[{contact_id}] - Routing task started.")
    state = state_manager.get_state(contact_id)

    # Determine the next step based on the state
    next_task = None

    # Priority 1: Budget has been explicitly accepted by the user.
    if state.budget_accepted:
        logger.info(f"[{contact_id}] - Budget accepted flag is TRUE. Routing to: registration_task")
        redis_client.set(f"{contact_id}:getting_data_from_user", "1") # Set flag to initiate registration
        next_task = registration_task.s(contact_id)

    # Priority 2: Is there a pending operation waiting for user input?
    elif state.pending_system_operation:
        logger.info(f"[{contact_id}] - Resuming pending system operation. Routing to: system_operations_task")
        # Restore the original request so the agent knows what it was trying to do
        state.system_action_request = state.pending_system_operation
        state_manager.save_state(contact_id, state) # Save state before dispatching
        next_task = system_operations_task.s(contact_id)

    # Priority 3: A new system operation has been requested
    elif state.system_action_request:
        logger.info(f"[{contact_id}] - New system action requested. Routing to: system_operations_task")
        next_task = system_operations_task.s(contact_id)

    # Priority 4: Already in the middle of registration
    elif redis_client.get(f"{contact_id}:getting_data_from_user"):
        logger.info(f"[{contact_id}] - Continuing registration flow. Routing to: registration_task")
        next_task = registration_task.s(contact_id)

    # Priority 5: Strategy (if needed) -> Communication
    elif not state.is_plan_acceptable:
        logger.info(f"[{contact_id}] - Plan not acceptable. Routing to: strategy_task -> communication_task")
        next_task = (strategy_task.s(contact_id) | communication_task.s())

    # Default: Straight to Communication
    else:
        logger.info(f"[{contact_id}] - Plan is acceptable. Routing to: communication_task")
        next_task = communication_task.s(contact_id)

    if next_task:
        next_task.apply_async()

    return contact_id