from abc import ABC, abstractmethod

class LLMInterface(ABC):

    @abstractmethod
    def set_generation_model(self, model_id: str):
        pass

    @abstractmethod
    def set_embedding_model(self, model_id: str, embedding_size: int):
        pass

    @abstractmethod
    def generate_text(self, prompt: str, chat_history: list=[], max_output_tokens: int=None,
                            temperature: float = None): #temperature is a value between 0 and 1 that controls the randomness of the output. Higher values (e.g., 0.8) will make the output more random, while lower values (e.g., 0.2) will make it more focused and deterministic.
        pass

    @abstractmethod
    def embed_text(self, text: str, document_type: str = None):#vecctor
        pass

    @abstractmethod
    def construct_prompt(self, prompt: str, role: str): #rephrase the prompt based on the role (system, user, assistant), before generating text. This can be used to add specific instructions or context to the prompt based on the role.
        pass

    @abstractmethod
    def chat_completion(self, messages: list, tools: list = None, tool_choice: str = None,
                        model: str = None, max_tokens: int = None,
                        temperature: float = None):
        pass