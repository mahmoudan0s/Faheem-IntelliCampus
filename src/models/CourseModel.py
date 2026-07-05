from sqlalchemy.future import select
from sqlalchemy import func
from .BaseDataModel import BaseDataModel
from .db_schemes import Course
from .enums.DataBaseEnum import DataBaseEnum
import uuid

class CourseModel(BaseDataModel):

    def __init__(self, db_client: object):
        super().__init__(db_client=db_client)
        self.db_client = db_client

    @classmethod
    async def create_instance(cls, db_client: object):
        instance = cls(db_client)
        return instance

    async def create_course(self, course: Course):
        async with self.db_client() as session:
            async with session.begin():
                session.add(course)
                await session.flush()
                await session.refresh(course)
        return course

    async def get_course_by_code(self, code: str):
        async with self.db_client() as session:
            async with session.begin():
                query = select(Course).where(Course.code == code)
                result = await session.execute(query)
                return result.scalar_one_or_none()

    async def get_course_by_id(self, course_id: uuid.UUID):
        async with self.db_client() as session:
            async with session.begin():
                query = select(Course).where(Course.id == course_id)
                result = await session.execute(query)
                return result.scalar_one_or_none()

    async def get_all_courses(self):
        async with self.db_client() as session:
            async with session.begin():
                query = select(Course).order_by(Course.code)
                result = await session.execute(query)
                return result.scalars().all()
