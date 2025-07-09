from typing import Any, Dict, List
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from app.core.logger import get_logger

logger = get_logger(__name__)

class CrewAgentCallbackHandler(BaseCallbackHandler):
    """
    A callback handler to log agent and tool actions for AgentOps.
    """
    def __init__(self, contact_id: str):
        self.contact_id = contact_id
        super().__init__()

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> Any:
        """Log the start of an LLM call."""
        logger.info(
            "on_llm_start",
            contact_id=self.contact_id,
            prompts=prompts,
            kwargs=kwargs
        )

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        """Log the end of an LLM call."""
        logger.info(
            "on_llm_end",
            contact_id=self.contact_id,
            response=str(response),
            kwargs=kwargs
        )

    def on_agent_action(self, action: Any, **kwargs: Any) -> Any:
        """Log the action an agent is about to take."""
        logger.info(
            "on_agent_action",
            contact_id=self.contact_id,
            agent_action={
                "tool": action.tool,
                "tool_input": action.tool_input,
                "log": action.log
            }
        )

    def on_tool_end(self, output: str, **kwargs: Any) -> Any:
        """Log the output of a tool."""
        logger.info(
            "on_tool_end",
            contact_id=self.contact_id,
            tool_output=output,
            kwargs=kwargs
        )

    def on_agent_finish(self, finish: Any, **kwargs: Any) -> Any:
        """Log the final output of an agent."""
        logger.info(
            "on_agent_finish",
            contact_id=self.contact_id,
            agent_finish={"output": finish.return_values.get('output')}
        )