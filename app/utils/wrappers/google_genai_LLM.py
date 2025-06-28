from typing import Any, List, Optional, Dict, Union

from crewai.llm import LLM
from langchain_core.runnables import Runnable
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool


class GoogleGenAIWrapper(LLM):
    """
    A wrapper for langchain_google_genai.ChatGoogleGenerativeAI to make it
    compatible with crewai, especially when using `bind_tools`.

    This class inherits from `crewai.llm.LLM` to trick crewai into accepting
    it as a valid LLM, preventing it from being re-wrapped and losing the
    `bind_tools` functionality.

    Usage:
      from langchain_google_genai import ChatGoogleGenerativeAI
      from app.utils.wrappers.google_genai_LLM import GoogleGenAIWrapper

      google_llm = ChatGoogleGenerativeAI(model="models/gemini-1.5-flash")

      # Option 1: Bind tools before wrapping
      # llm_with_tools = google_llm.bind_tools([my_tool])
      # crewai_llm = GoogleGenAIWrapper(llm=llm_with_tools)

      # Option 2 (Recommended): Bind tools using the wrapper
      crewai_llm = GoogleGenAIWrapper(llm=google_llm)
      crewai_llm_with_tools = crewai_llm.bind_tools([my_tool])

      agent = Agent(llm=crewai_llm_with_tools, ...)
    """

    def __init__(self, llm: Runnable):
        """
        Initializes the wrapper.

        Args:
            llm: An instance of ChatGoogleGenerativeAI, which may or may not
                 have had `bind_tools` called on it.
        """
        # We must call super().__init__ and provide a model string.
        # We can get it from the wrapped llm or use a placeholder.
        model_name = getattr(llm, "model", "google-genai-wrapper")
        super().__init__(model=model_name)
        self.llm = llm

    def bind_tools(
        self, tools: List[Union[Dict[str, Any], type, BaseTool]]
    ) -> "GoogleGenAIWrapper":
        """
        Binds tools to the underlying LLM and returns a new wrapper instance.
        This is the recommended way to add tools to the LLM for use with crewai.
        """
        bound_llm = self.llm.bind_tools(tools)
        return GoogleGenAIWrapper(llm=bound_llm)

    def invoke(
        self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs: Any
    ) -> Any:
        """
        Delegates the `invoke` call to the wrapped langchain LLM.
        This is the primary method used by crewai's agent executor.
        It removes 'callbacks' from kwargs to prevent conflicts with crewai.
        """
        kwargs.pop("callbacks", None)
        return self.llm.invoke(messages, stop=stop, **kwargs)

    async def ainvoke(
        self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs: Any
    ) -> Any:
        """
        Delegates the `ainvoke` call to the wrapped langchain LLM for async operations.
        It removes 'callbacks' from kwargs to prevent conflicts with crewai.
        """
        kwargs.pop("callbacks", None)
        return await self.llm.ainvoke(messages, stop=stop, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """
        Delegate any other attribute access to the wrapped LLM.
        This allows crewai to access properties like `model` or other
        configurations from the original `ChatGoogleGenerativeAI` object.
        """
        return getattr(self.llm, name)

    def call(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        """
        This method is part of the base `LLM` class.
        It's implemented here for compatibility, but `invoke` is the
        preferred method for crewai's modern execution flow.
        """
        # This is a simplified conversion. It might not cover all edge cases.
        from langchain_core.messages import (
            HumanMessage,
            AIMessage,
            SystemMessage,
            ToolMessage,
        )

        lc_messages = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "user" or role == "human":
                lc_messages.append(HumanMessage(content=content))
            elif role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "assistant" or role == "ai":
                lc_messages.append(AIMessage(content=content))
            elif role == "function" or role == "tool":
                # crewai might pass tool results this way
                lc_messages.append(
                    ToolMessage(
                        content=content, tool_call_id=msg.get("tool_call_id", "")
                    )
                )
            else:
                lc_messages.append(HumanMessage(content=f"{role}: {content}"))

        response = self.invoke(lc_messages, **kwargs)
        return response.content