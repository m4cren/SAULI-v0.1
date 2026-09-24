export interface ComponentCount {
  component: string;
  count: number;
  count_is_estimate: boolean;
}

export interface SurfaceAssessment {
  component: string;
  status: "visible_damage" | "no_visible_damage" | "not_assessable";
  damage_types: string[];
  location: string;
  severity: "minor" | "moderate" | "severe" | null;
  certainty: "confirmed" | "probable" | "uncertain";
  evidence: string;
}

export interface ViewObservation {
  image_index: number;
  visible_region: string;
  image_quality: string;
  damage_observations: string[];
  notes: string[];
}

export interface FoundItemAnalysis {
  generic_name: string;
  object_name: string;
  views_consistent: boolean;
  alternative_names: string[];
  object_count: number;
  component_counts: ComponentCount[];
  count_is_estimate: boolean;
  count_confidence: "high" | "medium" | "low";
  counting_notes: string[];
  category: string;
  subcategory: string;
  colors: string[];
  material: string[];
  brand: string | null;
  model_or_variant: string | null;
  visible_markings: string[];
  functional_components: string[];
  condition: "new" | "good" | "fair" | "poor" | "unknown";
  condition_visibility: string;
  condition_confidence: "high" | "medium" | "low";
  surface_assessments: SurfaceAssessment[];
  condition_details: string[];
  patterns: string[];
  distinctive_features: string[];
  likely_use: string;
  short_description: string;
  confidence: "high" | "medium" | "low";
  extraction_summary: string;
  needs_review: boolean;
  uncertainty_notes: string[];
  received_view_count: number;
  view_observations: ViewObservation[];
}

export interface ReconcileReviewRequest {
  analysis: FoundItemAnalysis;
  previous_summary: string;
  corrected_summary: string;
}

export interface FoundItem {
  id: string;
  item_code: string;
  status: "available" | "retrieved";
  found_location: string;
  found_at: string;
  analysis: FoundItemAnalysis;
  image_urls: { front: string; back: string };
}

export interface MatchResult {
  item: FoundItem;
  score: number;
  ai_similarity: number;
  deterministic_feature_score: number;
  location_score: number;
  time_proximity_score: number;
  matched_features: string[];
  conflicting_features: string[];
  explanation: string;
  needs_review: boolean;
}

export interface SearchResponse { search_id: string; results: MatchResult[] }

export interface Retrieval {
  id: string;
  item_id: string;
  item_name: string;
  item_code: string;
  compartment: string;
  retriever: string;
  retrieved_at: string;
  simulated: true;
}

export type PipelineStage = "uploading" | "analyzing" | "saving" | "complete";
export interface PipelineEvent {
  stage: PipelineStage | "error";
  item?: FoundItem;
  message?: string;
  status?: number;
}

export interface SearchFilters {
  last_seen_location: string;
  last_seen_at: string;
  category: string;
  primary_color: string;
  brand: string;
}
