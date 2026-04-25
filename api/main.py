from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from api.routers import auth, alerts, biometry, pets, guardians

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm up the ReID model on startup so the first request isn't slow
    from api.services.reid_service import get_reid_service
    get_reid_service()
    yield


app = FastAPI(
    title="Billy Pet API",
    description="Backend de biometria nasal e comunidade para tutores de pets",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(pets.router, prefix=API_PREFIX)
app.include_router(biometry.router, prefix=API_PREFIX)
app.include_router(alerts.router, prefix=API_PREFIX)
app.include_router(guardians.router, prefix=API_PREFIX)


@app.get("/health", tags=["infra"])
async def health():
    return {"status": "ok"}
