import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from conftest import FOUND_AT, ITEM_ID, analysis, item


def image_files(png, include_front=True, include_back=True, content_type="image/png"):
    files = {}
    if include_front:
        files["front_image"] = ("front.png", png, content_type)
    if include_back:
        files["back_image"] = ("back.png", png, content_type)
    return files


def analyze(client, png, files=None):
    return client.post(
        "/api/found-items/analyze",
        files=files or image_files(png),
    )


def confirm(
    client,
    png,
    key=None,
    files=None,
    found_at_override=None,
    analysis_payload=None,
    raw_analysis=None,
    accept=None,
):
    data = {
        "found_location": "LSPU Library, second floor",
        "analysis_json": raw_analysis
        if raw_analysis is not None
        else json.dumps(analysis_payload or analysis().model_dump()),
    }
    if found_at_override is not None:
        data["found_at_override"] = found_at_override
    headers = {"X-Idempotency-Key": key or str(uuid4())}
    if accept:
        headers["Accept"] = accept
    return client.post(
        "/api/found-items/confirm-and-store",
        data=data,
        files=files or image_files(png),
        headers=headers,
    )


def search(client, last_seen_at, session_id=None, idempotency_key=None):
    session_id = session_id or str(uuid4())
    response = client.post(
        "/api/matches/search",
        data={
            "description": "black leather wallet with a fold",
            "last_seen_location": "LSPU Library",
            "last_seen_at": last_seen_at.isoformat(),
            "anonymous_session_id": session_id,
            "idempotency_key": idempotency_key or str(uuid4()),
        },
    )
    return response, session_id


def test_analysis_requires_both_images_and_never_writes(client, dependencies, png):
    database, ai = dependencies
    assert analyze(client, png, files=image_files(png, include_back=False)).status_code == 422
    assert analyze(client, png, files=image_files(png, include_front=False)).status_code == 422

    response = analyze(client, png)
    assert response.status_code == 200
    assert response.json()["object_name"] == "Black leather wallet"
    assert len(ai.found_calls) == 1
    assert database.uploads == {}
    assert database.inserts == []


def test_review_reconciliation_uses_ai_but_never_writes(client, dependencies):
    database, ai = dependencies
    current = analysis().model_dump(mode="json")
    note = "This is a yellow Nike shoe with a damaged heel, not a wallet."

    response = client.post(
        "/api/found-items/reconcile-review",
        json={
            "analysis": current,
            "correction_notes": note,
        },
    )

    assert response.status_code == 200, response.text
    assert "Corrected item details." in response.json()["extraction_summary"]
    assert len(ai.review_calls) == 1
    reviewed, notes = ai.review_calls[0]
    assert reviewed.object_name == current["object_name"]
    assert notes == note
    assert database.uploads == {}
    assert database.inserts == []
    assert database.rows == {}


def test_confirmation_requires_reviewed_details_images_and_idempotency(client, png):
    valid_data = {
        "found_location": "Library",
        "analysis_json": analysis().model_dump_json(),
    }
    response = client.post(
        "/api/found-items/confirm-and-store",
        data=valid_data,
        files=image_files(png),
    )
    assert response.status_code == 422
    missing_analysis = client.post(
        "/api/found-items/confirm-and-store",
        data={"found_location": "Library"},
        files=image_files(png),
        headers={"X-Idempotency-Key": str(uuid4())},
    )
    assert missing_analysis.status_code == 422
    assert confirm(
        client, png, files=image_files(png, include_back=False)
    ).status_code == 422


def test_old_direct_store_route_is_removed(client, png):
    response = client.post(
        "/api/found-items/analyze-and-store",
        data={"found_location": "Library"},
        files=image_files(png),
        headers={"X-Idempotency-Key": str(uuid4())},
    )
    # FastAPI may report 405 because the dynamic GET /{item_id} path also matches
    # this text, but there is no POST handler capable of storing it.
    assert response.status_code in (404, 405)


def test_upload_media_type_and_size_statuses(client, png):
    unsupported = analyze(client, png, files=image_files(png, content_type="text/plain"))
    assert unsupported.status_code == 415
    too_large = b"x" * (10 * 1024 * 1024 + 1)
    oversized = analyze(
        client,
        png,
        files={
            "front_image": ("front.png", too_large, "image/png"),
            "back_image": ("back.png", png, "image/png"),
        },
    )
    assert oversized.status_code == 413


def test_confirmed_edits_server_time_private_paths_and_duplicate_key(
    client, dependencies, png
):
    database, ai = dependencies
    before = datetime.now(timezone.utc)
    key = str(uuid4())
    corrected = analysis().model_dump()
    corrected.update(
        {
            "object_name": "Corrected navy wallet",
            "colors": ["navy blue"],
            "short_description": "A navy wallet corrected by the finder.",
        }
    )
    response = confirm(client, png, key=key, analysis_payload=corrected)
    after = datetime.now(timezone.utc)
    assert response.status_code == 200, response.text
    payload = response.json()
    found_at = datetime.fromisoformat(payload["found_at"].replace("Z", "+00:00"))
    assert found_at.tzinfo is not None and before <= found_at <= after
    assert "front_image_path" not in json.dumps(payload)
    assert "/object/sign/sauli-item-images/" in payload["image_urls"]["front"]
    stored = database.rows[payload["id"]]
    assert stored["idempotency_key"] == key
    assert stored["object_name"] == "Corrected navy wallet"
    assert stored["analysis_json"]["colors"] == ["navy blue"]
    assert "corrected navy wallet" in stored["search_document"]
    assert "navy blue" in stored["search_document"]
    assert ai.found_calls == []
    assert not any(name in stored for name in ("user_id", "profile_id", "email", "phone"))
    assert confirm(client, png, key=key).status_code == 409


def test_confirmation_strictly_rejects_bad_or_unexpected_analysis(
    client, dependencies, png
):
    database, _ = dependencies
    wrong_type = analysis().model_dump()
    wrong_type["material"] = "leather"
    assert confirm(client, png, analysis_payload=wrong_type).status_code == 422

    extra = analysis().model_dump()
    extra["owner_name"] = "Must not be accepted"
    assert confirm(client, png, analysis_payload=extra).status_code == 422
    assert confirm(client, png, raw_analysis="not JSON").status_code == 422
    assert database.uploads == {}
    assert database.inserts == []


def test_confirmation_reapplies_sensitive_document_privacy(client, dependencies, png):
    database, _ = dependencies
    corrected = analysis().model_dump()
    corrected.update(
        {
            "generic_name": "student ID card",
            "object_name": "Student ID belonging to a named person",
            "category": "Documents",
            "visible_markings": ["Name and student number"],
            "short_description": "Contains private identifying data.",
        }
    )
    response = confirm(client, png, analysis_payload=corrected)
    assert response.status_code == 200
    stored = database.rows[response.json()["id"]]["analysis_json"]
    assert stored["object_name"] == "school ID"
    assert stored["document_kind"] == "school ID"
    assert stored["visible_markings"] == []
    assert stored["needs_review"] is True


def test_confirmed_id_shows_only_type_and_printed_owner_name(client, dependencies, png):
    database, _ = dependencies
    reviewed = analysis().model_dump()
    reviewed.update({
        "generic_name": "school ID",
        "object_name": "School ID number 123456789",
        "document_kind": "school ID",
        "document_owner_name": "Juan Dela Cruz",
        "visible_markings": ["Student number 123456789"],
        "extraction_summary": "Student number 123456789",
    })
    response = confirm(client, png, analysis_payload=reviewed)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["analysis"]["document_kind"] == "school ID"
    assert payload["analysis"]["document_owner_name"] == "Juan Dela Cruz"
    assert payload["analysis"]["extraction_summary"] == "school ID for Juan Dela Cruz."
    assert "123456789" not in response.text
    stored = database.rows[payload["id"]]
    assert "123456789" not in json.dumps(stored)


def test_confirmation_streams_only_upload_save_and_complete(client, png):
    response = confirm(client, png, accept="text/event-stream")
    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert [event["stage"] for event in events] == ["uploading", "saving", "complete"]


def test_failed_confirmation_cleans_uploaded_images(client, dependencies, png):
    database, _ = dependencies
    database.fail_insert = True
    response = confirm(client, png)
    assert response.status_code == 502
    assert len(database.cleaned) == 2
    assert database.uploads == {}


def test_developer_found_time_override_requires_zone_and_is_stored(client, png):
    invalid = confirm(client, png, found_at_override="2026-09-20T08:30")
    assert invalid.status_code == 422

    response = confirm(client, png, found_at_override="2026-09-20T16:30:00+08:00")
    assert response.status_code == 200
    assert datetime.fromisoformat(
        response.json()["found_at"].replace("Z", "+00:00")
    ) == datetime(2026, 9, 20, 8, 30, tzinfo=timezone.utc)


def test_health_has_separate_readiness_without_secrets(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "api": "ok",
        "database": "ok",
        "storage": "ok",
        "ollama": "ok",
    }
    assert "secret" not in response.text.casefold()


def test_temporal_boundaries_and_retrieved_items(client, dependencies):
    database, _ = dependencies
    database.rows[ITEM_ID] = item()
    before, _ = search(client, FOUND_AT - timedelta(minutes=1))
    assert before.status_code == 200 and len(before.json()["results"]) == 1
    equal, _ = search(client, FOUND_AT)
    assert equal.status_code == 200 and len(equal.json()["results"]) == 1
    after, _ = search(client, FOUND_AT + timedelta(minutes=1))
    assert after.status_code == 200 and after.json()["results"] == []
    database.rows[ITEM_ID]["status"] = "retrieved"
    database.rows[ITEM_ID]["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    retrieved, _ = search(client, FOUND_AT - timedelta(minutes=1))
    assert retrieved.status_code == 200 and retrieved.json()["results"] == []


def test_retrieval_is_atomic_session_bound_and_conflicts(client, dependencies):
    database, _ = dependencies
    database.rows[ITEM_ID] = item()
    response, session_id = search(client, FOUND_AT)
    assert response.status_code == 200
    search_id = response.json()["search_id"]

    mismatch = client.post(
        f"/api/retrievals/{ITEM_ID}/simulate",
        json={"search_request_id": search_id, "anonymous_session_id": str(uuid4())},
    )
    assert mismatch.status_code == 409
    assert database.rows[ITEM_ID]["status"] == "available"

    database.fail_retrieval_event = True
    failed = client.post(
        f"/api/retrievals/{ITEM_ID}/simulate",
        json={"search_request_id": search_id, "anonymous_session_id": session_id},
    )
    assert failed.status_code == 502
    assert database.rows[ITEM_ID]["status"] == "available"

    database.fail_retrieval_event = False
    completed = client.post(
        f"/api/retrievals/{ITEM_ID}/simulate",
        json={"search_request_id": search_id, "anonymous_session_id": session_id},
    )
    assert completed.status_code == 200
    assert completed.json()["retriever"] == "Anonymous retriever"
    assert database.rows[ITEM_ID]["status"] == "retrieved"
    duplicate = client.post(
        f"/api/retrievals/{ITEM_ID}/simulate",
        json={"search_request_id": search_id, "anonymous_session_id": session_id},
    )
    assert duplicate.status_code == 409


def test_no_endpoint_requires_supabase_auth_jwt(client, png):
    assert analyze(client, png).status_code == 200
    response = confirm(client, png)
    assert response.status_code == 200
