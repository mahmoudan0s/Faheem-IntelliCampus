import logging
from typing import Optional

logger = logging.getLogger("uvicorn")


class LLMService:
    def __init__(self, generation_client):
        self._generation_client = generation_client

    @property
    def model_id(self):
        return getattr(self._generation_client, "generation_model_id", None)

    def chat_completion(self, messages: list, tools: list = None,
                        tool_choice: str = None, model: str = None,
                        max_tokens: int = None, temperature: float = None):
        return self._generation_client.chat_completion(
            messages=messages, tools=tools, tool_choice=tool_choice,
            model=model or self.model_id,
            max_tokens=max_tokens, temperature=temperature,
        )

    async def generate(self, system_prompt: str, user_prompt: str,
                       max_output_tokens: Optional[int] = None,
                       temperature: Optional[float] = None) -> str:
        chat_history = [
            self._generation_client.construct_prompt(system_prompt, "system"),
        ]
        response = self._generation_client.generate_text(
            prompt=user_prompt, chat_history=chat_history,
            max_output_tokens=max_output_tokens, temperature=temperature,
        )
        if not response:
            raise RuntimeError("LLM returned empty response")
        return response