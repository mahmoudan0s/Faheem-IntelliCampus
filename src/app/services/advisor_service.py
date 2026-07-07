import asyncio
import json
import logging
import time
from typing import Optional

from app.prompts.advisor_prompt import ADVISOR_SYSTEM_PROMPT, RESPONSE_FORMAT_INSTRUCTION

logger = logging.getLogger("uvicorn")

CRITICAL_RULES = """\
CRITICAL RULES:
1. ALWAYS call at least one tool before answering. Never answer from general knowledge.

2. PGVECTOR (pgvector__search_bylaw_chunks) — call for ANY question about:
   - Course contents, topics, descriptions
   - Study plans, recommended courses per semester/level
   - Grading policies, GPA formula, letter grades, grade scale
   - Registration rules (max credit hours, summer limits, add/drop)
   - Graduation requirements, honors, field training, graduation project
   - Attendance rules, withdrawal, dismissal, suspension
   - Course codes, department info, academic regulations
   - Elective rules, compulsory course lists
   This is the academic bylaw — ESSENTIAL for advising students on rules and plans.
   Use chunk_type to narrow results, course_code for specific courses.

3. SQL SERVER (sqlserver__*) — call for ANY question about the student's PERSONAL data:
   - Profile, department, specialization, level
   - GPA, grades, transcript, completed courses
   - Current courses, weekly schedule, exam schedule, sessions
   - Attendance records, electives progress, credit hours
   - Calendar, reminders
   - Course prerequisites (use sqlserver__get_course_prerequisites with exact course_code OR full course_name; if empty, fall back to pgvector__search_bylaw_chunks with chunk_type="course_description")
   - Do NOT abbreviate course names into codes (e.g. "Object Oriented Programming" is NOT "OOP")
   - Do NOT call student-data tools for pure prerequisite questions
   These are student-specific — never available in the bylaw.

4. HYBRID questions need BOTH (call in parallel when possible):
   - "Can I register for X?" → pgvector (course info) + sqlserver (prerequisites + completed courses + department)
   - "What should I take next semester?" → pgvector (study plan + compulsory courses) + sqlserver (completed courses + GPA + hours + electives)
   - "Am I on track to graduate?" → pgvector (graduation requirements) + sqlserver (completed hours + transcript)
   - "What is my GPA?" / "Calculate my GPA" → sqlserver (semester grades). No pgvector needed — the grade scale is built-in.

5. Your very first message in the conversation MUST be tool call(s). No text before tools on the first round.
6. After you receive tool results in subsequent rounds, answer directly. Do NOT call more tools unless the data is clearly incomplete.
7. Never describe your tool-calling process — just call silently.
8. Your name is Faheem. You are the Student Academic Advisor. When a student asks about your identity, introduce yourself naturally in the Answer section. Do NOT confuse the student's profile data with your own identity."""

TOOL_RANKER_SYSTEM_PROMPT = """You are a tool selector. Given a student's question and the available tools, select the 1-5 most relevant tools needed to answer the question.

Available tools (JSON: name, description, parameters):

{tools_json}

Rules:
- Pick tools that are DIRECTLY needed to answer the student's question
- 1-2 tools for simple questions, up to 5 for complex planning questions
- Do NOT pick tools "just in case"
- For prerequisite questions, ALWAYS include sqlserver__get_course_prerequisites
- For student data questions, include the specific tool (grades, transcript, etc.)

Respond with ONLY a JSON array of tool names, nothing else.
Example: ["pgvector__search_bylaw_chunks", "sqlserver__get_course_prerequisites"]"""

TOOL_RANKER_TIMEOUT = 60


class AdvisorService:
    def __init__(self, mcp_manager, llm_service):
        self._mcp_manager = mcp_manager
        self._llm_service = llm_service

    @staticmethod
    def _keyword_tool_fallback(question: str, tools: list) -> list:
        q = question.lower()
        tool_names = {t["function"]["name"] for t in tools}
        selected = []

        if "prerequisite" in q or "prereq" in q:
            for name in ["sqlserver__get_course_prerequisites", "pgvector__search_bylaw_chunks"]:
                if name in tool_names:
                    selected.append(name)
        elif "gpa" in q or "grade" in q or "result" in q:
            for name in ["sqlserver__get_student_grades", "sqlserver__get_gpa_inputs"]:
                if name in tool_names:
                    selected.append(name)
        elif "schedule" in q or "time" in q or "class" in q:
            for name in ["sqlserver__get_weekly_schedule", "sqlserver__get_current_courses"]:
                if name in tool_names:
                    selected.append(name)
        elif "register" in q or "enroll" in q or "eligible" in q or "can i" in q:
            for name in ["pgvector__search_bylaw_chunks", "sqlserver__get_finished_prerequisites", "sqlserver__get_completed_hours"]:
                if name in tool_names:
                    selected.append(name)
        elif "transcript" in q or "report" in q:
            if "sqlserver__get_transcript" in tool_names:
                selected.append("sqlserver__get_transcript")
        elif "attend" in q or "absence" in q:
            if "sqlserver__get_student_attendance" in tool_names:
                selected.append("sqlserver__get_student_attendance")
        elif "elective" in q or "bucket" in q:
            if "sqlserver__get_elective_progress" in tool_names:
                selected.append("sqlserver__get_elective_progress")
        elif "calendar" in q or "event" in q:
            if "sqlserver__get_student_calendar" in tool_names:
                selected.append("sqlserver__get_student_calendar")
        elif "hour" in q or "credit" in q:
            for name in ["sqlserver__get_completed_hours", "sqlserver__get_registered_hours"]:
                if name in tool_names:
                    selected.append(name)

        if not selected:
            for name in ["pgvector__search_bylaw_chunks", "sqlserver__get_student_profile"]:
                if name in tool_names:
                    selected.append(name)

        logger.info("Tool ranker keyword fallback — selected: %s", selected[:5])
        return selected[:5]

    async def _rank_tools(self, question: str, tools: list,
                          profile_text: Optional[str] = None,
                          department: Optional[str] = None) -> list:
        tool_lines = [
            json.dumps({"name": t["function"]["name"],
                        "description": t["function"]["description"]})
            for t in tools
        ]
        prompt = TOOL_RANKER_SYSTEM_PROMPT.replace("{tools_json}", "\n".join(tool_lines))

        parts = [f"Student question: {question}"]
        if profile_text:
            parts.insert(0, f"Student profile:\n{profile_text}")
        if department:
            parts.append(f"Student department: {department}")
        user_content = "\n\n".join(parts)

        try:
            loop = asyncio.get_running_loop()
            t0 = time.perf_counter()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._llm_service.chat_completion(
                        messages=[
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": user_content},
                        ],
                        tools=None,
                        tool_choice=None,
                        max_tokens=200,
                        temperature=0,
                    ),
                ),
                timeout=TOOL_RANKER_TIMEOUT,
            )
            logger.info("Tool ranker completed in %.2fs", time.perf_counter() - t0)
        except asyncio.TimeoutError:
            logger.warning("Tool ranker timed out after %ds (elapsed %.2fs)", TOOL_RANKER_TIMEOUT, time.perf_counter() - t0)
            return self._keyword_tool_fallback(question, tools)
        except Exception as e:
            logger.warning("Tool ranker failed: %s", e)
            return self._keyword_tool_fallback(question, tools)

        if not response or not response.choices:
            logger.warning("Tool ranker returned empty response")
            return self._keyword_tool_fallback(question, tools)

        content = response.choices[0].message.content.strip()
        try:
            selected = json.loads(content)
            if not isinstance(selected, list):
                raise ValueError("Not a list")
            valid_names = {t["function"]["name"] for t in tools}
            selected = [s for s in selected if s in valid_names][:5]
            if selected:
                logger.info("Tool ranker selected %d tools: %s", len(selected), selected)
                return selected
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Tool ranker response parse failed: %r — %s", content, e)

        return self._keyword_tool_fallback(question, tools)

    @staticmethod
    def _filter_tools(tools: list, selected_names: list) -> list:
        return [t for t in tools if t["function"]["name"] in selected_names]

    async def process_question(
        self,
        question: str,
        student_code: Optional[str] = None,
        department: Optional[str] = None,
    ) -> str:
        model = self._llm_service.model_id
        if not model:
            return await self._fallback(question)

        # --- Discover tools from MCP servers ---
        try:
            raw_tools = await self._mcp_manager.get_all_tools()
            groq_tools = self._mcp_manager.tool_schemas_for_groq(raw_tools)
        except Exception as e:
            logger.error("Tool discovery failed: %s", e, exc_info=True)
            raw_tools = []
            groq_tools = []

        if not groq_tools:
            # Minimal fallback — covers all tools when MCP discovery fails
            groq_tools = []
            def _fb(name, desc, props):
                groq_tools.append({
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": desc,
                        "parameters": {"type": "object", "properties": props, "required": list(props.keys())},
                    },
                })
            _fb("sqlserver__get_student_profile", "Get full student profile: name, email, level, GPA, program, department", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_student_department", "Get student's primary department", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_current_courses", "Get registered courses with schedule and instructor", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_completed_courses", "Get completed/passed courses (Status=2)", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_transcript", "Get full academic transcript", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_student_grades", "Get all grades with scores and weights", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_semester_grades", "Get grades for a specific semester", {"student_code": {"type": "string"}, "semester": {"type": "string"}})
            _fb("sqlserver__get_gpa_inputs", "Get GPA, registered hours, passed hours", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_finished_prerequisites", "Get course codes the student passed", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_course_prerequisites", "Get prerequisites for a course. Pass exact course_code OR full course_name. Do not abbreviate names.", {"course_code": {"type": "string"}, "course_name": {"type": "string"}})
            _fb("sqlserver__get_weekly_schedule", "Get weekly class schedule", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_exam_schedule", "Get exam schedule", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_elective_progress", "Get elective bucket progress", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_elective_bucket_courses", "Get courses in an elective bucket", {"bucket_id": {"type": "integer"}})
            _fb("sqlserver__get_student_departments", "Get student's departments", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_completed_hours", "Get total completed credit hours", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_registered_hours", "Get total registered credit hours", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_student_attendance", "Get attendance records", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_student_reminders", "Get reminders", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_student_calendar", "Get calendar events", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_sessions", "Get lecture/lab session topics and dates", {"student_code": {"type": "string"}})
            _fb("pgvector__search_bylaw_chunks", "Search bylaw regulations, course info, study plans, grading policies, and academic rules", {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
                "department": {"type": "string"},
                "course_code": {"type": "string"},
                "chunk_type": {"type": "string"},
                "level": {"type": "integer"},
                "semester": {"type": "integer"},
            })

        logger.info("Tools discovered: %d raw, %d groq_tools — %s",
                    len(raw_tools), len(groq_tools),
                    [t["function"]["name"] for t in groq_tools])

        # --- Pre-fetch student profile ONLY (1 call — gives LLM context) ---
        user_content = question
        profile_text = None
        if student_code:
            profile_text = await self._search_student("get_student_profile", {"student_code": student_code})
            if profile_text:
                user_content = f"The student's profile:\n{profile_text}\n\nStudent question: {question}"
            user_content += f"\n\nMy student code is: {student_code}"
        if department:
            user_content += f"\n\nMy department is: {department}"

        # --- Rank tools (select up to 5 most relevant) ---
        selected_names = await self._rank_tools(question, groq_tools, profile_text, department)
        selected_tools = self._filter_tools(groq_tools, selected_names)
        current_timeout = 60
        logger.info("Tool ranker — using %d/%d tools: %s, timeout=%ds",
                    len(selected_tools), len(groq_tools),
                    [t["function"]["name"] for t in selected_tools], current_timeout)

        # --- Build messages ---
        messages = [
            {"role": "system", "content": (
                f"{ADVISOR_SYSTEM_PROMPT}\n\n{RESPONSE_FORMAT_INSTRUCTION}\n\n{CRITICAL_RULES}"
            )},
            {"role": "user", "content": user_content},
        ]

        # --- Phase 1: Select and execute tools (single LLM call + tool execution) ---
        tool_results_text = None

        for attempt in range(2):
            try:
                tc = "auto" if selected_tools else None
                loop = asyncio.get_running_loop()
                t0 = time.perf_counter()
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self._llm_service.chat_completion(
                            messages=messages,
                            tools=selected_tools if selected_tools else None,
                            tool_choice=tc,
                            max_tokens=2048,
                            temperature=0,
                        ),
                    ),
                    timeout=current_timeout,
                )
                logger.info("LLM call completed in %.2fs (attempt %d)", time.perf_counter() - t0, attempt + 1)
            except asyncio.TimeoutError:
                logger.warning("LLM timed out after %ds (attempt %d, elapsed %.2fs)", current_timeout, attempt + 1, time.perf_counter() - t0)
                continue
            except Exception as e:
                logger.error("LLM API call failed (attempt %d): %s", attempt + 1, e)
                continue

            if not response or not response.choices:
                continue

            msg = response.choices[0].message

            if not msg.tool_calls:
                if msg.content:
                    logger.info("LLM answered directly (attempt %d): %s", attempt + 1, msg.content[:100])
                    return msg.content
                continue

            logger.info("Attempt %d — tool calls: %s", attempt + 1,
                        [c.function.name for c in msg.tool_calls])

            # Execute all tool calls
            result_parts = []
            for tc_call in msg.tool_calls:
                server_name, tool_name = self._mcp_manager.parse_tool_name(tc_call.function.name)
                try:
                    args = json.loads(tc_call.function.arguments) if tc_call.function.arguments else {}
                    result = await self._mcp_manager.call_tool(server_name, tool_name, args)

                    content_parts = []
                    for item in result.content:
                        if hasattr(item, "text"):
                            content_parts.append(item.text)
                        else:
                            content_parts.append(str(item))
                    result_text = "\n".join(content_parts) if content_parts else "No data returned."

                    logger.info("Tool %s called with args=%s, isError=%s, response_len=%d",
                                tc_call.function.name, args, result.isError, len(result_text))
                    logger.info("RAW tool result (first 500): %s", result_text[:500])

                    if server_name == "sqlserver":
                        try:
                            parsed = json.loads(result_text)
                            if isinstance(parsed, dict) and parsed.get("success") is False:
                                err_msg = parsed.get("error", "Unknown error")
                                result_text = f"Error: {err_msg}"
                            elif isinstance(parsed, dict) and parsed.get("success") is True:
                                rows = parsed.get("rows", [])
                                if rows:
                                    lines = [f"Results ({len(rows)} rows):"]
                                    for i, row in enumerate(rows, 1):
                                        vals = [f"{k}: {v}" for k, v in row.items() if v is not None]
                                        lines.append(f"  {i}. {' | '.join(vals)}")
                                    result_text = "\n".join(lines)
                        except (json.JSONDecodeError, TypeError):
                            pass

                    if result.isError:
                        result_text = f"Error: {result_text}"

                except Exception as e:
                    logger.error("Tool call failed %s: %s", tc_call.function.name, e)
                    result_text = f"Error executing {tc_call.function.name}: {str(e)}"

                result_parts.append(f"Tool: {tc_call.function.name}\nArguments: {args}\nResult:\n{result_text}")

            tool_results_text = "\n\n---\n\n".join(result_parts)
            break  # Successful tool execution — exit attempt loop

        # --- Phase 2: Answer from tool results (fresh LLM call, no tools) ---
        if tool_results_text:
            answer_messages = [
                {"role": "system", "content": "You are Faheem, the Student Academic Advisor. Answer the student's question based ONLY on the data provided.\n\n"
                    "Use this format:\n## Answer\nDirect answer to the student's question.\n\n## Recommendation\nWhat the student should do next.\n\n"
                    "Rules:\n"
                    "- Answer ONLY from the provided data. Never use general knowledge.\n"
                    "- Never mention tool names, tool calls, or internal reasoning.\n"
                    "- When listing grades, show all courses with their scores and final percentages.\n"
                    "- If the data is insufficient, say what's missing.\n\n"
                    "GPA Calculation (built-in — use this directly):\n"
                    "- Formula: GPA = Total Grade Points / Total Registered Credit Hours\n"
                    "- For each course: Total Percentage = sum of (Score / MaxScore * Weight) for all grade components\n"
                    "- Grade Scale:\n"
                    "  A+ : 90% or above → 4.0 points\n"
                    "  A  : 85% to <90% → 3.7 points\n"
                    "  B+ : 80% to <85% → 3.3 points\n"
                    "  B  : 75% to <80% → 3.0 points\n"
                    "  C+ : 70% to <75% → 2.7 points\n"
                    "  C  : 65% to <70% → 2.4 points\n"
                    "  D+ : 60% to <65% → 2.2 points\n"
                    "  D  : 50% to <60% → 2.0 points\n"
                    "  F  : Less than 50% → 0.0 points\n"
                    "- Calculate GPA: For each course, convert total percentage to grade points using the scale, then GPA = sum(grade_points * credit_hours) / sum(credit_hours)"},
                {"role": "user", "content": f"{user_content}\n\n---\n\nData retrieved:\n{tool_results_text}\n\nAnswer the student's question based on this data."},
            ]
            try:
                loop = asyncio.get_running_loop()
                t0 = time.perf_counter()
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self._llm_service.chat_completion(
                            messages=answer_messages,
                            tools=None,
                            tool_choice=None,
                            max_tokens=2048,
                            temperature=0,
                        ),
                    ),
                    timeout=120,
                )
                logger.info("Answer phase completed in %.2fs", time.perf_counter() - t0)
            except asyncio.TimeoutError:
                logger.warning("Answer phase timed out after 120s (elapsed %.2fs)", time.perf_counter() - t0)
            except Exception as e:
                logger.error("Answer phase failed: %s", e)
            else:
                if response and response.choices:
                    content = response.choices[0].message.content
                    if content:
                        logger.info("Answer phase — content=%r", content[:200])
                        return content

        # --- Fallback if LLM failed ---
        return await self._fallback(question)

    async def _search_bylaw(self, **kwargs) -> Optional[str]:
        try:
            result = await self._mcp_manager.call_tool("pgvector", "search_bylaw_chunks", kwargs)
            parts = []
            for item in result.content:
                if hasattr(item, "text"):
                    parts.append(item.text)
                else:
                    parts.append(str(item))
            return "\n".join(parts) if parts else None
        except Exception as e:
            logger.warning("Bylaw search failed: %s", e)
            return None

    async def _search_student(self, tool_name: str, args: dict) -> Optional[str]:
        try:
            result = await self._mcp_manager.call_tool("sqlserver", tool_name, args)
            parts = []
            for item in result.content:
                if hasattr(item, "text"):
                    parts.append(item.text)
                else:
                    parts.append(str(item))
            return "\n".join(parts) if parts else None
        except Exception as e:
            logger.warning("Student data fetch failed (%s): %s", tool_name, e)
            return None

    async def _fallback(self, question: str) -> str:
        try:
            fallback_prompt = (
                "You are Faheem, the official Student Academic Advisor for the Faculty of Computers and Artificial Intelligence.\n\n"
                "CRITICAL — You do NOT have any tools available right now. You cannot call sqlserver or pgvector tools.\n"
                "Do NOT fabricate, simulate, or role-play tool calls, tool names, JSON tool results, chunk_id values, or retrieved data.\n"
                "Do NOT write ```json blocks that look like tool output.\n"
                "If you can answer from general academic knowledge, do so directly and honestly.\n"
                "If the question requires the student's personal records or the official bylaw (which you cannot access without tools), "
                "say clearly that you cannot reach the records right now and the student should try again shortly.\n\n"
                "Use this response format:\n\n"
                "## Answer\n\n"
                "Direct answer to the student's question, or an honest statement that the data is unavailable right now.\n\n"
                "## Recommendation\n\n"
                "What the student should do next.\n"
            )
            return await self._llm_service.generate(
                system_prompt=fallback_prompt,
                user_prompt=question,
                max_output_tokens=2048,
                temperature=0.3,
            )
        except Exception as e:
            logger.error("Fallback LLM failed: %s", e)
            return "## Answer\nI'm currently unavailable. Please try again later."
