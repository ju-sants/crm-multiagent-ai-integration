#!/bin/bash

# Configurações de otimização de recursos
export CELERY_OPTIMIZATION=fair
export C_FORCE_ROOT=1
export OTEL_SDK_DISABLED=true
export OTEL_PYTHON_DISABLED=true

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

# Reduzir workers para economizar recursos
WORKERS=${WORKERS:-2}
CELERY_CONCURRENCY=${CELERY_CONCURRENCY:-2}

# Iniciar Celery Worker em background com configurações otimizadas
echo "Iniciando Celery Worker..."
celery -A app.services.celery_service.celery_app worker \
    --loglevel=INFO \
    --concurrency=$CELERY_CONCURRENCY \
    --without-gossip \
    --without-mingle \
    --pool=solo \
    &
celery_worker_pid=$!

# Aguardar worker iniciar
sleep 3

# Iniciar Celery Beat em background  
echo "Iniciando Celery Beat..."
celery -A app.services.celery_service.celery_app beat \
    --loglevel=INFO \
    --pidfile=/tmp/celerybeat.pid \
    &
celery_beat_pid=$!

# Aguardar beat iniciar
sleep 3

# Iniciar Gunicorn em background com WSGI worker (correto para Flask)
echo "Iniciando Gunicorn..."
gunicorn -b 0.0.0.0:$PORT main:app \
    --workers $WORKERS \
    --worker-class sync \
    --timeout 300 \
    --max-requests 1000 \
    --max-requests-jitter 50 \
    &
gunicorn_pid=$!

echo "Todos os processos iniciados:"
echo "Celery Worker PID: $celery_worker_pid"
echo "Celery Beat PID: $celery_beat_pid"
echo "Gunicorn PID: $gunicorn_pid"

# Aguardar todos os processos
wait "$celery_worker_pid" "$celery_beat_pid" "$gunicorn_pid"