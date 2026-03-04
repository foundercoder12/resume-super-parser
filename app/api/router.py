from fastapi import APIRouter
from app.api.v1 import resumes, jobs

api_router = APIRouter(prefix="/v1")
api_router.include_router(resumes.router, tags=["resumes"])
api_router.include_router(jobs.router, tags=["jobs"])
