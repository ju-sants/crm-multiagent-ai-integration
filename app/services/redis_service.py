
import redis
from app.core.logger import get_logger
from app.config.settings import settings
from functools import lru_cache

logger = get_logger(__name__)

@lru_cache(maxsize=1)
def get_redis(db: int | None = None, host: str | None = None, port: int | None = None, password: str | None = None):
    redis_conn = None
    
    try:
        redis_conn = redis.Redis(host=settings.REDIS_HOST if not host else host, port=settings.REDIS_PORT if not port else port, password=settings.REDIS_PASSWORD if not password else password, db=settings.REDIS_DB_MAIN if not db else db, decode_responses=True)
        redis_conn.ping()
        logger.info(f"Successfully connected to Redis DB {settings.REDIS_DB_MAIN}")
    except redis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis DB {settings.REDIS_DB_MAIN}: {e}")
        exit(1)

    return redis_conn