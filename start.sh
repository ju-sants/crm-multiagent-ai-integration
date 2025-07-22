echo "Iniciando Celery worker..."
celery -A app.services.celery_service.celery_app worker \
  --loglevel=INFO

echo "Aguardando 5 segundos para Celery inicializar..."
sleep 5

echo "Iniciando Gunicorn..."
exec gunicorn -b 0.0.0.0:$PORT main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --timeout 300