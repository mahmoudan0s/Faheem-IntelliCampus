import asyncio
import logging

from fastapi import FastAPI
from routes import base, courses, smart_notes, admin_bylaw
from helpers.confg import get_settings
from stores.llm.LLMProviderFactory import LLMProviderFactory
from stores.vectordb.VectorDBProviderFactory import VectorDBProviderFactory
from stores.llm.templates.template_parser import TemplateParser
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from utils.metrics import setup_metrics

from app.services.llm_service import LLMService
from app.services.mcp_manager import MCPManager
from app.services.advisor_service import AdvisorService
from app.routes.advisor import advisor_router

logger = logging.getLogger("uvicorn")

app = FastAPI()

setup_metrics(app)


async def startup_span():
    settings = get_settings()

    postgres_conn = f"postgresql+asyncpg://{settings.POSTGRES_USERNAME}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_MAIN_DATABASE}"
    app.db_engine = create_async_engine(postgres_conn)
    app.db_client = sessionmaker(
        app.db_engine, class_=AsyncSession, expire_on_commit=False
    )

    llm_provider_factory = LLMProviderFactory(settings)
    vectordb_provider_factory = VectorDBProviderFactory(config=settings, db_client=app.db_client)

    app.generation_client = llm_provider_factory.create(provider=settings.GENERATION_BACKEND)
    app.generation_client.set_generation_model(model_id=settings.GENERATION_MODEL_ID)

    app.groq_generation_client = llm_provider_factory.create(provider="GROQ")
    if app.groq_generation_client:
        app.groq_generation_client.set_generation_model(model_id=settings.GROQ_MODEL_ID)

    # Warm up the generation LLM so the first user request isn't hit by a cold-start model load
    try:
        logger.info("Warming up generation LLM (cold-start)...")
        warmup_loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            warmup_loop.run_in_executor(
                None,
                lambda: app.generation_client.chat_completion(
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=5,
                    temperature=0,
                ),
            ),
            timeout=120,
        )
        logger.info("Generation LLM warmup complete")
    except Exception as e:
        logger.warning("Generation LLM warmup skipped: %s — first request may be slow", e)

    app.embedding_client = llm_provider_factory.create(provider=settings.EMBEDDING_BACKEND)
    app.embedding_client.set_embedding_model(
        model_id=settings.EMBEDDING_MODEL_ID,
        embedding_size=settings.EMBEDDING_MODEL_SIZE,
    )

    app.vectordb_client = vectordb_provider_factory.create(provider=settings.VECTOR_DB_BACKEND)
    await app.vectordb_client.connect()

    app.template_parser = TemplateParser(
        language=settings.PRIMARY_LANG,
        default_language=settings.DEFAULT_LANG,
    )

    llm_service = LLMService(generation_client=app.generation_client)

    mcp_manager = MCPManager()
    await mcp_manager.connect_all()
    app.state.mcp_manager = mcp_manager

    app.state.advisor_service = AdvisorService(
        mcp_manager=mcp_manager,
        llm_service=llm_service,
    )

    tool_count = len(await mcp_manager.get_all_tools())
    logger.info("Advisor service initialized — %d MCP tools available", tool_count)


async def shutdown_span():
    await app.db_engine.dispose()
    await app.vectordb_client.disconnect()
    if hasattr(app.state, "mcp_manager"):
        await app.state.mcp_manager.close_all()


app.on_event("startup")(startup_span)
app.on_event("shutdown")(shutdown_span)

app.include_router(base.base_router)
app.include_router(courses.courses_router)
app.include_router(smart_notes.smart_notes_router)
app.include_router(admin_bylaw.admin_bylaw_router)
app.include_router(advisor_router)
