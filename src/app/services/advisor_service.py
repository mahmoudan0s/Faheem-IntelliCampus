import json
import logging
import re
from typing import Optional

from app.prompts.advisor_prompt import ADVISOR_SYSTEM_PROMPT, RESPONSE_FORMAT_INSTRUCTION

logger = logging.getLogger("uvicorn")

_BYLAW_KEYWORDS = re.compile(
    r"(course|bylaw|regulation|prerequisite|GPA|grade|semester|study.?plan|"
    r"credit|graduat|elective|compulsory|department|program|"
    r"reinforcement learning|data warehouse|operating system|algorithm)", re.I
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

        raw_tools = await self._mcp_manager.get_all_tools()
        groq_tools = self._mcp_manager.tool_schemas_for_groq(raw_tools)

        # Pre-fetch bylaw context and inject into user message
        context_parts = []
        if _BYLAW_KEYWORDS.search(question):
            search_args = self._parse_search_params(question, department)
            bylaw_result = await self._search_bylaw(**search_args)
            if bylaw_result:
                context_parts.append(f"Bylaw search results:\n{bylaw_result}")

        # Pre-fetch student profile if code is given
        student_profile = None
        if student_code:
            student_profile = await self._fetch_student_profile(student_code)
            if student_profile:
                context_parts.append(f"Student profile:\n{student_profile}")

        user_content = question
        if context_parts:
            user_content = "\n\n".join(context_parts) + f"\n\nStudent question: {question}"
        if student_code:
            user_content += f"\n\nMy student code is: {student_code}"
        if department:
            user_content += f"\n\nMy department is: {department}"

        messages = [
            {"role": "system", "content": ADVISOR_SYSTEM_PROMPT + "\n\n" + RESPONSE_FORMAT_INSTRUCTION},
            {"role": "user", "content": user_content},
        ]

        max_rounds = 2
        for _round in range(max_rounds):
            try:
                response = self._llm_service.chat_completion(
                    messages=messages,
                    tools=groq_tools if groq_tools else None,
                    tool_choice="auto" if groq_tools else None,
                    max_tokens=1024,
                    temperature=0,
                )
            except Exception as e:
                logger.error("LLM API call failed (round %d): %s", _round, e)
                return (
                    "## Answer\nI'm sorry, I encountered an error processing your request. "
                    "Please try again later."
                )

            if not response or not response.choices:
                logger.error("LLM returned empty response (round %d)", _round)
                return "## Answer\nNo answer could be generated."

            msg = response.choices[0].message

            if not msg.tool_calls:
                return msg.content or (
                    "## Answer\nI've gathered information but need more details to give a complete answer. "
                    "Please clarify your question."
                )

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                server_name, tool_name = self._mcp_manager.parse_tool_name(tc.function.name)
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    result = await self._mcp_manager.call_tool(server_name, tool_name, args)

                    content_parts = []
                    for item in result.content:
                        if hasattr(item, "text"):
                            content_parts.append(item.text)
                        else:
                            content_parts.append(str(item))
                    result_text = "\n".join(content_parts) if content_parts else "No data returned."

                    logger.info("Tool %s called with args=%s, isError=%s, response_len=%d",
                                tc.function.name, args, result.isError, len(result_text))

                    if result.isError:
                        result_text = f"Error: {result_text}"

                except Exception as e:
                    logger.error("Tool call failed %s: %s", tc.function.name, e)
                    result_text = f"Error executing {tc.function.name}: {str(e)}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

        return (
            "## Answer\nI've gathered information but need more details to give a complete answer. "
            "Please clarify your question."
        )

    @staticmethod
    def _parse_search_params(question: str, department: Optional[str]) -> dict:
        q = question.strip().rstrip("?")
        q_lower = q.lower()

        # Parse department from question if not already provided
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

        # Department listing questions
        if re.search(r'what departments|list departments|faculty departments|departments.*faculty', q_lower):
            args["query"] = "faculty departments"
            args["top_k"] = 5

        # Elective questions
        if re.search(r'elective|choose.*course|optional', q_lower):
            args["query"] = "elective courses"
            args["top_k"] = 8
            if "chunk_type" not in args:
                args["chunk_type"] = "course_group"

        # Compulsory questions
        if re.search(r'compulsory|required.*course|mandatory|core.*course', q_lower):
            args["query"] = "compulsory courses"
            args["top_k"] = 8
            if "chunk_type" not in args:
                args["chunk_type"] = "course_group"

        # Parse level from "year N" or "level N"
        m = re.search(r'(?:year|level)\s*(\d)', question, re.I)
        if m:
            args["level"] = int(m.group(1))

        # Parse semester: "semester N" or "first/second semester"
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

    async def _fetch_student_profile(self, student_code: str) -> Optional[str]:
        try:
            sql_tool_name = "sqlserver__get_student_profile"
            result = await self._mcp_manager.call_tool("sqlserver", "get_student_profile", {"student_code": student_code})
            parts = []
            for item in result.content:
                if hasattr(item, "text"):
                    parts.append(item.text)
                else:
                    parts.append(str(item))
            return "\n".join(parts) if parts else None
        except Exception as e:
            logger.warning("Student profile fetch failed (server may be disabled): %s", e)
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
