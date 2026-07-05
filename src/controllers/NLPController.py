from .BaseController import BaseController
from models.db_schemes import Project
from stores.llm.LLMEnums import DocumentTypeEnum
from typing import List

class NLPController(BaseController):

    def __init__(self, vectordb_client, generation_client, 
                 embedding_client, template_parser = None):
        super().__init__()

        self.vectordb_client = vectordb_client
        self.generation_client = generation_client 
        self.embedding_client = embedding_client
        self.template_parser = template_parser
    
    def create_collection_name(self, project_id: str, course_code: str = None):
        if course_code:
            return f"kb_{course_code}".lower().strip()
        return f"collection_{self.vectordb_client.default_vector_size}_{project_id}".strip()
    
    async def search_vector_db_collection(self, project: Project, text: str, limit: int = 10, course_code: str = None):

        # step1: get collection name
        query_vector = None
        collection_name = self.create_collection_name(project_id=project.project_id, course_code=course_code)

        # step2: get text embedding vector
        vectors = self.embedding_client.embed_text(text=text, 
                                                 document_type=DocumentTypeEnum.QUERY.value)

        if not vectors or len(vectors) == 0:
            return False
        
        if isinstance(vectors, list) and len(vectors) > 0:
            query_vector = vectors[0]

        if not query_vector:
            return False    

        # step3: do semantic search
        results = await self.vectordb_client.search_by_vector(
            collection_name=collection_name,
            vector=query_vector,
            limit=limit
        )

        if not results:
            return False

        return results
    
    async def answer_rag_question(self, project: Project, query: str, limit: int = 10, course_code: str = None, additional_context: List[str] = None):
        
        answer, full_prompt, chat_history = None, None, None

        # step1: retrieve related documents
        retrieved_documents = await self.search_vector_db_collection(
            project=project,
            text=query,
            limit=limit,
            course_code=course_code,
        )

        has_kb = retrieved_documents and len(retrieved_documents) > 0
        has_files = additional_context and len(additional_context) > 0

        if not has_kb and not has_files:
            return answer, full_prompt, chat_history, []
        
        # step2: Construct LLM prompt
        system_prompt = self.template_parser.get("rag", "system_prompt")

        doc_num = 0
        parts = []

        if has_kb:
            kb_prompts = "\n".join([
                self.template_parser.get("rag", "document_prompt", {
                        "doc_num": idx + 1,
                        "chunk_text": self.generation_client.process_text(doc.text),
                })
                for idx, doc in enumerate(retrieved_documents)
            ])
            parts.append(kb_prompts)
            doc_num += len(retrieved_documents)

        if has_files:
            file_prompts = "\n".join([
                self.template_parser.get("rag", "document_prompt", {
                        "doc_num": doc_num + idx + 1,
                        "chunk_text": self.generation_client.process_text(ctx),
                })
                for idx, ctx in enumerate(additional_context)
            ])
            parts.append(file_prompts)

        footer_prompt = self.template_parser.get("rag", "footer_prompt", {"query": query})
        parts.append(footer_prompt)

        # step3: Construct Generation Client Prompts
        chat_history = [
            self.generation_client.construct_prompt(
                prompt=system_prompt,
                role=self.generation_client.enums.SYSTEM.value,
            )
        ]

        full_prompt = "\n\n".join(parts)

        # step4: Retrieve the Answer
        answer = self.generation_client.generate_text(
            prompt=full_prompt,
            chat_history=chat_history,
        )

        return answer, full_prompt, chat_history, retrieved_documents
        