from fastapi import FastAPI
from app.api.v1.health import router as health_router

app = FastAPI(
    title="FraudGuard AI",
    version="1.0.0"
)

app.include_router(
    health_router,
    prefix="/api/v1",
    tags=["Health"]
)


@app.get("/")
def root():
    return {
        "message": "FraudGuard AI is running"
    }