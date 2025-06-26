from celery import Celery
from app.config.settings import settings

# Centralized Celery app instance
celery_app = Celery(
    'agent_tasks',
    broker=f'redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB_MAIN + 2}',
    backend=f'redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB_MAIN + 2}',
    include=[
        'app.tasks.fast_path.context_analysis',
        'app.tasks.fast_path.strategy',
        'app.tasks.fast_path.communication',
        'app.tasks.fast_path.system_operations',
        'app.tasks.fast_path.registration',
        'app.tasks.fast_path.routing',
        'app.crews.enrichment_crew',
        'main'
    ]
)

celery_app.conf.update(
    task_track_started=True
)