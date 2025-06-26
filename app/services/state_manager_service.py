import redis
import json
import datetime
from typing import Dict, Any, Optional
from pydantic import ValidationError

from app.core.logger import get_logger

from app.services.redis_service import get_redis
from app.models.data_models import ConversationState, StateMetadata

logger = get_logger(__name__)

redis_client = get_redis()

class StateManagerService:
    """
    Serviço para gerenciar o estado da conversa com o cliente,
    utilizando o Redis como mecanismo de persistência e cache.
    """

    def __init__(self):
        self.redis_client = redis_client

    def _get_state_key(self, contact_id: str) -> str:
        """Gera a chave padronizada para armazenar o estado no Redis."""
        return f"state:{contact_id}"

    def _get_initial_state(self, contact_id: str) -> ConversationState:
        """
        Creates and returns a new ConversationState object.
        """
        metadata = StateMetadata(contact_id=contact_id)
        return ConversationState(metadata=metadata)

    def get_state(self, contact_id: str) -> ConversationState:
        """
        Retrieves the current conversation state for a given contact.

        If no state exists, a new initial state is created and returned.
        If the stored state is invalid, it logs an error and returns an initial state.

        Args:
            contact_id (str): The unique ID of the contact.

        Returns:
            ConversationState: The Pydantic model of the conversation state.
        """
        state_key = self._get_state_key(contact_id)
        try:
            stored_state_json = self.redis_client.get(state_key)
            
            if stored_state_json:
                logger.info(f"[{contact_id}] - Conversation state found, loading from Redis.")
                return ConversationState.model_validate_json(stored_state_json)
            else:
                logger.info(f"[{contact_id}] - No state found. Creating a new initial state in memory.")
                return self._get_initial_state(contact_id)

        except redis.exceptions.RedisError as e:
            logger.error(f"[{contact_id}] - Redis error when fetching state: {e}")
            return self._get_initial_state(contact_id)
        except ValidationError as e:
            logger.error(f"[{contact_id}] - Pydantic validation error when loading state from Redis. Data may be corrupt. Error: {e}")
            return self._get_initial_state(contact_id)

    def save_state(self, contact_id: str, state: ConversationState):
        """
        Saves the complete conversation state to Redis.

        Args:
            contact_id (str): The unique ID of the contact.
            state (ConversationState): The Pydantic state object to be saved.
        """
        state_key = self._get_state_key(contact_id)
        
        # Update timestamp and turn number before saving
        state.metadata.last_updated = datetime.datetime.now().isoformat()
        
        try:
            # Serialize the Pydantic model to a JSON string
            state_json = state.model_dump_json()
            self.redis_client.set(state_key, state_json)
            logger.info(f"[{contact_id}] - Conversation state saved successfully to Redis.")

        except redis.exceptions.RedisError as e:
            logger.error(f"[{contact_id}] - Error saving state to Redis: {e}")
        except Exception as e:
            logger.error(f"[{contact_id}] - An unexpected error occurred during state serialization: {e}")