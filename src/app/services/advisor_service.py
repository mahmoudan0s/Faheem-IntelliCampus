import asyncio
import json
import logging
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

5. Your FIRST response MUST be tool call(s). No text before tools.
6. After results, answer immediately. Don't call extra tools unnecessarily.
7. Never describe your tool-calling process — just call silently."""

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
                        "description": t["function"]["description"],
                        "parameters": t["function"]["parameters"]})
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
        except asyncio.TimeoutError:
            logger.warning("Tool ranker timed out after %ds", TOOL_RANKER_TIMEOUT)
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
            _fb("sqlserver__get_student_profile", "Get full student profile: name, email, level, GPA, program, department, specialization", {"student_code": {"type": "string"}})
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
                user_content = f"Student profile:\n{profile_text}\n\nStudent question: {question}"
            user_content += f"\n\nMy student code is: {student_code}"
        if department:
            user_content += f"\n\nMy department is: {department}"

        # --- Rank tools (select up to 5 most relevant) ---
        selected_names = await self._rank_tools(question, groq_tools, profile_text, department)
        selected_tools = self._filter_tools(groq_tools, selected_names)
        current_timeout = 30
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

        # --- LLM conversation loop with tool calling ---
        max_rounds = 4
        round_messages = messages[:]

        for attempt in range(2):
            msg = None

            for _round in range(max_rounds):
                try:
                    tc = "auto" if selected_tools else None
                    loop = asyncio.get_running_loop()
                    response = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: self._llm_service.chat_completion(
                                messages=round_messages,
                                tools=selected_tools if selected_tools else None,
                                tool_choice=tc,
                                max_tokens=1024,
                                temperature=0,
                            ),
                        ),
                        timeout=current_timeout,
                    )
                except asyncio.TimeoutError:
                    logger.warning("LLM timed out after %ds (round %d, attempt %d)", current_timeout, _round, attempt + 1)
                    break
                except Exception as e:
                    logger.error("LLM API call failed (round %d, attempt %d): %s", _round, attempt + 1, e)
                    break

                if not response or not response.choices:
                    logger.error("LLM returned empty response (round %d, attempt %d)", _round, attempt + 1)
                    break

                msg = response.choices[0].message

                if not msg.tool_calls:
                    logger.info("LLM stopped at round %d — content=%r, tool_calls=%s",
                                _round, msg.content, msg.tool_calls)
                    if msg.content:
                        return msg.content
                    break

                logger.info("Round %d, attempt %d — tool_choice=%s, msg.tool_calls=%d",
                            _round, attempt + 1, tc, len(msg.tool_calls))
                logger.info("Round %d, attempt %d — tool call names: %s",
                            _round, attempt + 1, [c.function.name for c in msg.tool_calls])

                round_messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {"id": c.id, "type": "function",
                         "function": {"name": c.function.name, "arguments": c.function.arguments}}
                        for c in msg.tool_calls
                    ],
                })

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
                            except (json.JSONDecodeError, TypeError):
                                pass

                        if result.isError:
                            result_text = f"Error: {result_text}"

                    except Exception as e:
                        logger.error("Tool call failed %s: %s", tc_call.function.name, e)
                        result_text = f"Error executing {tc_call.function.name}: {str(e)}"

                    round_messages.append({
                        "role": "tool",
                        "tool_call_id": tc_call.id,
                        "content": result_text,
                    })
            else:
                # All rounds completed without a final text answer
                if msg and msg.content:
                    return msg.content

        # --- Fallback if LLM failed (timeout / error / max rounds) ---
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
            return await self._llm_service.generate(
                system_prompt=ADVISOR_SYSTEM_PROMPT + "\n\n" + RESPONSE_FORMAT_INSTRUCTION,
                user_prompt=question,
                max_output_tokens=1024,
                temperature=0.3,
            )
        except Exception as e:
            logger.error("Fallback LLM failed: %s", e)
            return "## Answer\nI'm currently unavailable. Please try again later."
