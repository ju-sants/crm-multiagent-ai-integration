import logging
from app.config.settings import settings

def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(
        level=settings.LOG_LEVEL.upper(),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('app.log', mode='a')
        ]
    )
    
    return logging.getLogger(name)