"""Run from backend/: uvicorn app.main:app --reload --port 8000."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.errors import ServiceError
from app.services.ai import AIService
from app.services.supabase import SupabaseService


def create_app(settings: Settings | None = None, database=None, ai=None) -> FastAPI:
    settings = settings or get_settings()
    db = database or SupabaseService(settings)

    @asynccontextmanager
    async def lifespan(application):
        yield
        if database is None:
            await db.close()

    application = FastAPI(
        title="SAULI Prototype API", version="0.1.0", lifespan=lifespan
    )
    application.state.settings = settings
    application.state.database = db
    application.state.ai = ai or AIService(settings)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            settings.frontend_origin.rstrip("/"),
            "https://sauli-v0-1.vercel.app",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Accept", "X-Idempotency-Key"],
    )

    @application.exception_handler(ServiceError)
    async def service_error(_request: Request, error: ServiceError):
        return JSONResponse(
            status_code=error.status_code, content={"detail": error.message}
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError):
        fields = ", ".join(
            dict.fromkeys(str(entry["loc"][-1]) for entry in error.errors())
        )
        return JSONResponse(
            status_code=422,
            content={"detail": f"Missing or invalid request fields: {fields}."},
        )

    @application.exception_handler(Exception)
    async def unexpected_error(_request: Request, _error: Exception):
        # No exception text or dependency response is exposed to the browser.
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An unexpected backend error occurred. Check the local configuration and try again."
            },
        )

    application.include_router(router)
    return application


app = create_app()
