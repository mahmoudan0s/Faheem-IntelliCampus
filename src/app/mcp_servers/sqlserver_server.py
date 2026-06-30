import asyncio
import logging
import os
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from helpers.confg import get_settings
from app.database.sqlserver import SQLServerConnection

logger = logging.getLogger("mcp-sqlserver")

mcp = FastMCP("sqlserver-server")

_db: Optional[SQLServerConnection] = None


async def _init():
    global _db
    if _db is not None:
        return
    settings = get_settings()
    _db = SQLServerConnection(
        host=settings.SQL_SERVER_HOST,
        port=settings.SQL_SERVER_PORT,
        database=settings.SQL_SERVER_DATABASE,
        username=settings.SQL_SERVER_USERNAME,
        password=settings.SQL_SERVER_PASSWORD,
        driver=settings.SQL_SERVER_DRIVER,
    )
    await _db.connect()


@mcp.tool()
async def get_student_profile(student_code: str) -> Optional[dict]:
    """Get a student's personal and academic profile: name, department, specialization, level, GPA, bylaw."""
    await _init()
    query = """
        SELECT u.FullName, s.StudentCode, d.DepartmentName AS department,
               sp.Name AS specialization, s.Level, s.Gpa, s.BylawId
        FROM Students s
        JOIN Users u ON s.UserId = u.UserId
        LEFT JOIN Departments d ON s.DepartmentId = d.DepartmentId
        LEFT JOIN Specializations sp ON s.SpecializationId = sp.SpecializationId
        WHERE s.StudentCode = ?
    """
    result = await _db.fetch_one(query, (student_code,))
    if not result:
        return None
    return {
        "name": result["FullName"],
        "student_code": result["StudentCode"],
        "department": result["department"],
        "specialization": result["specialization"],
        "level": result["Level"],
        "gpa": float(result["Gpa"]) if result["Gpa"] else None,
        "bylaw_id": result["BylawId"],
    }


@mcp.tool()
async def get_completed_courses(student_code: str) -> list[dict]:
    """Get courses the student has completed with grades earned."""
    await _init()
    rows = await _db.fetch_all(
        """SELECT c.CourseCode, c.CourseName, c.CreditHours, g.Title AS grade
           FROM Students s
           JOIN Grades g ON s.UserId = g.StudentId
           JOIN Courses c ON g.CourseId = c.CourseId
           WHERE s.StudentCode = ? AND g.Status = 'passed'
           ORDER BY g.GradedAt""",
        (student_code,),
    )
    return [
        {"course_code": r["CourseCode"], "course_name": r["CourseName"],
         "credit_hours": int(r["CreditHours"]) if r["CreditHours"] else 0, "grade": r["grade"]}
        for r in rows
    ]


@mcp.tool()
async def get_current_courses(student_code: str) -> list[dict]:
    """Get courses the student is currently registered in this semester."""
    await _init()
    rows = await _db.fetch_all(
        """SELECT c.CourseCode, c.CourseName, c.CreditHours, cl.Day, cl.StartTime, cl.EndTime, cl.Room,
                  u.FullName AS instructor
           FROM Students s
           JOIN StudentCourses sc ON s.UserId = sc.StudentId
           JOIN Courses c ON sc.CourseId = c.CourseId
           LEFT JOIN Classes cl ON sc.ClassId = cl.ClassId
           LEFT JOIN Users u ON cl.InstructorId = u.UserId
           WHERE s.StudentCode = ? AND sc.Status = 1
           ORDER BY cl.Day, cl.StartTime""",
        (student_code,),
    )
    return [
        {"course_code": r["CourseCode"], "course_name": r["CourseName"],
         "credit_hours": int(r["CreditHours"]) if r["CreditHours"] else 0,
         "instructor": r["instructor"], "day": r["Day"],
         "time": f"{r['StartTime']}-{r['EndTime']}" if r.get("StartTime") else None,
         "room": r["Room"]}
        for r in rows
    ]


@mcp.tool()
async def get_failed_courses(student_code: str) -> list[dict]:
    """Get courses the student has failed."""
    await _init()
    rows = await _db.fetch_all(
        """SELECT c.CourseCode, c.CourseName, c.CreditHours, g.Title AS grade, g.GradedAt
           FROM Students s
           JOIN Grades g ON s.UserId = g.StudentId
           JOIN Courses c ON g.CourseId = c.CourseId
           WHERE s.StudentCode = ? AND g.Status = 'failed'
           ORDER BY g.GradedAt""",
        (student_code,),
    )
    return [
        {"course_code": r["CourseCode"], "course_name": r["CourseName"],
         "credit_hours": int(r["CreditHours"]) if r["CreditHours"] else 0,
         "grade": r["grade"]}
        for r in rows
    ]


@mcp.tool()
async def get_schedule(student_code: str) -> list[dict]:
    """Get the student's current weekly class schedule."""
    await _init()
    rows = await _db.fetch_all(
        """SELECT c.CourseCode, c.CourseName, s.Day, s.StartTime, s.EndTime, s.Location AS room, s.InstructorName AS instructor
           FROM Students stu
           JOIN Schedules s ON stu.UserId = s.StudentId
           JOIN Courses c ON s.CourseId = c.CourseId
           WHERE stu.StudentCode = ?
           ORDER BY s.Day, s.StartTime""",
        (student_code,),
    )
    return [
        {"course": r["CourseName"], "course_code": r["CourseCode"], "day": r["Day"],
         "time": f"{r['StartTime']}-{r['EndTime']}" if r.get("StartTime") else None,
         "room": r["room"], "instructor": r["instructor"]}
        for r in rows
    ]


@mcp.tool()
async def check_course_registration(student_code: str, course_code: str) -> dict:
    """Check if a student is eligible to register for a course. Checks prerequisites, duplicates, and prior completion."""
    await _init()

    course = await _db.fetch_one(
        "SELECT CourseId, CourseCode, CourseName FROM Courses WHERE CourseCode = ?", (course_code,)
    )
    if not course:
        return {"allowed": False, "reason": f"Course {course_code} not found", "missing": []}

    student = await _db.fetch_one(
        "SELECT UserId FROM Students WHERE StudentCode = ?", (student_code,)
    )
    if not student:
        return {"allowed": False, "reason": f"Student {student_code} not found", "missing": []}

    student_id = student["UserId"]
    course_id = course["CourseId"]

    passed = await _db.fetch_one(
        """SELECT 1 FROM Grades
           WHERE StudentId = ? AND CourseId = ? AND Status = 'passed'""",
        (student_id, course_id),
    )
    if passed:
        return {"allowed": False, "reason": "Already completed this course", "missing": []}

    registered = await _db.fetch_one(
        "SELECT 1 FROM StudentCourses WHERE StudentId = ? AND CourseId = ? AND Status = 1",
        (student_id, course_id),
    )
    if registered:
        return {"allowed": False, "reason": "Already registered in this course", "missing": []}

    prereqs = await _db.fetch_all(
        """SELECT c.CourseCode, c.CourseName FROM CoursePrerequisites cp
           JOIN Courses c ON cp.PrerequisiteCourseId = c.CourseId
           WHERE cp.CourseId = ?""",
        (course_id,),
    )

    missing = []
    for p in prereqs:
        passed_prereq = await _db.fetch_one(
            "SELECT 1 FROM Grades WHERE StudentId = ? AND CourseId = (SELECT CourseId FROM Courses WHERE CourseCode = ?) AND Status = 'passed'",
            (student_id, p["CourseCode"]),
        )
        if not passed_prereq:
            missing.append(p["CourseCode"])

    if missing:
        return {"allowed": False, "reason": f"Missing prerequisites: {', '.join(missing)}", "missing": missing}

    return {"allowed": True, "reason": "Eligible to register for this course", "missing": []}


@mcp.tool()
async def get_elective_progress(student_code: str) -> list[dict]:
    """Get a student's progress toward elective requirements: completed hours, required hours, remaining per bucket."""
    await _init()
    rows = await _db.fetch_all(
        """SELECT eb.Name AS bucket_name, eb.RequiredCreditHours AS required_hours,
                  COALESCE(sebp.CompletedCreditHours, 0) AS completed_hours
           FROM StudentElectiveBucketProgresses sebp
           JOIN ElectiveBuckets eb ON sebp.ElectiveBucketId = eb.ElectiveBucketId
           JOIN Students s ON sebp.StudentId = s.UserId
           WHERE s.StudentCode = ?
           ORDER BY eb.Name""",
        (student_code,),
    )
    return [
        {"bucket_name": r["bucket_name"], "required_hours": int(r["required_hours"]),
         "completed_hours": int(r["completed_hours"]),
         "remaining_hours": max(0, int(r["required_hours"]) - int(r["completed_hours"]))}
        for r in rows
    ]


@mcp.tool()
async def get_transcript(student_code: str) -> list[dict]:
    """Get a student's complete academic transcript: all courses, grades, semesters, and status."""
    await _init()
    rows = await _db.fetch_all(
        """SELECT c.CourseCode, c.CourseName, c.CreditHours, g.Title AS grade, g.Status, g.GradedAt
           FROM Students s
           JOIN Grades g ON s.UserId = g.StudentId
           JOIN Courses c ON g.CourseId = c.CourseId
           WHERE s.StudentCode = ?
           ORDER BY g.GradedAt""",
        (student_code,),
    )
    return [
        {"course_code": r["CourseCode"], "course_name": r["CourseName"],
         "credit_hours": int(r["CreditHours"]) if r["CreditHours"] else 0,
         "grade": r["grade"], "status": r["Status"]}
        for r in rows
    ]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_init())
    mcp.run(transport="stdio")
