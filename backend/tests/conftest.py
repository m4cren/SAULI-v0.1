import threading
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
from app.core.errors import ServiceError
from app.main import create_app
from app.models.schemas import FoundItemAnalysis, MatchAssessment, QueryAnalysis
from app.services.supabase import SupabaseService

ITEM_ID = "00000000-0000-4000-8000-000000000001"
FOUND_AT = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def analysis():
    return FoundItemAnalysis(
        generic_name="wallet", object_name="Black leather wallet", colors=["black"],
        material=["leather"], category="Personal belongings", condition="good",
        short_description="A black wallet.", extraction_summary="Black wallet with a fold.",
        distinctive_features=["fold"],
    )


def item(item_id=ITEM_ID, **overrides):
    return {
        "id": item_id, "item_code": "SL-2026-000001", "status": "available",
        "found_at": FOUND_AT.isoformat(), "found_location": "LSPU Library",
        "analysis_json": analysis().model_dump(),
        "object_name": "Black leather wallet",
        "front_image_path": f"found-items/{item_id}/front.png",
        "back_image_path": f"found-items/{item_id}/back.png",
        **overrides,
    }


class FakeAI:
    def __init__(self):
        self.compared = []
        self.found_calls = []
        self.review_calls = []

    async def health(self):
        return "ok"

    async def analyze_found_item(self, front, back, front_type, back_type):
        self.found_calls.append((front, back, front_type, back_type))
        return analysis()

    async def reconcile_found_item_review(
        self, current, previous_summary, corrected_summary
    ):
        self.review_calls.append((current, previous_summary, corrected_summary))
        return current.model_copy(update={"extraction_summary": corrected_summary})

    async def extract_query(self, search, image):
        return QueryAnalysis(generic_name="wallet", colors=["black"])

    async def compare(self, query, candidate, images):
        self.compared.append((candidate["id"], images))
        return MatchAssessment(candidate_id=candidate["id"], ai_similarity=0.9, matched_features=["black wallet"], explanation="Same visible type and color.", needs_review=False)


class FakeDatabase:
    """Only tests use this in-memory dependency; the application never substitutes it."""

    def __init__(self):
        self.rows = {}
        self.uploads = {}
        self.cleaned = []
        self.inserts = []
        self.matches = []
        self.fail_insert = False
        self.retrievals = []
        self.searches = {}
        self.fail_retrieval_event = False
        self.lock = threading.Lock()

    async def health(self):
        return "ok"

    async def database_health(self):
        return "ok"

    async def storage_health(self):
        return "ok"

    async def upload(self, path, data, content_type):
        self.uploads[path] = data

    async def cleanup(self, paths):
        self.cleaned.extend(paths)
        for path in paths:
            self.uploads.pop(path, None)

    async def download(self, path):
        return self.uploads.get(path, path.encode())

    async def insert(self, table, record):
        if self.fail_insert:
            raise ServiceError("Database insert failed.")
        self.inserts.append((table, record))
        for existing_table, existing in self.inserts[:-1]:
            if (
                existing_table == table
                and record.get("idempotency_key")
                and existing.get("idempotency_key") == record["idempotency_key"]
            ):
                raise ServiceError("This operation conflicts with an existing record.", 409)
        if table == "found_items":
            record = {**record, "item_code": "SL-2026-000001"}
            self.rows[record["id"]] = record
        elif table == "search_requests":
            self.searches[record["id"]] = dict(record)
        return record

    async def update(self, table, record_id, values):
        if table == "search_requests":
            self.searches[record_id].update(values)

    async def signed_url(self, path):
        return "https://test.invalid/storage/v1/object/sign/sauli-item-images/" + path + "?token=test-only"

    async def public_item(self, row):
        return await SupabaseService.public_item(self, row)

    async def eligible_items(self, last_seen_at):
        # Deliberately return ineligible rows too, to test the independent hard rule.
        for row in self.rows.values():
            yield dict(row)

    async def get_item(self, item_id):
        if item_id not in self.rows:
            raise ServiceError("This item was not found.", 404)
        return self.rows[item_id]

    async def save_matches(self, records):
        self.matches.extend(records)

    async def simulate_retrieval(self, item_id, search_request_id, anonymous_session_id):
        with self.lock:
            row = self.rows.get(item_id)
            if row is None:
                raise ServiceError("This item was not found.", 404)
            if row["status"] != "available":
                raise ServiceError("This item has already been retrieved.", 409)
            request = self.searches.get(search_request_id)
            match = next(
                (
                    value
                    for value in self.matches
                    if value["search_request_id"] == search_request_id
                    and value["found_item_id"] == item_id
                    and value.get("eligible", True)
                ),
                None,
            )
            if not request or not match or request["anonymous_session_id"] != anonymous_session_id:
                raise ServiceError(
                    "This retrieval is not valid for the current anonymous search session.", 409
                )
            if self.fail_retrieval_event:
                raise ServiceError("Retrieval event could not be saved.", 502)
            row["status"] = "retrieved"
            event = {
                "id": str(uuid4()), "item_id": item_id,
                "item_name": row["analysis_json"]["object_name"],
                "item_code": row["item_code"], "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "compartment": "C3", "retriever": "Anonymous retriever", "simulated": True,
            }
            self.retrievals.append(event)
            return event


@pytest.fixture
def png():
    output = BytesIO()
    Image.new("RGB", (3, 3), "teal").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def dependencies():
    return FakeDatabase(), FakeAI()


@pytest.fixture
def client(dependencies):
    database, ai = dependencies
    with TestClient(create_app(Settings(), database=database, ai=ai), raise_server_exceptions=False) as session:
        yield session
