from ..LLMInterface import LLMInterface
from ..LLMEnums import HuggingFaceEnums, DocumentTypeEnum
from sentence_transformers import SentenceTransformer
import logging
from typing import List, Union

class HuggingFaceProvider(LLMInterface):

    def __init__(self, api_key: str = None,
                       default_input_max_characters: int = 1000,
                       default_generation_max_output_tokens: int = 1000,
                       default_generation_temperature: float = 0.1):

        self.api_key = api_key

        self.default_input_max_characters = default_input_max_characters
        self.default_generation_max_output_tokens = default_generation_max_output_tokens
        self.default_generation_temperature = default_generation_temperature

        self.generation_model_id = None

        self.embedding_model_id = None
        self.embedding_size = None
        self.embedding_model = None

        self.enums = HuggingFaceEnums
        self.logger = logging.getLogger(__name__)

    def set_generation_model(self, model_id: str):
        self.logger.warning("HuggingFaceProvider does not support text generation, but generation model was set to: %s", model_id)
        self.generation_model_id = model_id

    def set_embedding_model(self, model_id: str, embedding_size: int):
        self.embedding_model_id = model_id
        self.embedding_size = embedding_size
        try:
            self.embedding_model = SentenceTransformer(self.embedding_model_id, token=self.api_key)
        except Exception as e:
            self.logger.error("Failed to initialize HuggingFace embedding model: %s", e)
            self.embedding_model = None

    def process_text(self, text: str):
        return text[:self.default_input_max_characters].strip()

    def generate_text(self, prompt: str, chat_history: list = [], max_output_tokens: int = None,
                            temperature: float = None):
        self.logger.warning("HuggingFaceProvider does not support text generation")
        return None

    def embed_text(self, text: Union[str, List[str]], document_type: str = None):

        if not self.embedding_model:
            self.logger.error("HuggingFace embedding model was not set")
            return None
        
        if not self.embedding_model_id:
            self.logger.error("HuggingFace embedding model ID was not set")
            return None
        try:
            if isinstance(text, str):
                text = [text]
            processed = [self.process_text(t) for t in text]
            embeddings = self.embedding_model.encode(processed, show_progress_bar=False)
            return embeddings.tolist()

        except Exception as e:
            self.logger.error("Failed to generate embeddings with HuggingFace model: %s", e)
            return None

        

       
    def construct_prompt(self, prompt: str, role: str):
        return {
            "role": role,
            "content": self.process_text(prompt)
        }

    def chat_completion(self, messages: list, tools: list = None, tool_choice: str = None,
                        model: str = None, max_tokens: int = None,
                        temperature: float = None):
        self.logger.warning("HuggingFaceProvider does not support tool-calling chat completion")
        return None
