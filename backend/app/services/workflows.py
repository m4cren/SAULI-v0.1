"""Confirmed-item storage and search workflows with upload compensation."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from app.core.config import Settings
from app.models.schemas import FoundItemAnalysis, MatchResult, SearchInput, SearchResponse
from app.services.ai import AIService
from app.services.images import ImageData
from app.services.matching import (
    deterministic_features,
    final_score,
    is_eligible,
    location_similarity,
    normalize,
    rank_matches,
    time_proximity,
)
from app.services.supabase import SupabaseService


def server_now() -> datetime:
    return datetime.now(timezone.utc)


def search_document(analysis: FoundItemAnalysis) -> str:
    values = [
        analysis.generic_name,
        analysis.object_name,
        *analysis.alternative_names,
        analysis.category,
        analysis.subcategory,
        *analysis.colors,
        *analysis.material,
        analysis.brand or "",
        analysis.model_or_variant or "",
        *analysis.visible_markings,
        *analysis.functional_components,
        analysis.condition,
        *analysis.condition_details,
        *analysis.patterns,
        *analysis.distinctive_features,
        analysis.likely_use,
        analysis.short_description,
        analysis.extraction_summary,
    ]
    return normalize(" ".join(value for value in values if value))


async def store_confirmed_item_events(
    front: ImageData,
    back: ImageData,
    location: str,
    found_at: datetime,
    idempotency_key: str,
    analysis: FoundItemAnalysis,
    settings: Settings,
    database: SupabaseService,
):
    item_id = str(uuid4())
    front_path = f"found-items/{item_id}/front.{front.extension}"
    back_path = f"found-items/{item_id}/back.{back.extension}"
    uploaded: list[str] = []
    saved = False
    try:
        yield {
            "stage": "uploading",
            "message": "Uploading two validated images to private Storage.",
        }
        # Add before upload: a timeout may occur after Storage accepts the object.
        uploaded.append(front_path)
        await database.upload(front_path, front.data, front.content_type)
        uploaded.append(back_path)
        await database.upload(back_path, back.data, back.content_type)

        yield {
            "stage": "saving",
            "message": "Saving the confirmed item details.",
        }
        record = {
            "id": item_id,
            "idempotency_key": idempotency_key,
            "status": "available",
            "found_location": location,
            "found_at": found_at.isoformat(),
            "front_image_path": front_path,
            "back_image_path": back_path,
            "views_consistent": analysis.views_consistent,
            "generic_name": analysis.generic_name,
            "object_name": analysis.object_name,
            "alternative_names": analysis.alternative_names,
            "object_count": analysis.object_count,
            "category": analysis.category,
            "subcategory": analysis.subcategory,
            "colors": analysis.colors,
            "materials": analysis.material,
            "brand": analysis.brand,
            "model_or_variant": analysis.model_or_variant,
            "visible_markings": analysis.visible_markings,
            "functional_components": analysis.functional_components,
            "condition": analysis.condition,
            "condition_details": analysis.condition_details,
            "patterns": analysis.patterns,
            "distinctive_features": analysis.distinctive_features,
            "likely_use": analysis.likely_use,
            "short_description": analysis.short_description,
            "extraction_summary": analysis.extraction_summary,
            "confidence": analysis.confidence,
            "needs_review": analysis.needs_review,
            "analysis_model": settings.ollama_model,
            "analysis_json": analysis.model_dump(),
            "search_document": search_document(analysis),
        }
        row = await database.insert("found_items", record)
        saved = True
        item = await database.public_item(row)
        yield {
            "stage": "complete",
            "message": "Record saved and temporary image previews created.",
            "item": item.model_dump(mode="json"),
        }
    finally:
        if not saved:
            await asyncio.shield(database.cleanup(uploaded))


async def search_items(
    search: SearchInput,
    image: ImageData | None,
    settings: Settings,
    database: SupabaseService,
    ai: AIService,
) -> SearchResponse:
    search_id = str(uuid4())
    query_path = f"searches/{search_id}/query.{image.extension}" if image else None
    request_saved = False
    try:
        if image:
            await database.upload(query_path, image.data, image.content_type)
        await database.insert(
            "search_requests",
            {
                "id": search_id,
                "anonymous_session_id": str(search.anonymous_session_id),
                "idempotency_key": str(search.idempotency_key),
                "description": search.description,
                "last_seen_location": search.last_seen_location,
                "last_seen_at": search.last_seen_at.isoformat(),
                "category_filter": search.category,
                "primary_color_filter": search.primary_color,
                "brand_filter": search.brand,
                "query_image_path": query_path,
                "processing_status": "processing",
            },
        )
        request_saved = True
    finally:
        if image and not request_saved:
            await asyncio.shield(database.cleanup([query_path]))

    try:
        query = await ai.extract_query(search, image.data if image else None)
        await database.update(
            "search_requests", search_id, {"query_analysis_json": query.model_dump()}
        )

        shortlist: list[dict] = []
        async for candidate in database.eligible_items(search.last_seen_at):
            # Defense in depth if the database function is changed accidentally.
            if not is_eligible(candidate, search.last_seen_at):
                continue
            analysis = FoundItemAnalysis.model_validate(candidate["analysis_json"])
            candidate["analysis_json"] = analysis.model_dump()
            features = deterministic_features(query, candidate["analysis_json"])
            location = location_similarity(
                search.last_seen_location, candidate["found_location"]
            )
            time = time_proximity(candidate["found_at"], search.last_seen_at)
            shortlist.append(
                {
                    "candidate": candidate,
                    "features": features,
                    "location": location,
                    "time": time,
                }
            )
            shortlist.sort(
                key=lambda value: (
                    -(
                        value["features"] * 0.20
                        + value["location"] * 0.15
                        + value["time"] * 0.10
                    ),
                    str(value["candidate"]["id"]),
                )
            )
            del shortlist[settings.deterministic_shortlist_limit :]

        scored: list[dict] = []
        rows_by_id: dict[str, dict] = {}
        for entry in shortlist[: settings.ai_rerank_limit]:
            candidate = entry["candidate"]
            images: list[bytes] = []
            if image:
                front, back = await asyncio.gather(
                    database.download(candidate["front_image_path"]),
                    database.download(candidate["back_image_path"]),
                )
                images = [image.data, front, back]
            assessment = await ai.compare(query, candidate, images)
            current = await database.get_item(candidate["id"])
            if not is_eligible(current, search.last_seen_at):
                continue
            scored.append(
                {
                    "search_request_id": search_id,
                    "found_item_id": str(candidate["id"]),
                    "final_score": final_score(
                        assessment.ai_similarity,
                        entry["features"],
                        entry["location"],
                        entry["time"],
                    ),
                    "ai_similarity": assessment.ai_similarity,
                    "deterministic_feature_score": entry["features"],
                    "location_score": entry["location"],
                    "time_proximity_score": entry["time"],
                    "matched_features": assessment.matched_features,
                    "conflicting_features": assessment.conflicting_features,
                    "explanation": assessment.explanation,
                    "needs_review": (
                        assessment.needs_review
                        or candidate["analysis_json"]["needs_review"]
                    ),
                }
            )
            rows_by_id[str(candidate["id"])] = current

        ranked = rank_matches(scored)
        database_rows = []
        for rank, result in enumerate(ranked, start=1):
            database_rows.append(
                {
                    "search_request_id": search_id,
                    "found_item_id": result["found_item_id"],
                    "rank": rank,
                    "eligible": True,
                    "ai_similarity_score": result["ai_similarity"] * 100,
                    "deterministic_feature_score": result[
                        "deterministic_feature_score"
                    ]
                    * 100,
                    "location_score": result["location_score"] * 100,
                    "time_proximity_score": result["time_proximity_score"] * 100,
                    "final_score": result["final_score"],
                    "matched_features": result["matched_features"],
                    "conflicting_features": result["conflicting_features"],
                    "explanation": result["explanation"],
                    "needs_review": result["needs_review"],
                    "ai_model": settings.ollama_model,
                    "score_breakdown": {
                        "ai_similarity": result["ai_similarity"],
                        "deterministic_feature_score": result[
                            "deterministic_feature_score"
                        ],
                        "location_score": result["location_score"],
                        "time_proximity_score": result["time_proximity_score"],
                    },
                    "ai_match_json": {
                        "candidate_id": result["found_item_id"],
                        "ai_similarity": result["ai_similarity"],
                        "matched_features": result["matched_features"],
                        "conflicting_features": result["conflicting_features"],
                        "explanation": result["explanation"],
                        "needs_review": result["needs_review"],
                    },
                }
            )
        await database.save_matches(database_rows)

        selected = [
            value for value in ranked if value["final_score"] >= settings.match_min_score
        ][: settings.match_limit]
        results = []
        for value in selected:
            item = await database.public_item(rows_by_id[value["found_item_id"]])
            results.append(
                MatchResult(
                    item=item,
                    score=round(value["final_score"], 2),
                    **{
                        field: value[field]
                        for field in (
                            "ai_similarity",
                            "deterministic_feature_score",
                            "location_score",
                            "time_proximity_score",
                            "matched_features",
                            "conflicting_features",
                            "explanation",
                            "needs_review",
                        )
                    },
                )
            )

        await database.update(
            "search_requests",
            search_id,
            {
                "processing_status": "completed",
                "result_count": len(results),
                "completed_at": server_now().isoformat(),
            },
        )
        return SearchResponse(search_id=search_id, results=results)
    except Exception:
        try:
            await database.update(
                "search_requests",
                search_id,
                {
                    "processing_status": "failed",
                    "error_message": "Search processing failed.",
                    "completed_at": server_now().isoformat(),
                },
            )
        except Exception:
            pass
        raise
