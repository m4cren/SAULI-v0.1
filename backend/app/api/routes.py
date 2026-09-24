"""Application workflows and safe item/retrieval endpoints."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.errors import ServiceError
from app.models.schemas import (
    FoundItem,
    FoundItemAnalysis,
    FoundItemReviewRequest,
    HealthResponse,
    PipelineEvent,
    RetrievalRequest,
    RetrievalResponse,
    SearchInput,
    SearchResponse,
)
from app.services.ai import protect_document_analysis
from app.services.images import read_upload
from app.services.workflows import (
    search_items,
    server_now,
    store_confirmed_item_events,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request):
    database = request.app.state.database
    database_check = getattr(database, "database_health", database.health)
    storage_check = getattr(database, "storage_health", database.health)
    database_status, storage_status, ollama = await asyncio.gather(
        database_check(), storage_check(), request.app.state.ai.health()
    )
    return HealthResponse(database=database_status, storage=storage_status, ollama=ollama)


def _found_at(value: str | None) -> datetime:
    found_at = server_now()
    if not value:
        return found_at
    try:
        overridden = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if overridden.tzinfo is None or overridden.utcoffset() is None:
            raise ValueError
        return overridden.astimezone(timezone.utc)
    except ValueError:
        raise ServiceError(
            "The developer found date/time must include a timezone offset.", 422
        ) from None


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def _confirmed_analysis(value: str) -> FoundItemAnalysis:
    try:
        payload = json.loads(value, object_pairs_hook=_unique_json_object)
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        analysis = FoundItemAnalysis.model_validate(
            payload,
            strict=True,
            context={"exact_types": True},
        )
    except (ValueError, TypeError, ValidationError):
        raise ServiceError(
            "The corrected item details are invalid. Review every field and try again.",
            422,
        ) from None
    return protect_document_analysis(analysis)


@router.post("/api/found-items/analyze", response_model=FoundItemAnalysis)
async def analyze_found_item(
    request: Request,
    front_image: Annotated[UploadFile, File()],
    back_image: Annotated[UploadFile, File()],
):
    max_bytes = request.app.state.settings.max_image_bytes
    front, back = await asyncio.gather(
        read_upload(front_image, max_bytes), read_upload(back_image, max_bytes)
    )
    return protect_document_analysis(
        await request.app.state.ai.analyze_found_item(
            front.data,
            back.data,
            front.content_type,
            back.content_type,
        )
    )


@router.post("/api/found-items/reconcile-review", response_model=FoundItemAnalysis)
async def reconcile_found_item_review(
    payload: FoundItemReviewRequest,
    request: Request,
):
    """Update related semantic fields before any upload or database write occurs."""
    return await request.app.state.ai.reconcile_found_item_review(
        payload.analysis,
        payload.previous_summary,
        payload.corrected_summary,
    )


@router.post("/api/found-items/confirm-and-store", response_model=FoundItem)
async def confirm_and_store(
    request: Request,
    front_image: Annotated[UploadFile, File()],
    back_image: Annotated[UploadFile, File()],
    found_location: Annotated[str, Form(min_length=2, max_length=200)],
    analysis_json: Annotated[str, Form(min_length=2, max_length=50_000)],
    idempotency_key: Annotated[UUID, Header(alias="X-Idempotency-Key")],
    found_at_override: Annotated[str | None, Form()] = None,
):
    found_at = _found_at(found_at_override)
    location = found_location.strip()
    if len(location) < 2:
        raise ServiceError("Enter a specific location where the item was found.", 422)
    analysis = _confirmed_analysis(analysis_json)
    max_bytes = request.app.state.settings.max_image_bytes
    front, back = await asyncio.gather(
        read_upload(front_image, max_bytes), read_upload(back_image, max_bytes)
    )
    events = store_confirmed_item_events(
        front,
        back,
        location,
        found_at,
        str(idempotency_key),
        analysis,
        request.app.state.settings,
        request.app.state.database,
    )
    if "text/event-stream" in request.headers.get("accept", ""):

        async def stream():
            try:
                async for event in events:
                    yield "data: " + PipelineEvent.model_validate(event).model_dump_json(exclude_none=True) + "\n\n"
            except ServiceError as error:
                yield "data: " + PipelineEvent(stage="error", message=error.message, status=error.status_code).model_dump_json(exclude_none=True) + "\n\n"
            except Exception:
                yield "data: " + PipelineEvent(stage="error", message="The item could not be processed. Please check backend configuration and retry.", status=500).model_dump_json(exclude_none=True) + "\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    async for event in events:
        if event["stage"] == "complete":
            return FoundItem.model_validate(event["item"])
    raise ServiceError("The item was not saved.")


@router.post("/api/matches/search", response_model=SearchResponse)
async def search(request: Request):
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    image = None
    try:
        if content_type == "application/json":
            payload = await request.json()
        elif content_type in ("multipart/form-data", "application/x-www-form-urlencoded"):
            async with request.form(
                max_files=1,
                max_fields=9,
                max_part_size=request.app.state.settings.max_image_bytes + 1,
            ) as form:
                if len(form.multi_items()) != len(form):
                    raise ServiceError("Submit each search field only once.", 400)
                payload = dict(form)
                query_image = payload.pop("query_image", None)
                if query_image is not None:
                    if not isinstance(query_image, StarletteUploadFile):
                        raise ServiceError("The query photo must be an image upload.", 400)
                    image = await read_upload(
                        query_image, request.app.state.settings.max_image_bytes
                    )
        else:
            raise ServiceError("Send the search as JSON or a multipart form.", 400)
        search_input = SearchInput.model_validate(payload)
    except (ValueError, ValidationError):
        raise ServiceError("Provide a description, last-seen location, and a date/time with a timezone offset. Check the optional filters.", 422) from None
    return await search_items(search_input, image, request.app.state.settings, request.app.state.database, request.app.state.ai)


@router.get("/api/found-items/{item_id}", response_model=FoundItem)
async def item_details(item_id: UUID, request: Request):
    database = request.app.state.database
    return await database.public_item(await database.get_item(str(item_id)))


@router.post("/api/retrievals/{item_id}/simulate", response_model=RetrievalResponse)
async def simulate_retrieval(
    item_id: UUID, payload: RetrievalRequest, request: Request
):
    # Prototype only. This is not QR verification or authorization for a real lock.
    result = await request.app.state.database.simulate_retrieval(
        str(item_id),
        str(payload.search_request_id),
        str(payload.anonymous_session_id),
    )
    return RetrievalResponse.model_validate(result)
