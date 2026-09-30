import asyncio
import json
import logging
from types import SimpleNamespace

import ollama
import pytest
from pydantic import ValidationError

from app.api.routes import _confirmed_analysis
from app.core.config import Settings
from app.core.errors import ServiceError
from app.models.schemas import (
    FoundItemAnalysis,
    FoundItemReviewReconciliation,
    QueryAnalysis,
    SearchInput,
)
from app.services.ai import AIService, canonical_matching_analysis, protect_document_analysis
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
    assert "Describe a wallet as a wallet whether it is closed" in message["content"]
    assert "Ordinary cards in a wallet are not" in message["content"]
    assert "Required JSON Schema:" not in message["content"]
    assert call["format"] == FoundItemAnalysis.model_json_schema()
    assert call["think"] is False


def test_found_item_prompt_scopes_id_name_rules_and_keeps_only_safe_document_details():
    client = ScriptedClient(
        [
            (
                json.dumps(
                    {
                        "generic_name": "driver's license",
                        "object_name": "driver's license",
                        "document_kind": "driver's license",
                        "document_owner_name": "Cruz, Maria Elena",
                        "extraction_summary": "Private card number 123456789",
                    }
                ),
                "",
            )
        ]
    )

    result = asyncio.run(
        AIService(Settings(), client=client).analyze_found_item(
            b"front", b"back", "image/jpeg", "image/jpeg"
        )
    )

    prompt = client.calls[0]["messages"][0]["content"]
    assert prompt.index("MANDATORY CONDITION INSPECTION") < prompt.index("Privacy rules:")
    assert "FIRST: CHECK FOR IDs" not in prompt
    assert '"LAST, FIRST MIDDLE"' in prompt
    assert "for ordinary items, retain every supported detail required above" in prompt
    assert result.document_owner_name == "Cruz Maria Elena"
    assert result.extraction_summary == "driver's license for Cruz Maria Elena."
    assert "123456789" not in result.model_dump_json()


def test_found_item_keeps_ordinary_item_details_after_document_rules():
    client = ScriptedClient(
        [
            (
                json.dumps(
                    {
                        "generic_name": "water bottle",
                        "object_name": "blue Acme water bottle",
                        "document_kind": "none",
                        "colors": ["blue"],
                        "material": ["coated metal"],
                        "brand": "Acme",
                        "condition": "fair",
                        "condition_details": ["dent on the left shoulder"],
                        "extraction_summary": "Blue Acme metal water bottle with a dent on its left shoulder.",
                    }
                ),
                "",
            )
        ]
    )

    result = asyncio.run(
        AIService(Settings(), client=client).analyze_found_item(
            b"front", b"back", "image/jpeg", "image/jpeg"
        )
    )

    assert result.brand == "Acme"
    assert result.colors == ["blue"]
    assert result.material == ["coated metal"]
    assert result.condition_details == ["dent on the left shoulder"]
    assert "dent on its left shoulder" in result.extraction_summary
    assert len(client.calls) == 1


def test_missing_id_name_uses_narrow_second_pass_without_exposing_other_text():
    client = ScriptedClient(
        [
            (
                json.dumps(
                    {
                        "generic_name": "driver's license",
                        "object_name": "driver's license",
                        "document_kind": "driver's license",
                        "document_owner_name": None,
                        "extraction_summary": "Private number 123456789",
                    }
                ),
                "",
            ),
            (json.dumps({"owner_name": "Cruz, Maria Elena"}), ""),
        ]
    )

    result = asyncio.run(
        AIService(Settings(), client=client).analyze_found_item(
            b"front", b"back", "image/jpeg", "image/jpeg"
        )
    )

    assert len(client.calls) == 2
    assert client.calls[1]["messages"][1]["images"] == [b"front", b"back"]
    assert "Read ONLY the printed" in client.calls[1]["messages"][1]["content"]
    assert result.document_owner_name == "Cruz Maria Elena"
    assert result.extraction_summary == "driver's license for Cruz Maria Elena."
    assert "123456789" not in result.model_dump_json()


def test_wallet_with_id_is_described_as_wallet_without_reading_card_owner():
    client = ScriptedClient(
        [
            (
                json.dumps(
                    {
                        "generic_name": "wallet",
                        "object_name": "black wallet with a school ID",
                        "document_kind": "school ID",
                        "document_owner_name": None,
                        "colors": ["black"],
                        "extraction_summary": "Student number 123456789",
                    }
                ),
                "",
            ),
            (json.dumps({
                "description": "Black folding wallet with a smooth outer surface, "
                "interior card slots, and a clear window."
            }), ""),
        ]
    )

    result = asyncio.run(
        AIService(Settings(), client=client).analyze_found_item(
            b"wallet-front", b"wallet-inside", "image/jpeg", "image/jpeg"
        )
    )

    assert result.generic_name == "wallet"
    assert result.document_kind == "school ID"
    assert result.document_owner_name is None
    assert result.extraction_summary == (
        "Black folding wallet with a smooth outer surface, interior card slots, "
        "and a clear window. It contains a school ID."
    )
    assert "123456789" not in result.model_dump_json()
    assert len(client.calls) == 2
    assert client.calls[1]["messages"][1]["images"] == [b"wallet-front", b"wallet-inside"]
    assert "Read ONLY the printed" not in client.calls[1]["messages"][1]["content"]
    assert protect_document_analysis(result).extraction_summary == result.extraction_summary
    assert _confirmed_analysis(result.model_dump_json()).extraction_summary == result.extraction_summary


def test_wallet_without_model_summary_uses_both_photos_for_visible_details():
    client = ScriptedClient([
        (json.dumps({
            "generic_name": "wallet",
            "object_name": "black long wallet",
            "document_kind": "none",
            "colors": ["black"],
            "short_description": "",
            "extraction_summary": "",
        }), ""),
        (json.dumps({
            "description": "Black long wallet with a plain outer panel that opens "
            "to card slots and several cards visible inside."
        }), ""),
    ])

    result = asyncio.run(
        AIService(Settings(), client=client).analyze_found_item(
            b"closed", b"open", "image/jpeg", "image/jpeg"
        )
    )

    assert result.extraction_summary == (
        "Black long wallet with a plain outer panel that opens to card slots "
        "and several cards visible inside."
    )
    assert result.document_kind == "none"
    assert len(client.calls) == 2
    assert client.calls[1]["messages"][1]["images"] == [b"closed", b"open"]


def test_wallet_title_only_summary_still_triggers_two_view_details():
    client = ScriptedClient([
        (json.dumps({
            "generic_name": "wallet",
            "object_name": "black leather wallet",
            "extraction_summary": "Black leather wallet.",
        }), ""),
        (json.dumps({
            "description": "Black leather wallet with a smooth closed exterior "
            "and an open interior showing card slots and several cards."
        }), ""),
    ])

    result = asyncio.run(
        AIService(Settings(), client=client).analyze_found_item(
            b"closed", b"open", "image/jpeg", "image/jpeg"
        )
    )

    assert result.extraction_summary == (
        "Black leather wallet with a smooth closed exterior and an open "
        "interior showing card slots and several cards."
    )
    assert len(client.calls) == 2


def test_wallet_with_useful_first_summary_does_not_need_another_model_call():
    client = ScriptedClient([
        (json.dumps({
            "generic_name": "wallet",
            "object_name": "black leather wallet",
            "extraction_summary": "Black leather wallet with visible card slots and cards inside.",
        }), ""),
    ])

    result = asyncio.run(
        AIService(Settings(), client=client).analyze_found_item(
            b"closed", b"open", "image/jpeg", "image/jpeg"
        )
    )

    assert "card slots and cards" in result.extraction_summary
    assert len(client.calls) == 1


def test_wallet_feature_check_failure_does_not_return_bare_fallback():
    client = ScriptedClient([
        (json.dumps({
            "generic_name": "wallet",
            "object_name": "black wallet",
            "extraction_summary": "",
        }), ""),
        ("not json", ""),
        ("not json", ""),
    ])

    with pytest.raises(ServiceError, match="required analysis format"):
        asyncio.run(
            AIService(Settings(), client=client).analyze_found_item(
                b"closed", b"open", "image/jpeg", "image/jpeg"
            )
        )


def test_wallet_description_retries_if_card_number_is_transcribed():
    client = ScriptedClient([
        (json.dumps({
            "generic_name": "wallet",
            "object_name": "black wallet",
            "extraction_summary": "",
        }), ""),
        (json.dumps({
            "description": "Black wallet with card slots and a card numbered 123456789 inside."
        }), ""),
        (json.dumps({
            "description": "Black wallet with a smooth exterior and an open interior "
            "showing several card slots and a clear sleeve."
        }), ""),
    ])

    result = asyncio.run(
        AIService(Settings(), client=client).analyze_found_item(
            b"closed", b"open", "image/jpeg", "image/jpeg"
        )
    )

    assert "card slots and a clear sleeve" in result.extraction_summary
    assert "123456789" not in result.model_dump_json()
    assert len(client.calls) == 3


def test_wallet_description_rejects_known_id_owner_name():
    client = ScriptedClient([
        (json.dumps({
            "generic_name": "wallet",
            "object_name": "black wallet with a school ID",
            "document_kind": "school ID",
            "document_owner_name": "Kyle Adrien",
        }), ""),
        (json.dumps({
            "description": "Black wallet with a clear card window and kyle adrien "
            "printed on the card inside."
        }), ""),
    ])

    with pytest.raises(ServiceError, match="private card text"):
        asyncio.run(
            AIService(Settings(), client=client).analyze_found_item(
                b"closed", b"open", "image/jpeg", "image/jpeg"
            )
        )


def test_invalid_id_name_second_pass_keeps_generic_document_summary():
    client = ScriptedClient(
        [
            (
                json.dumps(
                    {
                        "generic_name": "school ID",
                        "object_name": "school ID",
                        "document_kind": "school ID",
                        "document_owner_name": None,
                    }
                ),
                "",
            ),
            (json.dumps({"owner_name": "Juan 123456789"}), ""),
        ]
    )

    result = asyncio.run(
        AIService(Settings(), client=client).analyze_found_item(
            b"front", b"back", "image/jpeg", "image/jpeg"
        )
    )

    assert result.document_owner_name is None
    assert result.extraction_summary == "school ID."
    assert "123456789" not in result.model_dump_json()


def test_unavailable_optional_id_name_read_does_not_block_item_review(caplog):
    client = ScriptedClient(
        [
            (
                json.dumps(
                    {
                        "generic_name": "school ID",
                        "object_name": "school ID",
                        "document_kind": "school ID",
                    }
                ),
                "",
            ),
            ("not json", ""),
            ("not json", ""),
        ]
    )

    with caplog.at_level(logging.WARNING, logger="sauli.ai"):
        result = asyncio.run(
            AIService(Settings(), client=client).analyze_found_item(
                b"front", b"back", "image/jpeg", "image/jpeg"
            )
        )

    assert result.extraction_summary == "school ID."
    assert "not json" not in caplog.text


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
    assert "Required JSON Schema:" not in client.calls[0]["messages"][0]["content"]
    assert '"$defs"' not in client.calls[1]["messages"][0]["content"]


def test_found_item_fragment_repair_requests_complete_root_without_duplicate_schema():
    client = ScriptedClient(
        [
            (json.dumps({"component": "phone", "count": 1}), ""),
            (
                json.dumps(
                    {
                        "generic_name": "smartphone",
                        "object_name": "white smartphone",
                        "colors": ["white"],
                        "extraction_summary": "White smartphone with a dual rear camera.",
                    }
                ),
                "",
            ),
        ]
    )

    result = asyncio.run(
        AIService(Settings(), client=client).analyze_found_item(
            b"front", b"back", "image/jpeg", "image/jpeg"
        )
    )

    assert result.generic_name == "smartphone"
    assert len(client.calls) == 2
    repair = client.calls[1]["messages"][0]["content"]
    assert "Missing required fields: generic_name,object_name" in repair
    assert '"$defs"' not in repair
    assert client.calls[1]["format"] == FoundItemAnalysis.model_json_schema()


def test_ollama_repair_error_logs_status_without_model_response(caplog):
    class ErrorOnRepairClient:
        def __init__(self):
            self.calls = []

        def chat(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"component": "phone", "count": 1}),
                        thinking="",
                    )
                )
            raise ollama.ResponseError("PRIVATE-MODEL-BODY", status_code=502)

    client = ErrorOnRepairClient()
    with caplog.at_level(logging.WARNING, logger="sauli.ai"):
        with pytest.raises(ServiceError, match="Ollama server logs"):
            asyncio.run(
                AIService(Settings(), client=client).analyze_found_item(
                    b"front", b"back", "image/jpeg", "image/jpeg"
                )
            )

    assert "schema=FoundItemAnalysis attempt=2/2 status=502" in caplog.text
    assert "PRIVATE-MODEL-BODY" not in caplog.text


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
            extraction_summary=corrected,
        )
    )
    client = ScriptedClient([(response, "")])

    result = asyncio.run(
        AIService(Settings(), client=client).reconcile_found_item_review(
            current,
            "The shoe is yellow, not blue; heel damage cannot be confirmed.",
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
            extraction_summary=corrected,
        )
    )
    client = ScriptedClient([(response, "")])

    result = asyncio.run(
        AIService(Settings(), client=client).reconcile_found_item_review(
            current,
            "This is a yellow backpack, not a shoe. No brand, logo, or damage is visible.",
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


def test_review_brand_and_note_update_the_summary_and_matching_fields():
    current = reviewed_shoe_analysis()
    response = json.dumps(
        reconciliation_payload(
            current,
            object_name="Adidas yellow running shoe",
            colors=["yellow", "white"],
            brand="Adidas",
            visible_markings=["three stripes"],
            condition="good",
            condition_details=[],
            short_description="A yellow Adidas running shoe with an intact heel.",
            extraction_summary="Yellow Adidas running shoe with white sole and intact heel.",
        )
    )
    client = ScriptedClient([(response, "")])

    result = asyncio.run(
        AIService(Settings(), client=client).reconcile_found_item_review(
            current,
            "The shoe is yellow, has Adidas stripes, and has no heel tear.",
        )
    )

    assert result.brand == "Adidas"
    assert result.colors == ["yellow", "white"]
    assert result.condition_details == []
    assert result.extraction_summary.startswith("Yellow Adidas")
    assert result.surface_assessments == []
    prompt = client.calls[0]["messages"][1]["content"]
    assert '"correction_notes": "The shoe is yellow' in prompt
    assert "Nike" not in search_document(result)


def test_review_note_only_can_update_condition_and_summary():
    current = reviewed_shoe_analysis()
    response = json.dumps(
        reconciliation_payload(
            current,
            condition="good",
            condition_details=[],
            short_description="A blue Nike running shoe with an intact heel.",
            extraction_summary="Blue Nike running shoe with an intact heel and white sole.",
        )
    )
    client = ScriptedClient([(response, "")])

    result = asyncio.run(
        AIService(Settings(), client=client).reconcile_found_item_review(
            current,
            "The heel is intact; there is no tear.",
        )
    )

    assert result.condition == "good"
    assert result.condition_details == []
    assert result.surface_assessments == []
    assert "intact heel" in result.extraction_summary
    assert "tear" not in search_document(result).split()


def test_review_rejects_model_that_ignores_the_correction_note():
    current = reviewed_shoe_analysis()
    response = json.dumps(reconciliation_payload(current, brand="Nike"))
    client = ScriptedClient([(response, "")])

    with pytest.raises(ServiceError, match="did not apply"):
        asyncio.run(
            AIService(Settings(), client=client).reconcile_found_item_review(
                current,
                "The brand is Adidas, not Nike.",
            )
        )


def test_review_rejects_old_brand_left_in_searchable_summary():
    current = reviewed_shoe_analysis()
    response = json.dumps(
        reconciliation_payload(
            current,
            brand="Adidas",
            object_name="Adidas blue running shoe",
            short_description="A blue Adidas running shoe.",
            extraction_summary="Blue Adidas shoe with a Nike logo.",
        )
    )
    client = ScriptedClient([(response, "")])

    with pytest.raises(ServiceError, match="previous brand"):
        asyncio.run(
            AIService(Settings(), client=client).reconcile_found_item_review(
                current,
                "The brand is Adidas, not Nike.",
            )
        )


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
            brand=None,
            visible_markings=["person's name", "student number"],
            short_description="A student card containing private details.",
            extraction_summary=corrected,
        )
    )
    client = ScriptedClient([(response, "")])

    result = asyncio.run(
        AIService(Settings(), client=client).reconcile_found_item_review(
            current,
            "This is a student identification card, not a shoe.",
        )
    )

    assert result.object_name == "school ID"
    assert result.document_kind == "school ID"
    assert result.visible_markings == []
    assert "person's name" not in result.model_dump_json()
    assert "student number" not in result.model_dump_json()


def test_correction_can_change_primary_item_from_id_to_wallet():
    current = FoundItemAnalysis(
        generic_name="identification card",
        object_name="identification card for Maria Elena Cruz",
        document_kind="identification card",
        document_owner_name="Maria Elena Cruz",
        extraction_summary="identification card for Maria Elena Cruz.",
    )
    response = json.dumps(
        reconciliation_payload(
            current,
            generic_name="wallet",
            object_name="black wallet containing an identification card",
            category="Accessories",
            subcategory="wallet",
            colors=["black"],
            extraction_summary="Black wallet with an identification card for Maria Elena Cruz.",
        )
    )
    client = ScriptedClient([(response, "")])

    result = asyncio.run(
        AIService(Settings(), client=client).reconcile_found_item_review(
            current, "The found item is a black wallet with an ID inside, not a loose ID."
        )
    )

    assert result.generic_name == "wallet"
    assert result.document_kind == "identification card"
    assert result.extraction_summary == (
        "Black wallet containing an identification card."
    )
    assert result.document_owner_name is None
