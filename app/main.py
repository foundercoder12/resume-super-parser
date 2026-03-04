from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.logging import configure_logging
from app.api.router import api_router, dashboard_router
from app.api.middleware.request_id import RequestIdMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    configure_logging()
    # Ensure storage directory exists
    from app.storage.file_store import file_store
    file_store()
    yield
    # Shutdown (close Redis pool if open)
    from app.dependencies import _redis_pool
    if _redis_pool:
        await _redis_pool.aclose()


app = FastAPI(
    title="Resume Parser API",
    version="1.0.0",
    description="Microservice for parsing resume PDFs into structured JSON.",
    lifespan=lifespan,
)

app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(dashboard_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
