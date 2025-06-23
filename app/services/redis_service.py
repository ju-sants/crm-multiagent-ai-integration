
import redis
from app.core.logger import get_logger
from app.config.settings import settings
from functools import lru_cache

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_redis(db=None):
    redis_conn = None
    
    try:
        redis_conn = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, password=settings.REDIS_PASSWORD, db=5 if not db else db, decode_responses=True)
        redis_conn.ping()
        logger.info(f"Successfully connected to Redis DB {settings.REDIS_DB_MAIN}")
    except redis.exceptions.ConnectionError as e:
        logger.error(f"Failed to connect to Redis DB {settings.REDIS_DB_MAIN}: {e}")
        exit(1)
        
    return redis_conn