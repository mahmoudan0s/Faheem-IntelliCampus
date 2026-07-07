import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import quote_plus

from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from helpers.confg import get_settings

logger = logging.getLogger("mcp-sqlserver")

mcp = FastMCP("sqlserver-server")

_engine: Optional[Engine] = None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        driver = settings.SQL_SERVER_DRIVER
        database = settings.SQL_SERVER_DATABASE

        if not settings.SQL_SERVER_USERNAME:
            odbc_connect = (
                f"DRIVER={{{driver}}};"
                f"SERVER={settings.SQL_SERVER_HOST};"
                f"DATABASE={database};"
                f"Trusted_Connection=yes;"
                f"TrustServerCertificate=yes"
            )
            conn_str = f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc_connect)}"
        else:
            conn_str = (
                f"mssql+pyodbc://{settings.SQL_SERVER_USERNAME}:{quote_plus(settings.SQL_SERVER_PASSWORD)}"
                f"@{settings.SQL_SERVER_HOST}:{settings.SQL_SERVER_PORT}"
                f"/{database}"
                f"?driver={driver.replace(' ', '+')}"
                f"&TrustServerCertificate=yes"
            )
        _engine = create_engine(conn_str, pool_pre_ping=True)
    return _engine


# ---------------------------------------------------------------------------
# JSON serialisation helpers
# ---------------------------------------------------------------------------

def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _row_to_dict(row) -> dict:
    return {col: _serialize(val) for col, val in row._mapping.items()}


def _execute_query(sql: str, params: dict = None) -> str:
    engine = _get_engine()
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            rows = [_row_to_dict(r) for r in result.fetchall()]
            return json.dumps({"success": True, "row_count": len(rows), "rows": rows})
    except Exception as e:
        msg = str(e)[:300]
        logger.error("Query error: %s", msg)
        return json.dumps({"success": False, "error": msg})


# ---------------------------------------------------------------------------
# Key: Students table PK is UserId, NOT StudentId.
# All FK columns (StudentCourses.StudentId, Grades.StudentId, etc.)
# reference Students.UserId.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Tools — only student-specific data. Course info stays in pgvector.
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_student_profile(student_code: str) -> str:
    """Get full student profile: name, email, level, GPA, program, department."""
    sql = """
        SELECT
            s.UserId,
            s.StudentCode,
            u.FullName,
            u.Email,
            s.Level,
            s.GPA,
            s.Program,
            s.StudentType,
            s.BylawId,
            s.DepartmentId,
            d.DepartmentName,
            s.EnrollmentDate
        FROM Students s
        JOIN Users u ON s.UserId = u.UserId
        LEFT JOIN Departments d ON s.DepartmentId = d.DepartmentId
        WHERE s.StudentCode = :student_code
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_current_courses(student_code: str) -> str:
    """Get all registered courses for a student with class schedule and instructor."""
    sql = """
        SELECT
            c.CourseCode,
            c.CourseName,
            c.CreditHours,
            sc.Semester,
            sc.Status,
            cl.GroupCode,
            cl.Day,
            cl.StartTime,
            cl.EndTime,
            r.RoomName,
            u.FullName AS Instructor
        FROM StudentCourses sc
        JOIN Courses c ON sc.CourseId = c.CourseId
        LEFT JOIN Classes cl ON sc.ClassId = cl.ClassId
        LEFT JOIN Users u ON cl.InstructorId = u.UserId
        LEFT JOIN Rooms r ON cl.RoomId = r.RoomId
        WHERE sc.StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
            AND sc.Status = 1
        ORDER BY c.CourseCode
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_transcript(student_code: str) -> str:
    """Get full academic transcript: all courses with semesters, statuses, class work score,
    total grade percentage, GradeScales from the bylaw, and letter grade derived from GradeScales."""
    sql = """
        SELECT
            subq.CourseCode,
            subq.CourseName,
            subq.CreditHours,
            subq.Semester,
            subq.Status,
            subq.ClassWorkScore,
            ROUND(subq.TotalPercentage, 2) AS TotalPercentage,
            b.GradeScales,
            (SELECT TOP 1 gs.LetterGrade
             FROM OPENJSON(b.GradeScales)
             WITH (LetterGrade NVARCHAR(5) '$.Letter', MinScore DECIMAL(5,2) '$.MinScore') AS gs
             WHERE subq.TotalPercentage >= gs.MinScore
             ORDER BY gs.MinScore DESC
            ) AS LetterGrade,
            (SELECT TOP 1 gs.Points
             FROM OPENJSON(b.GradeScales)
             WITH (Points DECIMAL(4,2) '$.Points', MinScore DECIMAL(5,2) '$.MinScore') AS gs
             WHERE subq.TotalPercentage >= gs.MinScore
             ORDER BY gs.MinScore DESC
            ) AS GradePoints
        FROM (
            SELECT
                c.CourseCode,
                c.CourseName,
                c.CreditHours,
                sc.Semester,
                sc.Status,
                sc.StudentId,
                (SELECT ISNULL(SUM(g.Score), 0) FROM Grades g
                 WHERE g.CourseId = sc.CourseId AND g.StudentId = sc.StudentId
                 AND (g.GradeType LIKE '%ClassWork%' OR g.GradeType LIKE '%Class Work%'
                      OR g.GradeType LIKE '%Assignment%' OR g.GradeType LIKE '%Homework%'
                      OR g.GradeType LIKE '%Quiz%' OR g.GradeType LIKE '%Lab%')
                ) AS ClassWorkScore,
                (SELECT CASE WHEN COUNT(*) = 0 THEN NULL
                             ELSE SUM((g.Score * 1.0 / NULLIF(g.MaxScore, 0)) * g.Weight)
                        END
                 FROM Grades g
                 WHERE g.CourseId = sc.CourseId AND g.StudentId = sc.StudentId
                ) AS TotalPercentage
            FROM StudentCourses sc
            JOIN Courses c ON c.CourseId = sc.CourseId
            WHERE sc.StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
        ) subq
        JOIN Students s ON s.UserId = subq.StudentId
        JOIN Bylaws b ON b.BylawId = s.BylawId
        ORDER BY subq.Semester, subq.CourseCode
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_completed_courses(student_code: str) -> str:
    """Get all completed/passed courses (Status=2). Useful for prerequisite checks."""
    sql = """
        SELECT
            c.CourseId,
            c.CourseCode,
            c.CourseName,
            c.CreditHours
        FROM StudentCourses sc
        JOIN Courses c ON sc.CourseId = c.CourseId
        WHERE sc.StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
        AND sc.Status = 2
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_student_grades(student_code: str) -> str:
    """Get all grades: scores, weights, grade types, and grading dates."""
    sql = """
        SELECT
            c.CourseCode,
            c.CourseName,
            g.Title,
            g.Score,
            g.MaxScore,
            g.Weight,
            g.GradeType,
            g.GradedAt
        FROM Grades g
        JOIN Courses c ON g.CourseId = c.CourseId
        WHERE g.StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
        ORDER BY g.GradedAt DESC
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_semester_grades(student_code: str, semester: str) -> str:
    """Get courses and grades for a specific semester (e.g. 'Summer 2023', 'Fall 2024').
    LLM can calculate semester GPA from this."""
    sql = """
        SELECT
            sc.Semester,
            c.CourseCode,
            c.CourseName,
            c.CreditHours,
            c.CourseId,
            g.Score,
            g.MaxScore,
            g.Weight,
            g.Title,
            g.GradeType
        FROM StudentCourses sc
        JOIN Courses c ON sc.CourseId = c.CourseId
        LEFT JOIN Grades g ON sc.StudentId = g.StudentId AND sc.CourseId = g.CourseId
        WHERE sc.StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
        AND sc.Semester = :semester
    """
    return _execute_query(sql, {"student_code": student_code, "semester": semester})


@mcp.tool()
async def get_gpa_inputs(student_code: str) -> str:
    """Get current GPA, total registered hours, and total passed hours in one call."""
    sql = """
        SELECT
            s.GPA,
            SUM(c.CreditHours) AS RegisteredHours,
            SUM(CASE WHEN sc.Status = 2 THEN c.CreditHours ELSE 0 END) AS PassedHours
        FROM Students s
        LEFT JOIN StudentCourses sc ON sc.StudentId = s.UserId
        LEFT JOIN Courses c ON sc.CourseId = c.CourseId
        WHERE s.StudentCode = :student_code
        GROUP BY s.GPA
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_finished_prerequisites(student_code: str) -> str:
    """Get course codes the student has passed. Compare with bylaw prerequisites manually."""
    sql = """
        SELECT c.CourseCode
        FROM StudentCourses sc
        JOIN Courses c ON sc.CourseId = c.CourseId
        WHERE sc.StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
        AND sc.Status = 2
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_course_prerequisites(
    course_code: Optional[str] = None,
    course_name: Optional[str] = None,
) -> str:
    """Get prerequisites for a specific course. Provide course_code (e.g. 'CS213') or course_name (e.g. 'Object Oriented Programming'). At least one is required."""
    search_term = (course_code or course_name or "").strip()
    if not search_term:
        return json.dumps({"success": False, "error": "Provide course_code or course_name"})
    sql = """
        SELECT
            c.CourseCode,
            c.CourseName,
            pc.CourseCode AS PrerequisiteCode,
            pc.CourseName AS PrerequisiteName
        FROM BylawCoursePrerequisites bcp
        JOIN BylawCourses bc ON bcp.BylawCourseId = bc.BylawCourseId
        JOIN Courses c ON bc.CourseId = c.CourseId
        JOIN BylawCourses pbc ON bcp.PrerequisiteBylawCourseId = pbc.BylawCourseId
        JOIN Courses pc ON pbc.CourseId = pc.CourseId
        WHERE bc.BylawCourseId IN (
            SELECT bc2.BylawCourseId
            FROM BylawCourses bc2
            JOIN Courses c2 ON bc2.CourseId = c2.CourseId
            WHERE c2.CourseCode = :search_term
               OR c2.CourseName LIKE '%' + :search_term + '%'
        )
        ORDER BY pc.CourseCode
    """
    return _execute_query(sql, {"search_term": search_term})


@mcp.tool()
async def get_weekly_schedule(student_code: str) -> str:
    """Get weekly class schedule with days, times, rooms, and instructors."""
    sql = """
        SELECT
            c.CourseCode,
            c.CourseName,
            cl.Day,
            cl.StartTime,
            cl.EndTime,
            r.RoomName,
            u.FullName AS Instructor
        FROM StudentCourses sc
        JOIN Classes cl ON sc.ClassId = cl.ClassId
        JOIN Courses c ON sc.CourseId = c.CourseId
        LEFT JOIN Users u ON cl.InstructorId = u.UserId
        LEFT JOIN Rooms r ON cl.RoomId = r.RoomId
        WHERE sc.StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
            AND sc.Status = 1
        ORDER BY cl.Day, cl.StartTime
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_student_calendar(student_code: str) -> str:
    """Get the student's calendar events including exams, meetings, and other scheduled items."""
    sql = """
        SELECT
            Title,
            Type,
            Date,
            StartTime,
            EndTime,
            Location
        FROM Schedules
        WHERE StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
        ORDER BY Date
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_sessions(student_code: str) -> str:
    """Get lecture/lab session topics and dates for enrolled courses."""
    sql = """
        SELECT
            c.CourseCode,
            s.Topic,
            s.Date,
            s.StartTime,
            s.EndTime
        FROM StudentCourses sc
        JOIN Sessions s ON sc.ClassId = s.ClassId
        JOIN Courses c ON sc.CourseId = c.CourseId
        WHERE sc.StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
        ORDER BY s.Date
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_exam_schedule(student_code: str) -> str:
    """Get exam schedule with dates, times, and locations."""
    sql = """
        SELECT
            es.CourseCode,
            es.CourseName,
            es.Date,
            es.StartTime,
            es.EndTime,
            es.Location
        FROM ExamSchedules es
        JOIN StudentCourses sc ON sc.StudentId = es.StudentId
        JOIN Courses c ON c.CourseId = sc.CourseId AND c.CourseCode = es.CourseCode
        WHERE es.StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
            AND sc.Status = 1
        ORDER BY es.Date
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_elective_progress(student_code: str) -> str:
    """Get elective bucket progress: completed vs required hours and course counts."""
    sql = """
        SELECT
            eb.Name,
            sep.CompletedCreditHours,
            sep.CompletedCourseCount,
            eb.RequiredCreditHours,
            eb.RequiredCourseCount,
            sep.IsLocked
        FROM StudentElectiveBucketProgresses sep
        JOIN ElectiveBuckets eb ON sep.ElectiveBucketId = eb.ElectiveBucketId
        WHERE sep.StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_elective_bucket_courses(bucket_id: int) -> str:
    """Get courses available in a specific elective bucket."""
    sql = """
        SELECT
            eb.Name,
            c.CourseCode,
            c.CourseName,
            c.CreditHours
        FROM ElectiveBucketCourses ebc
        JOIN Courses c ON ebc.CourseId = c.CourseId
        JOIN ElectiveBuckets eb ON ebc.ElectiveBucketId = eb.ElectiveBucketId
        WHERE eb.ElectiveBucketId = :bucket_id
    """
    return _execute_query(sql, {"bucket_id": bucket_id})


@mcp.tool()
async def get_student_department(student_code: str) -> str:
    """Get the student's primary assigned department from the Students table. Always call this first to know the student's department before checking cross-department eligibility."""
    sql = """
        SELECT d.DepartmentName, d.DepartmentId
        FROM Students s
        LEFT JOIN Departments d ON s.DepartmentId = d.DepartmentId
        WHERE s.StudentCode = :student_code
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_student_departments(student_code: str) -> str:
    """Get departments the student is enrolled in (for multi-department students)."""
    sql = """
        SELECT d.DepartmentName
        FROM StudentDepartments sd
        JOIN Departments d ON sd.DepartmentId = d.DepartmentId
        WHERE sd.StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_department_info(department_id: int) -> str:
    """Get detailed information about a department."""
    sql = "SELECT * FROM Departments WHERE DepartmentId = :department_id"
    return _execute_query(sql, {"department_id": department_id})


@mcp.tool()
async def get_completed_hours(student_code: str) -> str:
    """Get total completed/passed credit hours."""
    sql = """
        SELECT SUM(c.CreditHours) AS CompletedHours
        FROM StudentCourses sc
        JOIN Courses c ON sc.CourseId = c.CourseId
        WHERE sc.StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
        AND sc.Status = 2
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_registered_hours(student_code: str) -> str:
    """Get total currently registered credit hours."""
    sql = """
        SELECT SUM(c.CreditHours) AS RegisteredHours
        FROM StudentCourses sc
        JOIN Courses c ON sc.CourseId = c.CourseId
        WHERE sc.StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
        AND sc.Status = 0
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_student_attendance(student_code: str) -> str:
    """Get attendance records with dates and statuses."""
    sql = """
        SELECT
            c.CourseCode,
            a.Date,
            a.Status
        FROM Attendances a
        JOIN Classes cl ON a.SessionId = cl.ClassId
        JOIN Courses c ON cl.CourseId = c.CourseId
        WHERE a.StudentId = (SELECT UserId FROM Students WHERE StudentCode = :student_code)
        ORDER BY a.Date
    """
    return _execute_query(sql, {"student_code": student_code})


@mcp.tool()
async def get_student_reminders(student_code: str) -> str:
    """Get the student's reminders and upcoming events."""
    sql = """
        SELECT *
        FROM [dbo].[Reminders]
        WHERE StudentId = (SELECT UserId FROM [dbo].[Students] WHERE StudentCode = :student_code)
        ORDER BY [Date]
    """
    return _execute_query(sql, {"student_code": student_code})


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def main():
    logger.info("SQL Server MCP server started (IntelliCampusDb)")
    await mcp.run_stdio_async()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
