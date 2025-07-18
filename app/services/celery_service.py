from celery import Celery
from app.config.settings import settings

# Centralized Celery app instance
celery_app = Celery(
    'agent_tasks',
    broker=f'redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB_MAIN + 1}',
    backend=f'redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB_MAIN + 1}',
    include=[
        'app.crews.main_crews.routing_agent',
        'app.crews.main_crews.strategy',
        'app.crews.main_crews.communication',
        'app.crews.main_crews.system_operations',
        'app.crews.main_crews.registration',
        'app.crews.main_crews.backend_routing',
        'app.crews.enrichment_crew',
        'app.services.callbell_service',
        'main'
    ]
)

# celery_app.control.purge()  # Clear any existing tasks

# Enhanced configuration for connection resilience
celery_app.conf.update(
    broker_heartbeat=20,
    # Task tracking
    task_track_started=True,
    
    # Connection retry settings
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    
    # Transport options for Redis resilience
    broker_transport_options={
        'visibility_timeout': 3600,
        'retry_on_timeout': True,
        'socket_keepalive': True,
        'socket_timeout': 120,
        'socket_connect_timeout': 30,
    },
    
    # Result backend settings
    result_backend_transport_options={
        'retry_on_timeout': True,
        'socket_keepalive': True,
        'socket_timeout': 120,
        'socket_connect_timeout': 30,
    },
    
    # Worker settings
    worker_prefetch_multiplier=1,
    task_acks_late=False,
    worker_max_tasks_per_child=1000,
    
    # Task execution settings
    task_soft_time_limit=300,  # 5 minutes
    task_time_limit=600,       # 10 minutes
    
    # Serialization
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    
    # Timezone
    timezone='UTC',
    enable_utc=True,
)