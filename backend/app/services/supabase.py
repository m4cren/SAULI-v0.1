"""Privileged Supabase access stays behind FastAPI; paths never leave this module."""

import asyncio
from urllib.parse import quote, urlsplit

import httpx

from app.core.config import Settings
from app.core.errors import ServiceError
from app.models.schemas import FoundItem, ImageURLs


class SupabaseService:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.base_url = settings.supabase_url.rstrip("/")
        self.bucket = settings.supabase_storage_bucket
        self.client = client or httpx.AsyncClient(timeout=30.0)

    @property
    def headers(self) -> dict[str, str]:
        if not self.base_url or not self.settings.supabase_secret_key:
            raise ServiceError(
                "Supabase is not configured. Set newly rotated SUPABASE_URL and "
                "SUPABASE_SECRET_KEY in backend/.env."
            )
        key = self.settings.supabase_secret_key
        headers = {"apikey": key}
        # Current sb_secret_ keys are API keys, not JWT bearer tokens.
        if key.startswith("eyJ") and key.count(".") == 2:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def close(self):
        await self.client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {**self.headers, **kwargs.pop("headers", {})}
        try:
            response = await self.client.request(
                method, self.base_url + path, headers=headers, **kwargs
            )
        except httpx.HTTPError:
            raise ServiceError(
                "Could not reach Supabase. Check its URL, network connection, and project status."
            ) from None
        if response.is_error:
            try:
                detail = response.json()
                code = detail.get("code")
                message = str(detail.get("message", ""))
            except (ValueError, AttributeError):
                code, message = None, ""
            if code in ("23505", "PT409") or "already been retrieved" in message:
                raise ServiceError("This operation conflicts with an existing record.", 409)
            if code == "PT404" or "does not exist" in message:
                raise ServiceError("This item was not found.", 404)
            if "No eligible match exists" in message:
                raise ServiceError(
                    "This retrieval is not valid for the current anonymous search session.", 409
                )
            if response.status_code in (401, 403):
                raise ServiceError(
                    "Supabase refused backend access. Check the rotated secret key and database permissions."
                )
            raise ServiceError(
                "Supabase could not complete the operation. Check that the anonymous reset "
                "migration and private Storage bucket are configured."
            )
        return response

    @staticmethod
    def _json(response: httpx.Response):
        try:
            return response.json()
        except ValueError:
            raise ServiceError("Supabase returned an invalid response.") from None

    async def database_health(self) -> str:
        if not self.base_url or not self.settings.supabase_secret_key:
            return "not_configured"
        try:
            await self._request(
                "GET",
                "/rest/v1/found_items",
                params={"select": "id", "limit": 1},
                timeout=4.0,
            )
            return "ok"
        except ServiceError:
            return "unavailable"

    async def storage_health(self) -> str:
        if not self.base_url or not self.settings.supabase_secret_key:
            return "not_configured"
        try:
            await self._request(
                "GET", f"/storage/v1/bucket/{quote(self.bucket, safe='')}", timeout=4.0
            )
            return "ok"
        except ServiceError:
            return "unavailable"

    async def health(self) -> str:
        """Compatibility helper used by test doubles."""
        return await self.database_health()

    async def upload(self, path: str, data: bytes, content_type: str):
        await self._request(
            "POST",
            f"/storage/v1/object/{quote(self.bucket, safe='')}/{quote(path, safe='/')}",
            content=data,
            headers={"Content-Type": content_type, "x-upsert": "false"},
        )

    async def cleanup(self, paths: list[str]):
        """Best effort compensation; cleanup failure never hides the original error."""
        if paths:
            try:
                await self._request(
                    "DELETE",
                    f"/storage/v1/object/{quote(self.bucket, safe='')}",
                    json={"prefixes": paths},
                )
            except ServiceError:
                pass

    async def download(self, path: str) -> bytes:
        response = await self._request(
            "GET",
            f"/storage/v1/object/authenticated/{quote(self.bucket, safe='')}/{quote(path, safe='/')}",
        )
        return response.content

    async def signed_url(self, path: str) -> str:
        response = await self._request(
            "POST",
            f"/storage/v1/object/sign/{quote(self.bucket, safe='')}/{quote(path, safe='/')}",
            json={"expiresIn": self.settings.signed_url_ttl_seconds},
        )
        data = self._json(response)
        signed = (data.get("signedURL") or data.get("signedUrl")) if isinstance(data, dict) else None
        if not isinstance(signed, str) or "/object/sign/" not in signed:
            raise ServiceError("Supabase did not return a private signed image URL.")
        if signed.startswith("/object/sign/"):
            return self.base_url + "/storage/v1" + signed
        if signed.startswith("/storage/v1/object/sign/"):
            return self.base_url + signed
        if (
            urlsplit(signed).netloc == urlsplit(self.base_url).netloc
            and signed.startswith(self.base_url + "/storage/v1/object/sign/")
        ):
            return signed
        raise ServiceError("Supabase returned an unexpected image URL.")

    async def insert(self, table: str, record: dict) -> dict:
        response = await self._request(
            "POST",
            f"/rest/v1/{table}",
            json=record,
            headers={"Prefer": "return=representation"},
        )
        records = self._json(response)
        if not isinstance(records, list) or not records:
            raise ServiceError("Supabase did not confirm that the record was saved.")
        return records[0]

    async def update(self, table: str, record_id: str, values: dict):
        await self._request(
            "PATCH",
            f"/rest/v1/{table}",
            params={"id": f"eq.{record_id}"},
            json=values,
            headers={"Prefer": "return=minimal"},
        )

    async def save_matches(self, records: list[dict]):
        if records:
            await self._request(
                "POST",
                "/rest/v1/match_results",
                json=records,
                headers={"Prefer": "return=minimal"},
            )

    async def get_item(self, item_id: str) -> dict:
        response = await self._request(
            "GET",
            "/rest/v1/found_items",
            params={"id": f"eq.{item_id}", "select": "*", "limit": 1},
        )
        rows = self._json(response)
        if not isinstance(rows, list):
            raise ServiceError("Supabase returned an invalid item record.")
        if not rows:
            raise ServiceError("This item was not found.", 404)
        return rows[0]

    async def eligible_items(self, last_seen_at):
        response = await self._request(
            "POST",
            "/rest/v1/rpc/get_eligible_found_items",
            json={"p_last_seen_at": last_seen_at.isoformat(), "p_limit": 100},
        )
        rows = self._json(response)
        if not isinstance(rows, list):
            raise ServiceError("Supabase returned an invalid candidate list.")
        for row in rows:
            yield row

    async def public_item(self, row: dict) -> FoundItem:
        # Explicit allowlist: object paths and backend-only columns cannot escape.
        front, back = await asyncio.gather(
            self.signed_url(row["front_image_path"]),
            self.signed_url(row["back_image_path"]),
        )
        return FoundItem(
            id=row["id"],
            item_code=row["item_code"],
            status=row["status"],
            found_location=row["found_location"],
            found_at=row["found_at"],
            analysis=row["analysis_json"],
            image_urls=ImageURLs(front=front, back=back),
        )

    async def simulate_retrieval(
        self, item_id: str, search_request_id: str, anonymous_session_id: str
    ) -> dict:
        item = await self.get_item(item_id)
        response = await self._request(
            "POST",
            "/rest/v1/rpc/complete_simulated_retrieval",
            json={
                "p_found_item_id": item_id,
                "p_search_request_id": search_request_id,
                "p_anonymous_session_id": anonymous_session_id,
            },
        )
        value = self._json(response)
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
        if not isinstance(value, dict) or not value.get("retrieval_event_id"):
            raise ServiceError("Supabase did not confirm the simulated retrieval.")
        return {
            "id": value["retrieval_event_id"],
            "item_id": item_id,
            "item_code": item["item_code"],
            "item_name": item.get("object_name") or "Lost item",
            "retrieved_at": value["retrieved_at"],
            "compartment": item.get("prototype_compartment", "C3"),
            "retriever": "Anonymous retriever",
            "simulated": True,
        }
