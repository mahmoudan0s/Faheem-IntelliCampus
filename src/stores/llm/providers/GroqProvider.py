from ..LLMInterface import LLMInterface
from ..LLMEnums import GroqEnums
from groq import Groq
import logging
from typing import List, Union

class GroqProvider(LLMInterface):

    def __init__(self, api_key: str,
                       default_input_max_characters: int=1000,
                       default_generation_max_output_tokens: int=1000,
                       default_generation_temperature: float=0.1):
        
        self.api_key = api_key

        self.default_input_max_characters = default_input_max_characters
        self.default_generation_max_output_tokens = default_generation_max_output_tokens
        self.default_generation_temperature = default_generation_temperature

        self.generation_model_id = None

        self.embedding_model_id = None
        self.embedding_size = None
        self.enums = GroqEnums
        self.client = Groq(
            api_key = self.api_key
        )

        self.logger = logging.getLogger(__name__)

    def set_generation_model(self, model_id: str):
        self.generation_model_id = model_id

    def set_embedding_model(self, model_id: str, embedding_size: int):
        self.embedding_model_id = model_id
        self.embedding_size = embedding_size

    def process_text(self, text: str):
        return text[:self.default_input_max_characters].strip()

    def generate_text(self, prompt: str, chat_history: list=[], max_output_tokens: int=None,
                            temperature: float = None):
        
        if not self.client:
            self.logger.error("Groq client was not set")
            return None

        if not self.generation_model_id:
            self.logger.error("Generation model for Groq was not set")
            return None
        
        max_output_tokens = max_output_tokens if max_output_tokens else self.default_generation_max_output_tokens
        temperature = temperature if temperature else self.default_generation_temperature

        chat_history.append(
            self.construct_prompt(prompt=prompt, role=GroqEnums.USER.value)
        )

        response = self.client.chat.completions.create(
            model = self.generation_model_id,
            messages = chat_history,
            max_tokens = max_output_tokens,
            temperature = temperature
        )

        if not response or not response.choices or len(response.choices) == 0 or not response.choices[0].message:
            self.logger.error("Error while generating text with Groq")
            return None

        return response.choices[0].message.content

    def chat_completion(self, messages: list, tools: list = None, tool_choice: str = None,
                        model: str = None, max_tokens: int = None,
                        temperature: float = None):
        if not self.client:
            self.logger.error("Groq client was not set")
            return None

        model = model or self.generation_model_id
        if not model:
            self.logger.error("Generation model for Groq was not set")
            return None

        max_tokens = max_tokens or self.default_generation_max_output_tokens
        temperature = temperature if temperature is not None else self.default_generation_temperature

        self.logger.info("=== Groq API Request ===")
        self.logger.info("Model: %s", model)
        self.logger.info("Messages: %d msgs", len(messages))
        self.logger.info("Tools: %s", [t["function"]["name"] for t in tools] if tools else "NONE")
        self.logger.info("Tool choice: %s", tool_choice)
        self.logger.info("Max tokens: %s", max_tokens)

        result = self.client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            tool_choice=tool_choice or ("auto" if tools else None),
            max_tokens=max_tokens,
            temperature=temperature,
        )

        return result

    def embed_text(self, text: Union[str, List[str]], document_type: str = None):
        self.logger.warning("Groq does not support embeddings natively")
        return None

    def construct_prompt(self, prompt: str, role: str):
        return {
            "role": role,
            "content": prompt
        }
