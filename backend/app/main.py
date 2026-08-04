"""Tessera task scheduling application."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os
import logging

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Tessera",
    description="Self-hosted task scheduling that respects the real shape of your day.",
    version="0.1.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
)


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint for container orchestration."""
    return {"status": "healthy"}


@app.on_event("startup")
async def startup_event():
    """Run startup tasks."""
    logger.info("Tessera starting up")


@app.on_event("shutdown")
async def shutdown_event():
    """Run shutdown tasks."""
    logger.info("Tessera shutting down")


# Placeholder: in Stage 9, serve the frontend build here
# frontend_path = os.path.join(os.path.dirname(__file__), "../../frontend/dist")
# if os.path.exists(frontend_path):
#     app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
