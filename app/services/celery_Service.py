from celery import Celery
from app.config.settings import settings

# Centralized Celery app instance
celery_app = Celery(
    'agent_tasks',
    broker=f'redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB_MAIN + 1}',
    backend=f'redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB_MAIN + 1}',
    include=[
        'app.crews.main_crews.context_analysis',
        'app.crews.main_crews.strategy',
        'app.crews.main_crews.communication',
        'app.crews.main_crews.system_operations',
        'app.crews.main_crews.registration',
        'app.crews.main_crews.routing',
        'app.crews.enrichment_crew',
        'main'
    ]
)

celery_app.conf.update(
    task_track_started=True
)