from ..LLMInterface import LLMInterface
from ..LLMEnums import OpenAIEnums
from openai import OpenAI
import logging
from typing import List, Union

class OpenAIProvider(LLMInterface):

    def __init__(self, api_key: str, api_url: str=None,#i can only use openapi package to contaact with other providers if they have an openapi endpoint"Ollama"same format"
                       default_input_max_characters: int=1000,
                       default_generation_max_output_tokens: int=1000,
                       default_generation_temperature: float=0.1):
        
        self.api_key = api_key
        self.api_url = api_url

        self.default_input_max_characters = default_input_max_characters
        self.default_generation_max_output_tokens = default_generation_max_output_tokens
        self.default_generation_temperature = default_generation_temperature

        # there is 2 tasks for this class, generation and embedding, and each one can have a different model, so we need to store the model id for each task
        self.generation_model_id = None

        self.embedding_model_id = None
        self.embedding_size = None

        self.client = OpenAI(
            api_key = self.api_key,
            base_url=self.api_url if self.api_url and len(self.api_url) > 0 else None,
        )

        self.enums = OpenAIEnums
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
            self.logger.error("OpenAI client was not set")
            return None

        if not self.generation_model_id:
            self.logger.error("Generation model for OpenAI was not set")
            return None
        
        max_output_tokens = max_output_tokens if max_output_tokens else self.default_generation_max_output_tokens
        temperature = temperature if temperature else self.default_generation_temperature

        chat_history.append( #append the user prompt to the chat history.
            self.construct_prompt(prompt=prompt, role=OpenAIEnums.USER.value)
        )

        response = self.client.chat.completions.create(
            model = self.generation_model_id,
            messages = chat_history,
            max_tokens = max_output_tokens,
            temperature = temperature,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )

        if not response or not response.choices or len(response.choices) == 0 or not response.choices[0].message:
            self.logger.error("Error while generating text with OpenAI")
            return None

        content = response.choices[0].message.content
        if not content:
            content = getattr(response.choices[0].message, "reasoning", None)

        return content


    def embed_text(self, text: Union[str, List[str]], document_type: str = None):
        if not self.client:
            self.logger.error("OpenAI client was not set")
            return None

        if not self.embedding_model_id:
            self.logger.error("Embedding model for OpenAI was not set")
            return None
        
        if isinstance(text, str):
            text = [text]
        
        response = self.client.embeddings.create(
            model = self.embedding_model_id,
            input = [self.process_text(t) for t in text],
        )

        if not response or not response.data or len(response.data) == 0 or not response.data[0].embedding:
            self.logger.error("Error while embedding text with OpenAI")
            return None

        return [d.embedding for d in response.data]

    def construct_prompt(self, prompt: str, role: str):
        return { # role is to help the provider understand the context of the prompt. content is the actual prompt that will be processed by the provider.
            "role": role,
            "content": prompt
        }

    def chat_completion(self, messages: list, tools: list = None, tool_choice: str = None,
                        model: str = None, max_tokens: int = None,
                        temperature: float = None):
        if not self.client:
            self.logger.error("OpenAI client was not set")
            return None

        model = model or self.generation_model_id
        if not model:
            self.logger.error("Generation model for OpenAI was not set")
            return None

        max_tokens = max_tokens or self.default_generation_max_output_tokens
        temperature = temperature or self.default_generation_temperature

        self.logger.info("=== OpenAI API Request ===")
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
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )

        return result
