import json
import hashlib
from functools import wraps
from app.services.redis_service import get_redis
from app.core.logger import get_logger

logger = get_logger(__name__)

def cache_result(ttl: int = 3600):
    """
    A decorator to cache the result of a function in Redis.

    The cache key is generated from the function's name and its arguments.
    The result is stored in Redis for a specified time-to-live (ttl).

    Args:
        ttl (int): The time-to-live for the cache in seconds. Default is 3600 (1 hour).
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            redis_conn = get_redis()
            
            # Create a stable cache key
            arg_representation = {
                'args': [str(a) for a in args],
                'kwargs': {k: str(v) for k, v in sorted(kwargs.items())}
            }
            key_string = f"{func.__name__}:{json.dumps(arg_representation, sort_keys=True)}"
            cache_key = f"cache:{hashlib.sha256(key_string.encode('utf-8')).hexdigest()}"

            # Try to get the cached result
            try:
                cached_result = redis_conn.get(cache_key)
                if cached_result:
                    logger.info(f"Cache hit for key: {cache_key}")
                    return json.loads(cached_result)
            except Exception as e:
                logger.error(f"Failed to read from cache: {e}")

            # If not in cache, execute the function
            logger.info(f"Cache miss for key: {cache_key}. Executing function.")
            result = func(*args, **kwargs)

            # Cache the result
            try:
                redis_conn.setex(cache_key, ttl, json.dumps(result) if not isinstance(result, bytes) else result)
            except Exception as e:
                logger.error(f"Failed to write to cache: {e}")

            return result
        return wrapper       
    return decorator