#!/bin/bash

# Função para cleanup quando o script receber SIGTERM
cleanup() {
    echo "Recebendo sinal de parada..."
    kill -TERM "$celery_worker_pid" "$celery_beat_pid" "$gunicorn_pid" 2>/dev/null
    wait "$celery_worker_pid" "$celery_beat_pid" "$gunicorn_pid"
    exit 0
}

# Configurar trap para cleanup
trap cleanup SIGTERM SIGINT

echo "Iniciando aplicação..."

# Iniciar Celery Worker em background
echo "Iniciando Celery Worker..."
celery -A app.services.celery_service.celery_app worker --loglevel=INFO &
celery_worker_pid=$!

# Iniciar Celery Beat em background  
echo "Iniciando Celery Beat..."
celery -A app.services.celery_service.celery_app beat --loglevel=INFO &
celery_beat_pid=$!

# Aguardar um pouco para os serviços do Celery iniciarem
sleep 5

# Iniciar Gunicorn em background
echo "Iniciando Gunicorn..."
gunicorn -b 0.0.0.0:$PORT main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --timeout 300 &
gunicorn_pid=$!

echo "Todos os processos iniciados:"
echo "Celery Worker PID: $celery_worker_pid"
echo "Celery Beat PID: $celery_beat_pid"
echo "Gunicorn PID: $gunicorn_pid"

# Aguardar todos os processos
wait "$celery_worker_pid" "$celery_beat_pid" "$gunicorn_pid"