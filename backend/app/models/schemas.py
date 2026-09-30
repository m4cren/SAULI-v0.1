"""Only these validated fields cross the AI/API boundary."""

import math
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1500)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=250)]
Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=250)
]
TextList = Annotated[list[Text], Field(max_length=60)]
Confidence = Literal["high", "medium", "low"]
DocumentKind = Literal[
    "none", "school ID", "driver's license", "government ID", "passport",
    "bank card", "identification card", "sensitive document",
]


def _is_exact_type_validation(info: ValidationInfo) -> bool:
    """Human-confirmed JSON must already have the declared field types."""
    return bool(info.context and info.context.get("exact_types"))


def _text_as_string(value):
    """Normalize only shallow, text-preserving shapes into one string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "; ".join(item.strip() for item in value if item.strip())
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        parts = []
        for key, detail in value.items():
            if detail is None:
                continue
            if isinstance(detail, str):
                text = detail.strip()
            elif isinstance(detail, list) and all(
                isinstance(item, str) for item in detail
            ):
                text = ", ".join(item.strip() for item in detail if item.strip())
            else:
                return value
            if text:
                parts.append(f"{key.replace('_', ' ')}: {text}")
        return "; ".join(parts)
    return value


def _text_as_list(value):
    """Normalize strings and shallow text objects into a flat string list."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    if not isinstance(items, list):
        return value
    normalized = []
    for item in items:
        if isinstance(item, str):
            text = item.strip()
            if text:
                normalized.append(text)
        elif isinstance(item, dict):
            text = _text_as_string(item)
            if not isinstance(text, str):
                return value
            if text:
                normalized.append(text)
        else:
            return value
    return normalized


class AIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ComponentCount(AIModel):
    component: Name
    count: int = Field(default=0, ge=0, le=1000)
    count_is_estimate: bool = True


class SurfaceAssessment(AIModel):
    component: Name
    status: Literal["visible_damage", "no_visible_damage", "not_assessable"] = (
        "not_assessable"
    )
    damage_types: TextList = Field(default_factory=list)
    location: Text = ""
    severity: Literal["minor", "moderate", "severe"] | None = None
    certainty: Literal["confirmed", "probable", "uncertain"] = "uncertain"
    evidence: Text = ""

    @field_validator("damage_types", mode="before")
    @classmethod
    def normalize_damage_types(cls, value, info: ValidationInfo):
        if _is_exact_type_validation(info):
            return value
        return _text_as_list(value)


class DamageAuditFinding(AIModel):
    """One pixel-supported defect from the focused condition pass."""

    damage_types: Annotated[list[Name], Field(min_length=1, max_length=8)]
    location: Name
    image_indices: Annotated[list[Literal[1, 2]], Field(min_length=1, max_length=2)]
    severity: Literal["minor", "moderate", "severe"] | None
    certainty: Literal["confirmed", "probable", "uncertain"]
    geometry_cues: Annotated[list[Name], Field(max_length=8)]
    evidence: Name

    @model_validator(mode="after")
    def unique_image_indices(self):
        if len(set(self.image_indices)) != len(self.image_indices):
            raise ValueError("image_indices must not contain duplicates")
        if self.certainty == "confirmed" and set(self.image_indices) != {1, 2}:
            raise ValueError(
                "confirmed damage must be independently supported by both images"
            )
        geometry_damage = {
            "bend",
            "bending",
            "bent",
            "compressed",
            "deformation",
            "deformed",
            "dent",
            "dented",
            "flattened",
            "warp",
            "warped",
        }
        if (
            any(
                word in damage_type.casefold()
                for damage_type in self.damage_types
                for word in geometry_damage
            )
            and not self.geometry_cues
        ):
            raise ValueError(
                "dent and deformation findings require a visible geometry cue"
            )
        return self


class DamageAuditClearRegion(AIModel):
    """A specifically inspected region with positive no-damage evidence."""

    region: Name
    image_indices: Annotated[list[Literal[1, 2]], Field(min_length=1, max_length=2)]
    evidence: Name

    @model_validator(mode="after")
    def unique_image_indices(self):
        if len(set(self.image_indices)) != len(self.image_indices):
            raise ValueError("image_indices must not contain duplicates")
        return self


class DamageAuditUnassessableRegion(AIModel):
    """A region that cannot support either a damage or no-damage claim."""

    region: Name
    image_indices: Annotated[list[Literal[1, 2]], Field(min_length=1, max_length=2)]
    reason: Name

    @model_validator(mode="after")
    def unique_image_indices(self):
        if len(set(self.image_indices)) != len(self.image_indices):
            raise ValueError("image_indices must not contain duplicates")
        return self


class FoundItemDamageAudit(AIModel):
    """Compact second-pass condition evidence; it never identifies the item."""

    assessed_image_indices: Annotated[
        list[Literal[1, 2]], Field(min_length=2, max_length=2)
    ]
    damage_present: bool
    observations: Annotated[list[DamageAuditFinding], Field(max_length=20)]
    clear_regions: Annotated[list[DamageAuditClearRegion], Field(max_length=30)]
    not_assessable_regions: Annotated[
        list[DamageAuditUnassessableRegion], Field(max_length=30)
    ]

    @model_validator(mode="after")
    def internally_consistent(self):
        if set(self.assessed_image_indices) != {1, 2}:
            raise ValueError("both image 1 and image 2 must be assessed exactly once")
        if self.damage_present != bool(self.observations):
            raise ValueError(
                "damage_present must be true exactly when observations is non-empty"
            )
        if not (self.observations or self.clear_regions or self.not_assessable_regions):
            raise ValueError("at least one inspected region must be reported")
        return self


class ViewObservation(AIModel):
    image_index: int = Field(ge=1, le=2)
    visible_region: Text = ""
    image_quality: Text = "unknown"
    damage_observations: TextList = Field(default_factory=list)
    notes: TextList = Field(default_factory=list)

    @field_validator("damage_observations", "notes", mode="before")
    @classmethod
    def normalize_observation_text_lists(cls, value, info: ValidationInfo):
        if _is_exact_type_validation(info):
            return value
        return _text_as_list(value)


class FoundItemAnalysis(AIModel):
    # Identification anchors are required: {} must never count as a successful analysis.
    generic_name: Name
    object_name: Name
    views_consistent: bool = False
    alternative_names: TextList = Field(default_factory=list)
    object_count: int = Field(default=1, ge=1, le=1000)
    component_counts: list[ComponentCount] = Field(default_factory=list, max_length=60)
    count_is_estimate: bool = True
    count_confidence: Confidence = "low"
    counting_notes: TextList = Field(default_factory=list)
    category: ShortText = "unknown"
    subcategory: ShortText = "unknown"
    document_kind: DocumentKind = "none"
    document_owner_name: ShortText | None = None
    colors: TextList = Field(default_factory=list)
    material: TextList = Field(default_factory=list)
    brand: ShortText | None = None
    model_or_variant: ShortText | None = None
    visible_markings: TextList = Field(default_factory=list)
    functional_components: TextList = Field(default_factory=list)
    condition: Literal["new", "good", "fair", "poor", "unknown"] = "unknown"
    condition_visibility: Text = "not_assessable"
    condition_confidence: Confidence = "low"
    surface_assessments: list[SurfaceAssessment] = Field(
        default_factory=list, max_length=60
    )
    condition_details: TextList = Field(default_factory=list)
    patterns: TextList = Field(default_factory=list)
    distinctive_features: TextList = Field(default_factory=list)
    likely_use: Text = ""
    short_description: Text = ""
    confidence: Confidence = "low"
    needs_review: bool = True
    uncertainty_notes: TextList = Field(default_factory=list)
    extraction_summary: Text = ""
    received_view_count: int = Field(default=0, ge=0, le=2)
    view_observations: list[ViewObservation] = Field(default_factory=list, max_length=2)

    @field_validator(
        "alternative_names",
        "counting_notes",
        "colors",
        "material",
        "visible_markings",
        "functional_components",
        "condition_details",
        "patterns",
        "distinctive_features",
        "uncertainty_notes",
        mode="before",
    )
    @classmethod
    def normalize_text_lists(cls, value, info: ValidationInfo):
        if _is_exact_type_validation(info):
            return value
        return _text_as_list(value)

    @field_validator(
        "likely_use", "short_description", "extraction_summary", mode="before"
    )
    @classmethod
    def normalize_scalar_text(cls, value, info: ValidationInfo):
        if _is_exact_type_validation(info):
            return value
        return _text_as_string(value)

    @model_validator(mode="after")
    def flag_uncertain_views(self):
        if (
            not self.views_consistent
            or self.received_view_count != 2
            or {view.image_index for view in self.view_observations} != {1, 2}
            or self.confidence == "low"
        ):
            self.needs_review = True
        return self


class FoundItemReviewReconciliation(AIModel):
    """Complete canonical semantic state after finder review."""

    generic_name: Name
    object_name: Name
    alternative_names: TextList
    category: ShortText
    subcategory: ShortText
    document_kind: DocumentKind
    document_owner_name: ShortText | None
    colors: TextList
    material: TextList
    brand: ShortText | None
    model_or_variant: ShortText | None
    visible_markings: TextList
    functional_components: TextList
    condition: Literal["new", "good", "fair", "poor", "unknown"]
    condition_details: TextList
    patterns: TextList
    distinctive_features: TextList
    likely_use: Text
    short_description: Text
    uncertainty_notes: TextList
    extraction_summary: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1500),
    ]


class FoundItemReviewRequest(AIModel):
    """Finder review input; the current structured analysis must keep exact types."""

    analysis: FoundItemAnalysis
    correction_notes: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1500),
    ]

    @field_validator("analysis", mode="before")
    @classmethod
    def exact_analysis_types(cls, value):
        if isinstance(value, FoundItemAnalysis):
            return value
        return FoundItemAnalysis.model_validate(
            value,
            strict=True,
            context={"exact_types": True},
        )


class QueryAnalysis(AIModel):
    generic_name: Name
    possible_names: TextList = Field(default_factory=list)
    category: ShortText | None = None
    subcategory: ShortText | None = None
    colors: TextList = Field(default_factory=list)
    materials: TextList = Field(default_factory=list)
    brand: ShortText | None = None
    visible_markings: TextList = Field(default_factory=list)
    distinctive_features: TextList = Field(default_factory=list)
    damage_or_condition: TextList = Field(default_factory=list)
    component_details: TextList = Field(default_factory=list)
    location_terms: TextList = Field(default_factory=list)
    uncertainties: TextList = Field(default_factory=list)


class MatchAssessment(AIModel):
    candidate_id: Name
    ai_similarity: float
    matched_features: TextList = Field(default_factory=list)
    conflicting_features: TextList = Field(default_factory=list)
    explanation: Text = "Insufficient evidence for a reliable comparison."
    needs_review: bool = True

    @field_validator("candidate_id")
    @classmethod
    def valid_candidate_id(cls, value):
        return str(UUID(value))

    @field_validator("ai_similarity", mode="before")
    @classmethod
    def clamp_score(cls, value):
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
        ):
            raise ValueError("AI similarity must be a finite number")
        return max(0.0, min(1.0, float(value)))


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchInput(APIModel):
    anonymous_session_id: UUID
    idempotency_key: UUID
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2500)
    ]
    last_seen_location: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)
    ]
    last_seen_at: AwareDatetime
    category: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None
    ) = None
    primary_color: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None
    ) = None
    brand: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None
    ) = None

    @field_validator("last_seen_at")
    @classmethod
    def to_utc(cls, value):
        return value.astimezone(timezone.utc)


class ImageURLs(APIModel):
    front: str
    back: str


class FoundItem(APIModel):
    id: UUID
    item_code: str
    status: Literal["available", "retrieved"]
    found_location: str
    found_at: AwareDatetime
    analysis: FoundItemAnalysis
    image_urls: ImageURLs


class MatchResult(APIModel):
    item: FoundItem
    score: float = Field(ge=0, le=100)
    ai_similarity: float = Field(ge=0, le=1)
    deterministic_feature_score: float = Field(ge=0, le=1)
    location_score: float = Field(ge=0, le=1)
    time_proximity_score: float = Field(ge=0, le=1)
    matched_features: list[str]
    conflicting_features: list[str]
    explanation: str
    needs_review: bool


class SearchResponse(APIModel):
    search_id: UUID
    results: list[MatchResult]


class RetrievalResponse(APIModel):
    id: UUID
    item_id: UUID
    item_code: str
    item_name: str
    compartment: Literal["C3"]
    retriever: Literal["Anonymous retriever"]
    retrieved_at: AwareDatetime
    simulated: Literal[True]


class RetrievalRequest(APIModel):
    search_request_id: UUID
    anonymous_session_id: UUID


class HealthResponse(APIModel):
    api: Literal["ok"] = "ok"
    database: str
    storage: str
    ollama: str


class PipelineEvent(APIModel):
    stage: Literal["uploading", "analyzing", "saving", "complete", "error"]
    item: FoundItem | None = None
    message: str | None = None
    status: int | None = None
