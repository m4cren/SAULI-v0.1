import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ServiceError
from app.models.schemas import (
    FoundItemAnalysis,
    FoundItemReviewReconciliation,
    QueryAnalysis,
    SearchInput,
)
from app.services.ai import AIService, canonical_matching_analysis
from app.services.workflows import search_document
from conftest import FOUND_AT, ITEM_ID


class ScriptedClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        content, thinking = next(self.responses)
        return SimpleNamespace(message=SimpleNamespace(content=content, thinking=thinking))


def query_input():
    return SearchInput(
        description="black wallet",
        last_seen_location="Library",
        last_seen_at=FOUND_AT,
        anonymous_session_id="00000000-0000-4000-8000-000000000010",
        idempotency_key="00000000-0000-4000-8000-000000000020",
    )


def test_invalid_json_gets_exactly_one_repair():
    client = ScriptedClient([("not json", ""), ('{"generic_name":"wallet"}', "")])
    result = asyncio.run(AIService(Settings(), client=client).extract_query(query_input(), None))
    assert result.generic_name == "wallet"
    assert len(client.calls) == 2
    assert "previous answer was not valid" in client.calls[1]["messages"][1]["content"]


def test_invalid_repair_returns_safe_error_without_raw_reasoning():
    client = ScriptedClient([("", "private reasoning"), ("", "private reasoning")])
    with pytest.raises(ServiceError, match="one repair") as error:
        asyncio.run(AIService(Settings(), client=client).extract_query(query_input(), None))
    assert len(client.calls) == 2
    assert "private reasoning" not in str(error.value)
    assert "private reasoning" not in client.calls[1]["messages"][1]["content"]


def test_validation_debug_log_is_useful_without_model_values(caplog):
    private_value = "PRIVATE-VALUE-MUST-NOT-BE-LOGGED"
    content = json.dumps({"generic_name": "wallet", private_value: private_value})
    client = ScriptedClient([(content, ""), (content, "")])
    with caplog.at_level(logging.WARNING, logger="sauli.ai"):
        with pytest.raises(ServiceError):
            asyncio.run(AIService(Settings(), client=client).extract_query(query_input(), None))
    log = caplog.text
    assert "schema=QueryAnalysis" in log
    assert "attempt=1/2" in log
    assert "attempt=2/2" in log
    assert "unexpected_fields=1" in log
    assert "extra_forbidden" in log
    assert private_value not in log


def test_only_validated_json_is_used_from_unexpected_thinking_field():
    client = ScriptedClient([("", 'internal private text {"generic_name":"wallet"} extra private text')])
    result = asyncio.run(AIService(Settings(), client=client).extract_query(query_input(), None))
    assert "private text" not in result.model_dump_json()
    assert result.generic_name == "wallet"


def test_candidate_id_cannot_be_changed_by_ai():
    content = json.dumps({"candidate_id": "00000000-0000-4000-8000-000000000099", "ai_similarity": 0.8})
    client = ScriptedClient([(content, ""), (content, "")])
    with pytest.raises(ServiceError):
        asyncio.run(AIService(Settings(), client=client).compare(QueryAnalysis(generic_name="wallet"), {"id": ITEM_ID, "analysis": {}}, []))
    assert len(client.calls) == 2


def test_query_and_candidate_image_order_is_explicit():
    content = json.dumps({"candidate_id": ITEM_ID, "ai_similarity": 0.8})
    client = ScriptedClient([(content, "")])
    images = [b"query", b"front", b"back"]
    asyncio.run(AIService(Settings(), client=client).compare(QueryAnalysis(generic_name="wallet"), {"id": ITEM_ID, "analysis": {}}, images))
    message = client.calls[0]["messages"][1]
    assert message["images"] == images
    assert message["content"].count("[img]") == 3
    assert client.calls[0]["think"] is False


def test_found_item_normalizes_common_vlm_text_shapes():
    result = FoundItemAnalysis.model_validate(
        {
            "generic_name": "bottle",
            "object_name": "blue water bottle",
            "views_consistent": True,
            "counting_notes": "One bottle is visible.",
            "material": "coated metal",
            "condition_details": [
                {
                    "component": "body",
                    "detail": ["minor surface marks", "small scuff"],
                    "severity": None,
                },
                {"component": "lid", "detail": "appears intact"},
            ],
            "likely_use": ["carrying water", "sports or school use"],
            "short_description": ["Blue bottle", "with a loop lid"],
            "extraction_summary": {
                "identification": "water bottle",
                "condition": "used",
            },
            "received_view_count": 2,
            "view_observations": [
                {"image_index": 1, "notes": "Front view is clear."},
                {"image_index": 2, "notes": "Back view is clear."},
            ],
        }
    )

    assert result.counting_notes == ["One bottle is visible."]
    assert result.material == ["coated metal"]
    assert result.condition_details == [
        "component: body; detail: minor surface marks, small scuff",
        "component: lid; detail: appears intact",
    ]
    assert result.likely_use == "carrying water; sports or school use"
    assert result.short_description == "Blue bottle; with a loop lid"
    assert result.extraction_summary == (
        "identification: water bottle; condition: used"
    )
    assert result.view_observations[0].notes == ["Front view is clear."]
    assert result.view_observations[1].notes == ["Back view is clear."]


def test_found_item_normalization_keeps_unsupported_types_strict():
    for field in ("likely_use", "material", "short_description"):
        with pytest.raises(ValidationError):
            payload = {
                "generic_name": "bottle",
                "object_name": "blue water bottle",
                field: True,
            }
            FoundItemAnalysis.model_validate(payload)

    with pytest.raises(ValidationError):
        FoundItemAnalysis.model_validate(
            {
                "generic_name": "bottle",
                "object_name": "blue water bottle",
                "condition_details": [{"detail": {"nested": "not allowed"}}],
            }
        )


def test_found_item_common_text_shapes_do_not_trigger_repair():
    content = json.dumps(
        {
            "generic_name": "bottle",
            "object_name": "blue water bottle",
            "counting_notes": "One bottle is visible.",
            "material": "metal",
            "condition_details": [
                {"component": "body", "detail": "minor scuffs"}
            ],
            "likely_use": ["carrying water", "school use"],
            "short_description": ["Blue bottle", "loop lid"],
            "extraction_summary": {
                "identification": "blue bottle",
                "condition": "minor scuffs",
            },
            "view_observations": [
                {"image_index": 1, "notes": "Front view."},
                {"image_index": 2, "notes": "Back view."},
            ],
            "received_view_count": 2,
            "views_consistent": True,
        }
    )
    client = ScriptedClient([(content, "")])

    result = asyncio.run(
        AIService(Settings(), client=client).analyze_found_item(
            b"front", b"back", "image/jpeg", "image/jpeg"
        )
    )

    assert result.likely_use == "carrying water; school use"
    assert result.material == ["metal"]
    assert result.condition_details == [
        "component: body; detail: minor scuffs"
    ]
    assert result.short_description == "Blue bottle; loop lid"
    assert result.extraction_summary == (
        "identification: blue bottle; condition: minor scuffs"
    )
    assert len(client.calls) == 1
    call = client.calls[0]
    message = call["messages"][0]
    assert message["images"] == [b"front", b"back"]
    assert message["content"].count("[img]") == 2
    assert "IMAGE 1 - FRONT VIEW" in message["content"]
    assert "IMAGE 2 - BACK VIEW" in message["content"]
    assert call["format"] == FoundItemAnalysis.model_json_schema()
    assert call["think"] is False


def test_found_item_repair_keeps_schema_constrained_format():
    invalid = json.dumps(
        {
            "generic_name": "bottle",
            "object_name": "blue water bottle",
            "material": True,
        }
    )
    valid = json.dumps(
        {
            "generic_name": "bottle",
            "object_name": "blue water bottle",
            "material": ["metal"],
        }
    )
    client = ScriptedClient([(invalid, ""), (valid, "")])

    result = asyncio.run(
        AIService(Settings(), client=client).analyze_found_item(
            b"front", b"back", "image/jpeg", "image/jpeg"
        )
    )

    expected_schema = FoundItemAnalysis.model_json_schema()
    assert result.material == ["metal"]
    assert len(client.calls) == 2
    assert all(call["format"] == expected_schema for call in client.calls)
    assert "material" in client.calls[1]["messages"][0]["content"]


def reviewed_shoe_analysis():
    return FoundItemAnalysis(
        generic_name="shoe",
        object_name="Nike blue running shoe",
        views_consistent=True,
        alternative_names=["running sneaker"],
        component_counts=[
            {"component": "shoelace", "count": 2, "count_is_estimate": False}
        ],
        count_confidence="high",
        counting_notes=["One shoe was detected."],
        category="Footwear",
        subcategory="Running shoe",
        colors=["blue", "white"],
        material=["mesh", "rubber"],
        brand="Nike",
        visible_markings=["white swoosh"],
        functional_components=["laces", "rubber sole"],
        condition="fair",
        condition_visibility="Both sides visible",
        condition_confidence="high",
        surface_assessments=[
            {
                "component": "heel",
                "status": "visible_damage",
                "damage_types": ["small tear"],
                "location": "rear heel",
                "severity": "minor",
                "certainty": "confirmed",
                "evidence": "Visible in image 2",
            }
        ],
        condition_details=["Small tear on rear heel"],
        patterns=["solid color"],
        distinctive_features=["white sole"],
        likely_use="running",
        short_description="A blue Nike running shoe with a small heel tear.",
        confidence="high",
        needs_review=False,
        uncertainty_notes=["Model variant is not visible."],
        extraction_summary="Nike blue shoe with a damaged heel.",
        received_view_count=2,
        view_observations=[
            {
                "image_index": 1,
                "visible_region": "stale-blue-provenance front and side",
                "notes": ["Automated blue observation."],
            },
            {
                "image_index": 2,
                "visible_region": "back and sole",
                "damage_observations": ["Small heel tear."],
            },
        ],
    )


def reconciliation_payload(current, **updates):
    current_values = current.model_dump(mode="json")
    payload = {
        field: current_values[field]
        for field in FoundItemReviewReconciliation.model_fields
    }
    payload.update(updates)
    return payload


def test_review_summary_color_change_propagates_without_losing_unrelated_fields():
    current = reviewed_shoe_analysis()
    corrected = "Nike yellow shoe."
    response = json.dumps(
        reconciliation_payload(
            current,
            object_name="Nike yellow running shoe",
            colors=["yellow", "white"],
            condition="unknown",
            condition_details=[],
            short_description="A yellow Nike running shoe.",
        )
    )
    client = ScriptedClient([(response, "")])

    result = asyncio.run(
        AIService(Settings(), client=client).reconcile_found_item_review(
            current,
            current.extraction_summary,
            corrected,
        )
    )

    assert result.extraction_summary == corrected
    assert result.object_name == "Nike yellow running shoe"
    assert result.colors == ["yellow", "white"]
    assert result.brand == "Nike"
    assert result.material == ["mesh", "rubber"]
    assert result.condition == "unknown"
    assert result.condition_details == []
    assert result.component_counts == current.component_counts
    assert result.surface_assessments == []
    assert result.condition_visibility == "not_assessable"
    assert result.condition_confidence == "low"
    assert "blue" not in search_document(result).split()
    assert "tear" not in search_document(result).split()
    assert "yellow" in search_document(result).split()
    rerank_text = json.dumps(canonical_matching_analysis(result)).casefold()
    assert "blue" not in rerank_text
    assert "tear" not in rerank_text
    assert "yellow" in rerank_text
    assert client.calls[0]["format"]["additionalProperties"] is False
    assert set(client.calls[0]["format"]["required"]) == set(
        FoundItemReviewReconciliation.model_fields
    )
    assert client.calls[0]["messages"][1]["images"] == []


def test_review_summary_explicit_removals_clear_stale_semantic_and_surface_data():
    current = reviewed_shoe_analysis()
    corrected = "Yellow backpack with no visible brand, logo, or damage."
    response = json.dumps(
        reconciliation_payload(
            current,
            generic_name="backpack",
            object_name="Yellow backpack",
            alternative_names=[],
            category="Bags",
            subcategory="Backpack",
            colors=["yellow"],
            material=[],
            brand=None,
            model_or_variant=None,
            visible_markings=[],
            functional_components=[],
            condition="good",
            condition_details=[],
            patterns=[],
            distinctive_features=[],
            likely_use="",
            short_description="A yellow backpack with no visible damage.",
            uncertainty_notes=[],
        )
    )
    client = ScriptedClient([(response, "")])

    result = asyncio.run(
        AIService(Settings(), client=client).reconcile_found_item_review(
            current,
            current.extraction_summary,
            corrected,
        )
    )

    assert result.extraction_summary == corrected
    assert result.generic_name == "backpack"
    assert result.object_name == "Yellow backpack"
    assert result.colors == ["yellow"]
    assert result.brand is None
    assert result.visible_markings == []
    assert result.functional_components == []
    assert result.condition == "good"
    assert result.condition_details == []
    assert result.component_counts == []
    assert result.counting_notes == []
    assert result.surface_assessments == []
    # Nonsemantic view identity remains, while stale image-derived prose is removed.
    assert result.received_view_count == current.received_view_count
    assert [view.image_index for view in result.view_observations] == [1, 2]
    assert all(not view.visible_region for view in result.view_observations)
    assert all(not view.notes for view in result.view_observations)
    assert all(not view.damage_observations for view in result.view_observations)
    stored_search_text = search_document(result)
    for stale in ("blue", "nike", "swoosh", "shoe", "tear"):
        assert stale not in stored_search_text.split()


def test_candidate_reranking_excludes_image_provenance_and_surface_assessments():
    current = reviewed_shoe_analysis()
    canonical = canonical_matching_analysis(current)
    assert "view_observations" not in canonical
    assert "surface_assessments" not in canonical
    assert "counting_notes" not in canonical

    response = json.dumps({"candidate_id": ITEM_ID, "ai_similarity": 0.8})
    client = ScriptedClient([(response, "")])
    asyncio.run(
        AIService(Settings(), client=client).compare(
            QueryAnalysis(generic_name="shoe"),
            {"id": ITEM_ID, "analysis_json": current.model_dump()},
            [],
        )
    )

    prompt = client.calls[0]["messages"][1]["content"]
    assert "stale-blue-provenance" not in prompt
    assert "Visible in image 2" not in prompt


def test_review_reconciliation_reapplies_document_privacy():
    current = reviewed_shoe_analysis()
    corrected = "Student identification card with a person's name and number."
    response = json.dumps(
        reconciliation_payload(
            current,
            generic_name="identification card",
            object_name="Student identification card belonging to a named person",
            category="Documents",
            subcategory="Identification card",
            visible_markings=["person's name", "student number"],
            short_description="A student card containing private details.",
        )
    )
    client = ScriptedClient([(response, "")])

    result = asyncio.run(
        AIService(Settings(), client=client).reconcile_found_item_review(
            current,
            current.extraction_summary,
            corrected,
        )
    )

    assert result.object_name == "identification card"
    assert result.visible_markings == []
    assert "person's name" not in result.model_dump_json()
    assert "student number" not in result.model_dump_json()
