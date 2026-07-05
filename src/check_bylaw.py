import asyncio
from helpers.confg import get_settings
from stores.vectordb.VectorDBProviderFactory import VectorDBProviderFactory
from stores.llm.LLMProviderFactory import LLMProviderFactory
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


async def check():
    s = get_settings()
    engine = create_async_engine(
        f"postgresql+asyncpg://{s.POSTGRES_USERNAME}:{s.POSTGRES_PASSWORD}"
        f"@{s.POSTGRES_HOST}:{s.POSTGRES_PORT}/{s.POSTGRES_MAIN_DATABASE}"
    )
    db = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    llm_factory = LLMProviderFactory(s)
    embedder = llm_factory.create(provider=s.EMBEDDING_BACKEND)
    embedder.set_embedding_model(model_id=s.EMBEDDING_MODEL_ID, embedding_size=s.EMBEDDING_MODEL_SIZE)

    vf = VectorDBProviderFactory(config=s, db_client=db)
    vc = vf.create(provider=s.VECTOR_DB_BACKEND)
    await vc.connect()

    try:
        query = "Machine Learning course prerequisites"
        embedding = embedder.embed_text(text=query)
        if isinstance(embedding, list) and len(embedding) > 0 and isinstance(embedding[0], list):
            embedding = embedding[0]

        results = await vc.search_by_vector(collection_name="bylaw", vector=embedding, limit=5)
        print(f"Results for '{query}': {len(results) if results else 0}")
        if results:
            for r in results:
                meta = r.metadata or {}
                print(f"  Code: {meta.get('course_code')} | Name: {meta.get('course_name')} | Dept: {meta.get('department')} | Score: {r.score:.4f}")
                print(f"  Text: {r.text[:150]}...")
                print()
        else:
            print("No results found")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    await vc.disconnect()
    await engine.dispose()


asyncio.run(check())
