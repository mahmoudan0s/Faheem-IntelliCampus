import asyncio
import json
import logging
import re
from typing import Optional

from app.prompts.advisor_prompt import ADVISOR_SYSTEM_PROMPT, RESPONSE_FORMAT_INSTRUCTION

logger = logging.getLogger("uvicorn")

_BYLAW_KEYWORDS = re.compile(
    r"(course|bylaw|regulation|prerequisite|GPA|grade|semester|study.?plan|"
    r"credit|graduat|elective|compulsory|department|program|"
    r"reinforcement learning|data.?warehous|operating system|algorithm|"
    r"content|describe|contain|topic|syllabus|learn|objectiv|"
    r"[A-Z]{2,3}\d{3})", re.I
)


class AdvisorService:
    def __init__(self, mcp_manager, llm_service):
        self._mcp_manager = mcp_manager
        self._llm_service = llm_service

    async def process_question(
        self,
        question: str,
        student_code: Optional[str] = None,
        department: Optional[str] = None,
    ) -> str:
        model = self._llm_service.model_id
        if not model:
            return await self._fallback(question)

        try:
            raw_tools = await self._mcp_manager.get_all_tools()
            groq_tools = self._mcp_manager.tool_schemas_for_groq(raw_tools)
        except Exception as e:
            logger.error("Tool discovery failed: %s", e, exc_info=True)
            raw_tools = []
            groq_tools = []

        if not groq_tools:
            # Minimal fallback — covers the most used tools
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
            _fb("sqlserver__get_student_profile", "Get full student profile", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_student_department", "Get student's primary department (always call this first for dept info)", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_current_courses", "Get registered courses with schedule", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_completed_courses", "Get completed/passed courses (Status=2)", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_transcript", "Get full academic transcript", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_student_grades", "Get all grades with scores and weights", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_semester_grades", "Get grades for a semester", {"student_code": {"type": "string"}, "semester": {"type": "integer"}})
            _fb("sqlserver__get_gpa_inputs", "Get GPA, registered hours, passed hours", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_finished_prerequisites", "Get course codes the student passed", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_weekly_schedule", "Get weekly class schedule", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_exam_schedule", "Get exam schedule", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_elective_progress", "Get elective bucket progress", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_elective_bucket_courses", "Get courses in an elective bucket", {"bucket_id": {"type": "integer"}})
            _fb("sqlserver__get_student_departments", "Get student's departments", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_completed_hours", "Get total completed credit hours", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_registered_hours", "Get total registered credit hours", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_student_attendance", "Get attendance records", {"student_code": {"type": "string"}})
            _fb("sqlserver__get_student_reminders", "Get reminders", {"student_code": {"type": "string"}})
            _fb("pgvector__search_bylaw_chunks", "Search bylaw regulations and course info", {
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

        context_parts = []

        # Pre-fetch bylaw context when relevant
        bylaw_q = re.sub(r'\bmy\b|\byour\b|\bI\b|\bRegistered\b|\bregister\b', '', question, flags=re.I)
        if _BYLAW_KEYWORDS.search(bylaw_q):
            search_args = self._parse_search_params(question, department)
            bylaw_result = await self._search_bylaw(**search_args)
            if bylaw_result:
                context_parts.append(f"Bylaw search results:\n{bylaw_result}")

        # Pre-fetch student data when student_code is provided
        if student_code:
            profile_result = await self._search_student("get_student_profile", {"student_code": student_code})
            if profile_result:
                context_parts.append(f"Student profile:\n{profile_result}")
            completed = await self._search_student("get_completed_courses", {"student_code": student_code})
            if completed:
                context_parts.append(f"Completed courses:\n{completed}")
            current = await self._search_student("get_current_courses", {"student_code": student_code})
            if current:
                context_parts.append(f"Current registration:\n{current}")

        # Skip LLM only for student-data questions (covered by pre-fetch) or
        # registration questions with course code. General course info questions
        # (contents, prerequisites, etc.) should still go through the LLM.
        q_lower = question.lower()
        _student_data_keywords = [
            "which department", "what department", "my department", "department am i",
            "took", "taken", "completed", "transcript",
            "gpa",
            "profile", "my info", "my information", "who am i",
            "current", "now", "this semester", "taking", "registered", "schedule",
        ]
        _is_registration_q = bool(re.search(r'\b[A-Z]{2,3}\d{3}\b', question)) or (
            "register" in q_lower or "can i" in q_lower
        )
        _is_student_data_q = any(k in q_lower for k in _student_data_keywords)
        if context_parts and (_is_registration_q or _is_student_data_q):
            logger.info("Simple question detected — skipping LLM, using fallback")
            return self._answer_from_context(context_parts, question)

        user_content = question
        if context_parts:
            user_content = "\n\n".join(context_parts) + f"\n\nStudent question: {question}"
        if student_code:
            user_content += f"\n\nMy student code is: {student_code}"
        if department:
            user_content += f"\n\nMy department is: {department}"

        messages = [
            {"role": "system", "content": (
                f"{ADVISOR_SYSTEM_PROMPT}\n\n{RESPONSE_FORMAT_INSTRUCTION}\n\n"
                "CRITICAL RULES:\n"
                "1. The user message contains bylaw search results. Use them for regulations, course info, prerequisites.\n"
                "2. You MUST call sqlserver__* tools to verify the student's PERSONAL data — do NOT guess or assume.\n"
                "   - Registration questions → call get_completed_courses + get_current_courses\n"
                "   - GPA questions → call get_gpa_inputs or get_student_grades\n"
                "   - Schedule questions → call get_weekly_schedule or get_exam_schedule\n"
                "   - Any question with student_code → always call get_student_profile first\n"
                "3. Your FIRST response MUST be one or more tool calls. Do NOT write any text before calling tools.\n"
                "4. After tool results come back, analyze them and write the answer. Do NOT call more tools unless needed.\n"
                "5. Never describe your tool-calling process, never say 'I'm checking' or 'let me look up' — just call silently."
            )},
            {"role": "user", "content": user_content},
        ]

        max_rounds = 4
        LLM_TIMEOUT = 30

        for attempt in range(2):
            round_messages = messages[:]

            for _round in range(max_rounds):
                try:
                    tc = "auto" if groq_tools else None
                    loop = asyncio.get_running_loop()
                    response = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: self._llm_service.chat_completion(
                                messages=round_messages,
                                tools=groq_tools if groq_tools else None,
                                tool_choice=tc,
                                max_tokens=1024,
                                temperature=0,
                            ),
                        ),
                        timeout=LLM_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning("LLM timed out after %ds (round %d, attempt %d)", LLM_TIMEOUT, _round, attempt + 1)
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
                if msg and msg.content:
                    return msg.content

        if context_parts:
            return self._answer_from_context(context_parts, question)
        return (
            "## Answer\nI'm sorry, I'm having trouble processing your request. "
            "Please try asking in a different way or try again later."
        )

    @staticmethod
    def _parse_search_params(question: str, department: Optional[str]) -> dict:
        q = question.strip().rstrip("?")
        q_lower = q.lower()

        # Strip question words and filler to get key terms
        q = re.sub(r'\b(what|are|the|for|is|tell|me|about|of|in|a|an|do|does|can|how|would|i|my|you|your)\b', '', q, flags=re.I)
        q = re.sub(r'\s+', ' ', q).strip()
        if not q:
            q = q_lower.strip()

        if not department:
            dept_map = {
                r'information\s+systems|(?<!\w)IS(?!\w)': "information_systems",
                r'computer\s+science|(?<!\w)CS(?!\w)': "computer_science",
                r'information\s+technology|(?<!\w)IT(?!\w)': "information_technology",
                r'decision\s+support|(?<!\w)DS(?!\w)': "decision_support",
                r'artificial\s+intelligence|(?<!\w)AI(?!\w)': "artificial_intelligence",
            }
            for pattern, dept_name in dept_map.items():
                if re.search(pattern, question, re.I):
                    department = dept_name
                    break

        args = {"query": q, "top_k": 3}
        if department:
            args["department"] = department

        if re.search(r'what departments|list departments|faculty departments|departments.*faculty', q_lower):
            args["query"] = "faculty departments"
            args["top_k"] = 5

        if re.search(r'elective|choose.*course|optional', q_lower):
            args["query"] = "elective courses"
            args["top_k"] = 8
            if "chunk_type" not in args:
                args["chunk_type"] = "course_group"

        if re.search(r'compulsory|required.*course|mandatory|core.*course', q_lower):
            args["query"] = "compulsory courses"
            args["top_k"] = 8
            if "chunk_type" not in args:
                args["chunk_type"] = "course_group"

        if re.search(r'prerequisite|require.*before|need.*before|what.*take.*before', q_lower):
            args["top_k"] = 5
            if "chunk_type" not in args:
                args["chunk_type"] = "course_description"

        if re.search(r'attendance|minimum.*(percent|attend|class)|absent|miss|dismiss', q_lower):
            args["query"] = "attendance policy minimum percentage"
            args["top_k"] = 5
            if "chunk_type" not in args:
                args["chunk_type"] = "attendance_rules"

        if re.search(r'credit.*(hour|total|graduat|need|require)|graduat.*(requirement|condition|credit|hour)|total.*hour|how.*many.*credit|hour.*graduat', q_lower):
            args["query"] = "graduation requirements"
            args["top_k"] = 5
            if "chunk_type" not in args:
                args["chunk_type"] = "graduation_requirements"

        # Extract course code (e.g. IS313, CS462, AI424) and use as filter
        m = re.search(r'\b([A-Z]{2,3}\d{3})\b', question, re.I)
        if m:
            args["course_code"] = m.group(1).upper()

        m = re.search(r'(?:year|level)\s*(\d)', question, re.I)
        if m:
            args["level"] = int(m.group(1))

        m = re.search(r'semester\s*(\d)', question, re.I)
        if m:
            sem = int(m.group(1))
            if sem <= 2:
                args["semester"] = sem
            elif sem <= 4:
                args["level"] = 2
                args["semester"] = sem - 2
            elif sem <= 6:
                args["level"] = 3
                args["semester"] = sem - 4
            else:
                args["level"] = 4
                args["semester"] = sem - 6

        m = re.search(r'(first|second)\s+semester', question, re.I)
        if m:
            args["semester"] = 1 if m.group(1).lower() == "first" else 2

        return args

    @staticmethod
    def _answer_from_context(context_parts: list, question: str) -> str:
        q = question.lower()

        # Extract student department from pre-fetched profile
        student_dept = None
        for part in context_parts:
            if part.startswith("Student profile:"):
                try:
                    data = json.loads(part[len("Student profile:\n"):])
                    if data.get("success") and data["rows"]:
                        student_dept = (data["rows"][0].get("DepartmentName") or "").strip().lower()
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass

        # Extract course code from question
        course_code = None
        m = re.search(r'\b([A-Z]{2,3}\d{3})\b', question)
        if m:
            course_code = m.group(1).upper()

        # The faculty has exactly 5 departments: AI, CS, DS, IT, IS.
        # Max cross-department courses = 2 (total across all other departments).
        prefix_to_dept = {
            "IS": "information systems",
            "CS": "computer science",
            "IT": "information technology",
            "AI": "artificial intelligence",
            "DS": "operations research and decision support",
        }

        # Cross-department allowed: {student_dept: {offering_dept: [(code, name), ...]}}
        cross_dept_allowed = {
            "information systems": {
                "operations research and decision support": [
                    ("DS456", "Project Management"), ("DS342", "Data Analytics"),
                    ("DS321", "Linear and Integer Programming"), ("DS312", "Decision Support and Future Studies Methodologies"),
                ],
                "artificial intelligence": [
                    ("AI331", "Theories of Mind"), ("AI311", "Introduction to Logic"),
                ],
                "computer science": [
                    ("CS371", "High Performance Computing"), ("CS432", "Theory of Computation"),
                ],
                "information technology": [
                    ("IT495", "Selected Topics in Information Technology I"),
                    ("IT331", "Data Communication"), ("IT352", "Pattern Recognition"),
                ],
            },
            "computer science": {
                "operations research and decision support": [
                    ("DS321", "Linear and Integer Programming"), ("DS331", "Systems Modeling and Simulation"),
                    ("DS341", "Learning from Data"), ("DS342", "Data Analytics"),
                    ("DS456", "Project Management"), ("DS343", "Probabilistic Reasoning"),
                ],
                "information systems": [
                    ("IS313", "Data Warehousing"), ("IS333", "Web-Based Information Systems Development"),
                    ("IS436", "Enterprise Mobile Applications Development"), ("IS322", "Information Retrieval"),
                    ("IS435", "Usability Engineering"),
                ],
                "information technology": [
                    ("IT495", "Selected Topics in Information Technology I"),
                    ("IT331", "Data Communication"), ("IT352", "Pattern Recognition"),
                ],
                "artificial intelligence": [
                    ("AI331", "Theories of Mind"), ("AI311", "Introduction to Logic"),
                ],
            },
            "operations research and decision support": {
                "artificial intelligence": [
                    ("AI331", "Theories of Mind"), ("AI311", "Introduction to Logic"),
                    ("AI495", "Selected Topics in Artificial Intelligence I"),
                ],
                "information systems": [
                    ("IS313", "Data Warehousing"), ("IS333", "Web-Based Information Systems Development"),
                    ("IS436", "Enterprise Mobile Applications Development"), ("IS322", "Information Retrieval"),
                ],
                "computer science": [
                    ("CS371", "High Performance Computing"), ("CS432", "Theory of Computation"),
                ],
                "information technology": [
                    ("IT351", "Information Theory and Data Compression"), ("IT331", "Data Communication"),
                    ("IT432", "Communication Technology"), ("IT495", "Selected Topics in Information Technology I"),
                ],
            },
            "information technology": {
                "operations research and decision support": [
                    ("DS321", "Linear and Integer Programming"), ("DS342", "Data Analytics"),
                    ("DS456", "Project Management"), ("DS312", "Decision Support and Future Studies Methodologies"),
                ],
                "information systems": [
                    ("IS333", "Web-Based Information Systems Development"),
                    ("IS436", "Enterprise Mobile Applications Development"), ("IS322", "Information Retrieval"),
                ],
                "computer science": [
                    ("CS371", "High Performance Computing"), ("CS432", "Theory of Computation"),
                ],
                "artificial intelligence": [
                    ("AI331", "Theories of Mind"), ("AI311", "Introduction to Logic"),
                ],
            },
            "artificial intelligence": {
                "operations research and decision support": [
                    ("DS342", "Data Analytics"), ("DS456", "Project Management"),
                ],
                "information systems": [
                    ("IS333", "Web-Based Information Systems Development"),
                    ("IS436", "Enterprise Mobile Applications Development"), ("IS322", "Information Retrieval"),
                ],
                "computer science": [
                    ("CS371", "High Performance Computing"), ("CS432", "Theory of Computation"),
                ],
                "information technology": [
                    ("IT352", "Pattern Recognition"), ("IT453", "Advanced Pattern Recognition"),
                    ("IT495", "Selected Topics in Information Technology I"), ("IT331", "Data Communication"),
                ],
            },
        }

        # Build a reverse lookup: (code, name_lower) → (offering_dept, student_dept)
        # for quick matching
        code_to_info = {}
        name_to_info = {}
        for s_dept, offering_dict in cross_dept_allowed.items():
            for o_dept, courses in offering_dict.items():
                for c_code, c_name in courses:
                    code_to_info[c_code.upper()] = (o_dept, s_dept, c_name)
                    name_to_info[c_name.lower()] = (o_dept, s_dept, c_name)

        # Only codes in cross_dept_allowed are true cross-department electives.
        # Foundation courses (CS111, CS112, etc.) are common faculty curriculum, not cross-dept electives.
        cross_dept_codes = set()
        for s_dept, offering_dict in cross_dept_allowed.items():
            for o_dept, courses in offering_dict.items():
                for c_code, c_name in courses:
                    cross_dept_codes.add(c_code.upper())

        def _count_cross_used(context_parts):
            used = 0
            for part in context_parts:
                if part.startswith("Current registration:"):
                    try:
                        reg_data = json.loads(part[len("Current registration:\n"):])
                        if reg_data.get("success") and reg_data["rows"]:
                            for row in reg_data["rows"]:
                                rc = (row.get("CourseCode") or "").upper()
                                if rc in cross_dept_codes and row.get("Status") in (0, 1):
                                    used += 1
                    except (json.JSONDecodeError, KeyError, IndexError):
                        pass
            return used

        if course_code and student_dept and student_dept != "none":
            cc = course_code.upper()
            # Check by course code first
            if cc in code_to_info:
                offering_dept, allowed_for_dept, cname = code_to_info[cc]
                if allowed_for_dept != student_dept:
                    return (
                        f"## Answer\nNo, you cannot register for **{cc}** ({cname}).\n\n"
                        f"This course is in the cross-department list for "
                        f"{allowed_for_dept.replace('_', ' ').title()} students, "
                        f"but you belong to {student_dept.replace('_', ' ').title()}."
                    )
                cross_used = _count_cross_used(context_parts)
                if cross_used >= 2:
                    return (
                        f"## Answer\nNo, you cannot register for **{cc}** ({cname}).\n\n"
                        f"The faculty has 5 departments (AI, CS, DS, IT, IS) and you can take "
                        f"a maximum of 2 courses from other departments total. "
                        f"You have already used {cross_used} of 2 cross-department slots."
                    )
                return (
                    f"## Answer\nYes, you can register for **{cc}** ({cname}), offered by the "
                    f"{offering_dept.replace('_', ' ').title()} department.\n"
                    f"Remember: max 2 courses across all other departments (AI, CS, DS, IT, IS). "
                    f"Used {cross_used} of 2 cross-department slots. Ensure prerequisites are met."
                )

            # Code not in cross-dept list — check by prefix
            prefix = course_code[:2].upper() if course_code[:2].upper() in prefix_to_dept else None
            course_dept = prefix_to_dept.get(prefix) if prefix else None

            if course_dept and course_dept != student_dept:
                # Check if this course is in THIS student's cross-dept list by offering dept
                student_allowed = cross_dept_allowed.get(student_dept, {})
                if course_dept in student_allowed:
                    cross_used = _count_cross_used(context_parts)
                    course_names = [n for c, n in student_allowed[course_dept]]
                    return (
                        f"## Answer\nCourses from {course_dept.replace('_', ' ').title()} "
                        f"allowed for your department include: {', '.join(course_names)}. "
                        f"Max 2 courses across all 5 departments (AI, CS, DS, IT, IS). "
                        f"Used {cross_used} of 2 slots. "
                        f"Verify prerequisites in the bylaw."
                    )
                return (
                    f"## Answer\nNo, you cannot register for **{cc}**.\n\n"
                    f"It is offered by the {course_dept.replace('_', ' ').title()} department, "
                    f"but you belong to {student_dept.replace('_', ' ').title()}. "
                    f"No courses from {course_dept.replace('_', ' ').title()} are in the "
                    f"approved cross-department list for your department. "
                    f"Remember: max 2 courses across all 5 departments (AI, CS, DS, IT, IS)."
                )

            if course_dept == student_dept:
                return (
                    f"## Answer\nYes, **{cc}** is in your department "
                    f"({student_dept.replace('_', ' ').title()}). "
                    f"Check prerequisites in the bylaw."
                )

        # Registration question without a recognized code
        if "register" in q or "can i" in q:
            if not student_dept or student_dept == "none":
                return (
                    f"## Answer\nYour department has not been assigned yet. "
                    f"You need to be assigned before registering for courses."
                )
            # Try matching by name from question text
            q_lower = question.lower()
            for stud_dept, offering_dict in cross_dept_allowed.items():
                if stud_dept != student_dept:
                    continue
                for offering_dept, courses in offering_dict.items():
                    for c_code, c_name in courses:
                        if c_name.lower() in q_lower:
                            cross_used = _count_cross_used(context_parts)
                            if cross_used >= 2:
                                return (
                                    f"## Answer\n{c_name} ({c_code}) is in the approved cross-department list "
                                    f"(offered by {offering_dept.replace('_', ' ').title()}). "
                                    f"But you already used {cross_used} of 2 cross-department slots. "
                                    f"Max 2 courses across all 5 departments (AI, CS, DS, IT, IS)."
                                )
                            return (
                                f"## Answer\nYes, you can register for **{c_name}** ({c_code}), "
                                f"offered by the {offering_dept.replace('_', ' ').title()} department. "
                                f"Max 2 courses across all 5 departments (AI, CS, DS, IT, IS). "
                                f"Used {cross_used} of 2 slots. "
                                f"Check prerequisites in the bylaw."
                            )
            return (
                f"## Answer\nPlease specify the course code (e.g., AI424, CS371) so I can check eligibility."
            )

        # --- Common question handlers ---

        # "what courses did I take" / "my completed courses"
        if any(w in q for w in ["course", "took", "taken", "completed", "transcript"]):
            for part in context_parts:
                if part.startswith("Completed courses:"):
                    try:
                        data = json.loads(part[len("Completed courses:\n"):])
                        if data.get("success") and data["rows"]:
                            rows = data["rows"]
                            total = sum(r.get("CreditHours", 0) or 0 for r in rows)
                            lines = [f"You have completed **{len(rows)}** courses (**{total}** credit hours):\n"]
                            for r in rows:
                                lines.append(f"- **{r.get('CourseCode')}** — {r.get('CourseName')} ({r.get('CreditHours', 0)} cr)")
                            return "\n".join(lines)
                    except (json.JSONDecodeError, KeyError, IndexError):
                        pass
                    break

        # "what is my GPA"
        if "gpa" in q:
            for part in context_parts:
                if part.startswith("Student profile:"):
                    try:
                        data = json.loads(part[len("Student profile:\n"):])
                        if data.get("success") and data["rows"]:
                            r = data["rows"][0]
                            gpa = r.get("GPA", "N/A")
                            name = r.get("FullName", "Student")
                            return f"## Answer\n{name}, your current cumulative GPA is **{gpa}**."
                    except (json.JSONDecodeError, KeyError, IndexError):
                        pass
                    break

        # "my profile" / "my info"
        if any(w in q for w in ["profile", "my info", "my information", "who am i"]):
            for part in context_parts:
                if part.startswith("Student profile:"):
                    try:
                        data = json.loads(part[len("Student profile:\n"):])
                        if data.get("success") and data["rows"]:
                            r = data["rows"][0]
                            dept = r.get("DepartmentName") or "Not assigned"
                            spec = r.get("SpecializationName") or "None"
                            return (
                                f"## Answer\n**{r.get('FullName')}** — Level {r.get('Level')}, "
                                f"{dept}\n\n"
                                f"- **Code:** {r.get('StudentCode')}\n"
                                f"- **Email:** {r.get('Email')}\n"
                                f"- **GPA:** {r.get('GPA')}\n"
                                f"- **Program:** {'Bachelor' if r.get('Program') == 0 else 'Other'}\n"
                                f"- **Department:** {dept}\n"
                                f"- **Specialization:** {spec}"
                            )
                    except (json.JSONDecodeError, KeyError, IndexError):
                        pass
                    break

        # Bylaw content questions (course contents, prerequisites, topics, descriptions)
        if any(w in q for w in ["content", "contain", "topic", "syllabus", "describe", "what is", "what are", "prerequisite", "requisite"]):
            for part in context_parts:
                if part.startswith("Bylaw search results:"):
                    body = part[len("Bylaw search results:\n"):].strip()
                    if body:
                        # Extract relevant course info sections from bylaw results
                        lines = body.split("\n")
                        # Remove low-relevance boilerplate chunks
                        filtered = []
                        for line in lines:
                            if any(skip in line.lower() for skip in ["course category", "add and drop", "article (16)", "curriculum classifies"]):
                                continue
                            filtered.append(line)
                        if filtered:
                            return "## Answer\n" + "\n".join(filtered[:30])
                    break

        # "which department am I in" / "my department"
        if any(w in q for w in ["which department", "what department", "my department", "department am i"]):
            if student_dept and student_dept != "none":
                name = "Unknown"
                for part in context_parts:
                    if part.startswith("Student profile:"):
                        try:
                            data = json.loads(part[len("Student profile:\n"):])
                            if data.get("success") and data["rows"]:
                                name = data["rows"][0].get("FullName", "Student")
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
                return (
                    f"## Answer\n{name}, you are in the **{student_dept.replace('_', ' ').title()}** department."
                )
            return "## Answer\nYour department has not been assigned yet in the system."

        # "what am I taking now" / "current courses" / "my schedule"
        if any(w in q for w in ["current", "now", "this semester", "taking", "registered", "schedule"]):
            for part in context_parts:
                if part.startswith("Current registration:"):
                    try:
                        data = json.loads(part[len("Current registration:\n"):])
                        if data.get("success") and data["rows"]:
                            active = [r for r in data["rows"] if r.get("Status") == 1]
                            if active:
                                lines = [f"You are currently registered for **{len(active)}** courses:\n"]
                                for r in active:
                                    lines.append(
                                        f"- **{r.get('CourseCode')}** — {r.get('CourseName')} "
                                        f"({r.get('CreditHours', 0)} cr, {r.get('Day')} {r.get('StartTime')[:5]}-{r.get('EndTime')[:5]}, {r.get('Room')})"
                                    )
                                return "\n".join(lines)
                            else:
                                return "## Answer\nYou are not currently registered for any courses."
                    except (json.JSONDecodeError, KeyError, IndexError):
                        pass
                    break

        # Generic fallback — structured summary
        summary_parts = []
        for part in context_parts:
            if part.startswith("Student profile:"):
                try:
                    data = json.loads(part[len("Student profile:\n"):])
                    if data.get("success") and data["rows"]:
                        r = data["rows"][0]
                        summary_parts.append(
                            f"**{r.get('FullName')}** — Level {r.get('Level')}, "
                            f"{r.get('DepartmentName') or 'No dept'}, GPA: {r.get('GPA')}"
                        )
                except (json.JSONDecodeError, KeyError, IndexError):
                    summary_parts.append(part[:200])
            elif part.startswith("Completed courses:"):
                try:
                    data = json.loads(part[len("Completed courses:\n"):])
                    if data.get("success"):
                        summary_parts.append(f"**Completed:** {data.get('row_count', 0)} courses")
                except json.JSONDecodeError:
                    pass
            elif part.startswith("Current registration:"):
                try:
                    data = json.loads(part[len("Current registration:\n"):])
                    if data.get("success"):
                        active = sum(1 for r in data.get("rows", []) if r.get("Status") == 1)
                        completed = sum(1 for r in data.get("rows", []) if r.get("Status") == 2)
                        summary_parts.append(f"**Registration:** {active} active, {completed} completed")
                except json.JSONDecodeError:
                    pass

        if summary_parts:
            return "## Answer\n" + "\n".join(summary_parts) + "\n\nPlease ask a more specific question for details."
        return "## Answer\nI found the information above. Please ask a more specific question."

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
