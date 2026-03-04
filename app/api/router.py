from fastapi import APIRouter
from app.api.v1 import resumes, jobs, metrics
from app.api import dashboard

api_router = APIRouter(prefix="/v1")
api_router.include_router(resumes.router, tags=["resumes"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(metrics.router, tags=["metrics"])

# Dashboard served at /dashboard (no version prefix)
dashboard_router = APIRouter()
dashboard_router.include_router(dashboard.router, tags=["dashboard"])
