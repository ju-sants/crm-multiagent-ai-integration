from celery import Celery
from app.config.settings import settings


def make_celery(app):
    celery_app = Celery(
        'main',
        broker=f'redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB_MAIN + 1}',
        backend=f'redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB_MAIN + 1}',
    )
    celery_app.conf.update(app.config)

    # Configuração para que as tarefas possam acessar o contexto da aplicação Flask
    class ContextTask(celery_app.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app.Task = ContextTask
    return celery_app