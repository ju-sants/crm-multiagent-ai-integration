import redis
import json
import datetime
from typing import Dict, Any, Optional

from app.core.logger import get_logger

from app.services.redis_service import get_redis

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

    def _get_initial_state(self, contact_id: str) -> Dict[str, Any]:
        """
        Cria e retorna a estrutura de dados padrão para um novo estado de conversa.
        """
        return {
          "metadata": {
            "contact_id": contact_id,
            "session_start_time": datetime.datetime.now().isoformat(),
            "last_updated": datetime.datetime.now().isoformat(),
            "current_turn_number": 0
          },
          "current_context": {
          "context_type": "",
          "last_topic": "",
          "updated_at": ""
          },
          "session_summary": "Início da conversa.",
          "entities_extracted": [],
          "products_discussed": [],
          "disclousure_checklist": [],
          "last_agent_action": None,
          "user_sentiment_history": []
        }

    def get_state(self, contact_id: str) -> Dict[str, Any]:
        """
        Busca o estado atual da conversa para um determinado contato.

        Se nenhum estado existir para o contato, um novo estado inicial é criado
        e retornado, mas não é salvo no Redis até a primeira chamada de save_state.

        Args:
            contact_id (str): O ID único do contato.

        Returns:
            Dict[str, Any]: O estado da conversa como um dicionário Python.
        """
        state_key = self._get_state_key(contact_id)
        try:
            stored_state = self.redis_client.get(state_key)
            
            if stored_state:
                logger.info(f"[{contact_id}] - Estado da conversa encontrado e carregado do Redis.")
                return json.loads(stored_state)
            else:
                logger.info(f"[{contact_id}] - Nenhum estado encontrado. Criando um novo estado inicial em memória.")
                return self._get_initial_state(contact_id)

        except redis.exceptions.RedisError as e:
            logger.error(f"[{contact_id}] - Erro ao conectar ou buscar dados do Redis: {e}")
            # Em caso de falha do Redis, retorna um estado inicial para não quebrar o fluxo.
            return self._get_initial_state(contact_id)
        except json.JSONDecodeError as e:
            logger.error(f"[{contact_id}] - Erro ao decodificar o estado armazenado no Redis. Retornando estado inicial. Erro: {e}")
            return self._get_initial_state(contact_id)

    def save_state(self, contact_id: str, state: Dict[str, Any]):
        """
        Salva (ou sobrescreve) o estado completo da conversa no Redis.

        Args:
            contact_id (str): O ID único do contato.
            state (Dict[str, Any]): O objeto de estado completo a ser salvo.
        """
        state_key = self._get_state_key(contact_id)
        
        # Atualiza o timestamp e o número do turno antes de salvar
        state.get("metadata", {})["last_updated"] = datetime.datetime.now().isoformat()
        state.get("metadata", {})["current_turn_number"] = state.get("metadata", {}).get("current_turn_number", 0) + 1
        
        try:
            # Serializa o dicionário para uma string JSON antes de salvar
            state_json = json.dumps(state, ensure_ascii=False)
            self.redis_client.set(state_key, state_json)
            logger.info(f"[{contact_id}] - Estado da conversa salvo com sucesso no Redis.")

        except redis.exceptions.RedisError as e:
            logger.error(f"[{contact_id}] - Erro ao salvar o estado no Redis: {e}")
        except TypeError as e:
            logger.error(f"[{contact_id}] - Erro ao serializar o estado para JSON: {e}")