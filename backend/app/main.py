import logging
from contextlib import asynccontextmanager

from app.api.v1 import router as api_v1_router
from app.core.config import settings
from app.ml.inference import ModelNotLoadedError, inference
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("fraudguard")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        inference.load()
        logger.info(
            "Model loaded: %s (schema %s)",
            inference.version,
            inference.schema_version,
        )
    except ModelNotLoadedError as exc:
        logger.warning("Model not loaded: %s", exc)
        logger.warning("Run `python -m app.ml.train_bootstrap` to create one.")
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "model_loaded": inference.is_loaded,
        "model_version": inference.version if inference.is_loaded else None,
    }
