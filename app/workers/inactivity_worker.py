from datetime import datetime, timedelta

from app.core.logger import get_logger
from app.services.celery_service import celery_app
from app.services.redis_service import get_redis
from app.crews.src.secondary_crews.follow_up import follow_up_task

logger = get_logger(__name__)
redis_client = get_redis()

LOCK_EXPIRATION_SECONDS = 60 * 10  # 10 minutes

# Backoff schedule in minutes
BACKOFF_SCHEDULE = [5, 60, 24 * 60, 3 * 24 * 60]  # 5m, 1h, 1d, 3d

@celery_app.task(name='workers.inactivity_worker')
def inactivity_worker_task():
    """
    Periodically scans for inactive contacts and triggers the follow-up crew
    with a gradual backoff strategy.
    """
    lock_key = "inactivity_worker_lock"
    
    if not redis_client.set(lock_key, "running", nx=True, ex=LOCK_EXPIRATION_SECONDS):
        logger.info("Inactivity worker is already running. Skipping.")
        return

    try:
        logger.info("Starting inactivity worker with gradual backoff...")
        
        contact_ids = redis_client.smembers("contacts")

        for contact_id in contact_ids:
            follow_up_level_key = f"follow_up_level:{contact_id}"
            follow_up_level = int(redis_client.get(follow_up_level_key) or 0)

            if follow_up_level >= len(BACKOFF_SCHEDULE):
                logger.info(f"Contact {contact_id} has reached the max follow-up level. Skipping.")
                continue

            last_message_timestamp_str = redis_client.get(f"history:last_timestamp:to_follow_up:{contact_id}")
            
            if not last_message_timestamp_str:
                continue

            last_message_timestamp = datetime.fromisoformat(last_message_timestamp_str)
            
            # Get the current backoff period
            current_backoff_minutes = BACKOFF_SCHEDULE[follow_up_level]
            
            if datetime.now() - last_message_timestamp > timedelta(minutes=current_backoff_minutes):
                logger.info(f"Contact {contact_id} is inactive beyond backoff level {follow_up_level}. Triggering follow-up task.")
                
                # Increment the follow-up level for the next check
                redis_client.set(follow_up_level_key, follow_up_level + 1)
                
                follow_up_task.apply_async(args=[contact_id])

    finally:
        # Release the lock
        redis_client.delete(lock_key)
        logger.info("Inactivity worker finished.")