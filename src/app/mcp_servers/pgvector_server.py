import asyncio
import logging
import os
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from helpers.confg import get_settings
from stores.llm.LLMProviderFactory import LLMProviderFactory
from stores.llm.LLMEnums import LLMEnums
from stores.vectordb.VectorDBProviderFactory import VectorDBProviderFactory
from stores.vectordb.VectorDBEnums import VectorDBEnums
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger("mcp-pgvector")

mcp = FastMCP("pgvector-server")

_embedding_client = None
_vectordb_client = None
_db_session_factory = None


async def _init():
    global _embedding_client, _vectordb_client, _db_session_factory
    if _embedding_client is not None:
        return

    settings = get_settings()

    postgres_conn = (
        f"postgresql+asyncpg://{settings.POSTGRES_USERNAME}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_MAIN_DATABASE}"
    )
    db_engine = create_async_engine(postgres_conn, pool_size=5, max_overflow=10)
    _db_session_factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    llm_factory = LLMProviderFactory(settings)
    _embedding_client = llm_factory.create(provider=settings.EMBEDDING_BACKEND)
    _embedding_client.set_embedding_model(
        model_id=settings.EMBEDDING_MODEL_ID,
        embedding_size=settings.EMBEDDING_MODEL_SIZE,
    )

    vectordb_factory = VectorDBProviderFactory(config=settings, db_client=_db_session_factory)
    _vectordb_client = vectordb_factory.create(provider=settings.VECTOR_DB_BACKEND)
    await _vectordb_client.connect()

    _embedding_client.embed_text(text="warmup")


async def _keyword_search(
    query: str, top_k: int,
    department: Optional[str], course_code: Optional[str],
    chunk_type: Optional[str], level: Optional[int], semester: Optional[int],
    category: Optional[str] = None, section: Optional[str] = None,
    requirement_type: Optional[str] = None,
) -> list:
    global _db_session_factory
    if not _db_session_factory:
        return []
    try:
        async with _db_session_factory() as session:
            from sqlalchemy import text
            kw_sql = text("""
                SELECT id, text, metadata,
                       ts_rank(to_tsvector('english', text), plainto_tsquery('english', :query))
                       + CASE WHEN text ILIKE :phrase THEN 0.5 ELSE 0 END as rank
                FROM bylaw
                WHERE to_tsvector('english', text) @@ plainto_tsquery('english', :query)
                   OR text ILIKE :phrase
                ORDER BY rank DESC
                LIMIT :limit
            """)
            result = await session.execute(kw_sql, {"query": query, "phrase": f"%{query}%", "limit": top_k * 3})
            rows = result.fetchall()
            out = []
            for row in rows:
                meta = row.metadata or {}
                if not _match_filters(meta, department, course_code, chunk_type, level, semester, category, section, requirement_type):
                    continue
                out.append(_build_result(row.text, row.rank, meta))
                if len(out) >= top_k:
                    break
            return out
    except Exception as e:
        logger.warning("Keyword search failed: %s", e)
        return []


async def _metadata_search(
    query: str, top_k: int,
    department: Optional[str], course_code: Optional[str],
    chunk_type: Optional[str], level: Optional[int], semester: Optional[int],
    category: Optional[str] = None, section: Optional[str] = None,
    requirement_type: Optional[str] = None,
) -> list:
    global _db_session_factory
    if not _db_session_factory:
        return []
    try:
        async with _db_session_factory() as session:
            from sqlalchemy import text
            like_pattern = f"%{query}%"
            meta_sql = text("""
                SELECT id, text, metadata
                FROM bylaw
                WHERE metadata::text ILIKE :pattern
                   OR text ILIKE :pattern
                LIMIT :limit
            """)
            result = await session.execute(meta_sql, {"pattern": like_pattern, "limit": top_k * 3})
            rows = result.fetchall()
            out = []
            for row in rows:
                meta = row.metadata or {}
                if not _match_filters(meta, department, course_code, chunk_type, level, semester, category, section, requirement_type):
                    continue
                out.append(_build_result(row.text, 0.5, meta))
                if len(out) >= top_k:
                    break
            return out
    except Exception as e:
        logger.warning("Metadata search failed: %s", e)
        return []


def _match_filters(
    meta: dict,
    department: Optional[str], course_code: Optional[str],
    chunk_type: Optional[str], level: Optional[int], semester: Optional[int],
    category: Optional[str] = None, section: Optional[str] = None,
    requirement_type: Optional[str] = None,
) -> bool:
    if department:
        dept_val = str(meta.get("department") or "").lower().replace("_", "").replace("-", "").replace(" ", "")
        dept_filter = department.lower().replace("_", "").replace("-", "").replace(" ", "")
        if dept_filter not in dept_val and dept_val not in dept_filter:
            return False
    if course_code and str(meta.get("course_code", "")).upper() != course_code.upper():
        return False
    if chunk_type and str(meta.get("chunk_type", "")).lower() != chunk_type.lower():
        return False
    if category and str(meta.get("category", "")).lower() != category.lower():
        return False
    if section and str(meta.get("section", "")).lower() != section.lower():
        return False
    if requirement_type and str(meta.get("requirement_type", "")).lower() != requirement_type.lower():
        return False
    if level is not None and meta.get("level") != level:
        return False
    if semester is not None:
        sem_val = meta.get("semester")
        if sem_val is None:
            return False
        expected_abs = str(semester)
        if level is not None and semester in (1, 2):
            expected_abs = str((level - 1) * 2 + semester)
        if str(sem_val) != expected_abs and str(sem_val) != str(semester):
            return False
    return True


def _build_result(text: str, score, meta: dict) -> dict:
    score_val = round(float(score), 3) if score is not None else 0.5
    return {
        "text": text,
        "score": score_val,
        "metadata": {
            "department": meta.get("department"),
            "course_code": meta.get("course_code"),
            "course_name": meta.get("course_name"),
            "category": meta.get("category"),
            "chunk_type": meta.get("chunk_type"),
            "section": meta.get("section"),
            "prerequisites": meta.get("prerequisites"),
            "credit_hours": meta.get("credit_hours"),
            "requirement_type": meta.get("requirement_type"),
        },
    }


@mcp.tool()
async def search_bylaw_chunks(
    query: str,
    top_k: int = 3,
    department: Optional[str] = None,
    course_code: Optional[str] = None,
    chunk_type: Optional[str] = None,
    level: Optional[int] = None,
    semester: Optional[int] = None,
    category: Optional[str] = None,
    section: Optional[str] = None,
    requirement_type: Optional[str] = None,
) -> str:
    """Search academic regulations, course information, study plans, and policies.
    Returns the most relevant bylaw excerpts with metadata tags.

    ---
    chunk_type — narrow by semantic type:
    - "document_info" — document title, version, issuing authority
    - "vision" — faculty vision statement
    - "mission" — faculty mission statement
    - "values" — faculty values and guiding principles
    - "objectives" — faculty objectives and goals
    - "departments" — list of academic departments
    - "department_overview" — overview of a department, purpose, and scientific fields
    - "programs" — academic programs offered
    - "program_framework" — general framework governing programs
    - "program_overview" — overview of a specific program
    - "program_structure" — program structure with credit-hour distribution
    - "study_plan" — recommended semester-by-semester study plan (use with level+semester+department)
    - "curriculum_section" — a section of the curriculum
    - "course_group" — lists of courses (compulsory, elective, university requirements)
    - "course_description" — detailed course info: description, objectives, prerequisites, topics
    - "academic_requirement" — compulsory or elective requirements
    - "graduation_requirement" — graduation conditions and requirements
    - "graduation_project" — graduation project rules
    - "academic_regulation" — general academic regulations
    - "registration_rules" — course registration, credit hours, add/drop, prerequisites
    - "withdrawal_rules" — course withdrawal rules
    - "attendance_rules" — attendance policies and absence limits
    - "dismissal_rules" — academic dismissal and suspension
    - "grading_policy" — GPA calculation, grading system, honors
    - "academic_progression" — academic standing, progression, warnings
    - "academic_advising" — advising rules and responsibilities
    - "course_code_system" — how course codes are constructed
    - "department_codes" — department abbreviation mappings

    ---
    category — high-level knowledge category:
    - "general_requirements" — university-wide requirements
    - "college_requirements" — faculty-level requirements
    - "course_contents" — detailed course info (descriptions, objectives, topics, prerequisites)
    - "specialization_requirements" — department-specific curriculum
    - "graduation_requirements" — graduation conditions
    - "study_plan" — recommended semester-by-semester plan

    ---
    requirement_type — curriculum requirement category:
    - "compulsory" — mandatory course
    - "elective" — optional course
    - "general_elective" — university general elective
    - "college_compulsory" — faculty compulsory
    - "department_compulsory" / "specialization_compulsory" — department compulsory (semantically identical, search both)
    - "department_elective" / "specialization_elective" — department elective (semantically identical, search both)
    - "graduation_project" — graduation project requirement
    - "field_training" — internship requirement
    - "recommended_study_plan" — recommended semester sequence

    ---
    section — exact document section heading:
    - "Document Information", "Faculty Vision", "Faculty Mission", etc.
    - "Article 1 - Study Regulations", "Article 4 - Prerequisites", "Article 10 - GPA Calculation"
    - "Computer Science - Compulsory Courses", "Information Systems - Elective Courses"
    - "Sample Study Plan - Level One", "AI Department - Level Three"
    See full doc for all ~50 section values.

    For study plans, use level (1-4) and semester (1-2 or "summer") with department.

    Args:
        query: The question or search topic (e.g. "Data Warehousing", "grading system", "CS level 3 plan")
        top_k: Number of results to return (default 5)
        department: Filter by department (e.g. "computer_science", "information_systems", "AI")
        course_code: Filter by exact course code (e.g. "IS313", "CS462")
        chunk_type: Filter by semantic chunk type (see list above)
        level: Filter by academic level (1-4) — for study plans
        semester: Filter by semester (1 or 2) — for study plans
        category: Filter by high-level knowledge category (see list above)
        section: Filter by exact document section heading (see full documentation)
        requirement_type: Filter by curriculum requirement category (see list above)
    """
    global _vectordb_client
    if _embedding_client is None or _vectordb_client is None:
        return "Server not initialized yet. Try again."

    try:
        results = []

        # --- Tier 1: Vector search ---
        embedding = _embedding_client.embed_text(text=query)
        if embedding:
            if isinstance(embedding, list) and len(embedding) > 0 and isinstance(embedding[0], list):
                embedding = embedding[0]
            vec_results = await _vectordb_client.search_by_vector(
                collection_name="bylaw", vector=embedding, limit=top_k * 3
            )
            if vec_results:
                for doc in vec_results:
                    if doc.score < -999:
                        continue
                    meta = doc.metadata or {}
                    if not _match_filters(meta, department, course_code, chunk_type, level, semester, category, section, requirement_type):
                        continue
                    results.append(_build_result(doc.text, doc.score, meta))
                    if len(results) >= top_k:
                        break

        # --- Tier 2: Keyword search (full-text search on text column) ---
        if not results:
            kw_results = await _keyword_search(query, top_k, department, course_code, chunk_type, level, semester, category, section, requirement_type)
            if kw_results:
                results = kw_results

        # --- Tier 3: Metadata + ILIKE search (catch-all for entity names, codes) ---
        if not results:
            meta_results = await _metadata_search(query, top_k, department, course_code, chunk_type, level, semester, category, section, requirement_type)
            if meta_results:
                results = meta_results

        # --- Fallback: if department filter was too restrictive, retry without it ---
        if not results and department:
            results = []
            if embedding:
                vec_results = await _vectordb_client.search_by_vector(
                    collection_name="bylaw", vector=embedding, limit=top_k * 3
                )
                if vec_results:
                    for doc in vec_results:
                        if doc.score < -999:
                            continue
                        meta = doc.metadata or {}
                        if not _match_filters(meta, None, course_code, chunk_type, level, semester, category, section, requirement_type):
                            continue
                        results.append(_build_result(doc.text, doc.score, meta))
                        if len(results) >= top_k:
                            break
            if not results:
                kw_results = await _keyword_search(query, top_k, None, course_code, chunk_type, level, semester, category, section, requirement_type)
                if kw_results:
                    results = kw_results
            if not results:
                meta_results = await _metadata_search(query, top_k, None, course_code, chunk_type, level, semester, category, section, requirement_type)
                if meta_results:
                    results = meta_results

        if not results:
            return "No matching bylaw content found in the database."

        # --- Format output ---
        lines = [f"--- Result {i+1} (relevance: {r['score']}) ---" for i, r in enumerate(results)]
        for i, r in enumerate(results):
            meta = r["metadata"]
            tags = []
            if meta.get("course_code"): tags.append(f"Course: {meta['course_code']}")
            if meta.get("course_name"): tags.append(f"Name: {meta['course_name']}")
            if meta.get("department"): tags.append(f"Dept: {meta['department']}")
            if meta.get("category"): tags.append(f"Category: {meta['category']}")
            if meta.get("chunk_type"): tags.append(f"Type: {meta['chunk_type']}")
            if meta.get("prerequisites"): tags.append(f"Prereq: {meta['prerequisites']}")
            if meta.get("credit_hours"): tags.append(f"Credits: {meta['credit_hours']}")
            if meta.get("requirement_type"): tags.append(f"Req: {meta['requirement_type']}")
            if tags:
                lines.append(f"[{' | '.join(tags)}]")
            lvl = meta.get("level")
            sem = meta.get("semester")
            if lvl is not None and sem is not None:
                rel_sem = ((int(sem) - 1) % 2) + 1
                lines.append(f"[Relative: Level {lvl}, {'First' if rel_sem == 1 else 'Second'} Semester]")
            lines.append(r["text"])
            if i < len(results) - 1:
                lines.append("")
        return "\n".join(lines)
    except Exception as e:
        logger.error("search_bylaw_chunks failed: %s", e, exc_info=True)
        return f"Search failed due to a database error. Please try again."


async def main():
    await _init()
    logger.info("pgvector server initialized (embedding model + vector DB connected)")
    await mcp.run_stdio_async()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
