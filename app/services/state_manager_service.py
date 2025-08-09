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

    def get_state(self, contact_id: str) -> tuple[ConversationState, bool]:
        """
        Retrieves the current conversation state for a given contact.

        If no state exists, a new initial state is created and returned with a flag indicating it's new.
        If the stored state is invalid, it logs an error and returns an initial state.
        If the stored state is valid, it returns the state with a flag indicating it's not new.

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
                return ConversationState.model_validate_json(stored_state_json), False
            else:
                logger.info(f"[{contact_id}] - No state found. Creating a new initial state in memory.")
                return self._get_initial_state(contact_id), True

        except redis.exceptions.RedisError as e:
            logger.error(f"[{contact_id}] - Redis error when fetching state: {e}")
            return self._get_initial_state(contact_id), True
        except ValidationError as e:
            logger.warning(f"[{contact_id}] - Pydantic validation error for stored state: {e}. Attempting to migrate old state format.")
            if stored_state_json:
                try:
                    old_state_dict = json.loads(stored_state_json)
                    return self._migrate_old_state(old_state_dict), False
                except (json.JSONDecodeError, TypeError):
                    logger.error(f"[{contact_id}] - Could not migrate old state as it is not valid JSON. Creating new state.")
                    return self._get_initial_state(contact_id), True
            else:
                # This case should not be hit if ValidationError was raised, but as a safeguard:
                return self._get_initial_state(contact_id), True

    def save_state(self, contact_id: str, state: ConversationState):
        """
        Saves the complete conversation state to Redis.

        Args:
            contact_id (str): The unique ID of the contact.
            state (ConversationState): The Pydantic state object to be saved.
        """
        state_key = self._get_state_key(contact_id)
        
        try:
            # Serialize the Pydantic model to a JSON string
            state_json = state.model_dump_json()
            self.redis_client.set(state_key, state_json)
            logger.info(f"[{contact_id}] - Conversation state saved successfully to Redis.")

        except redis.exceptions.RedisError as e:
            logger.error(f"[{contact_id}] - Error saving state to Redis: {e}")
        except Exception as e:
            logger.error(f"[{contact_id}] - An unexpected error occurred during state serialization: {e}")

    def _migrate_old_state(self, old_dict: Dict[str, Any]) -> ConversationState:
        """
        Attempts to migrate a state from an old dictionary format to the new
        ConversationState Pydantic model.
        """
        contact_id = old_dict.get("contact_id") or old_dict.get("metadata", {}).get("contact_id")
        if not contact_id:
            # If we can't even find a contact_id, it's a lost cause.
            raise ValueError("Old state dictionary is missing a contact_id.")

        logger.info(f"[{contact_id}] - Migrating state from old format.")
        
        # Create a new state and populate it with data from the old one
        new_state = self._get_initial_state(contact_id)

        # Manually map old fields to new fields
        new_state.metadata.current_turn_number = old_dict.get("metadata", {}).get("current_turn_number", 1)
        new_state.entities_extracted = old_dict.get("entities_extracted", [])
        new_state.products_discussed = old_dict.get("products_discussed", [])
        new_state.disclosure_checklist = old_dict.get("disclousure_checklist", []) # Note the typo in the original
        new_state.strategic_plan = old_dict.get("strategic_plan")
        new_state.system_operation_status = old_dict.get("system_operation_status")
        new_state.system_action_request = old_dict.get("system_action_request")
        new_state.identified_topic = old_dict.get("identified_topic")
        new_state.operational_context = old_dict.get("operational_context")
        new_state.user_sentiment_history = old_dict.get("user_sentiment_history", [])
        
        # Handle nested communication_preference
        if "communication_preference" in old_dict:
            new_state.prefers_audio = old_dict["communication_preference"].get("prefers_audio", False)
        elif "prefers_audio" in old_dict:
            new_state.prefers_audio = old_dict.get("prefers_audio", False)

        return new_state