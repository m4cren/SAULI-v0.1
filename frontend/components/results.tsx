"use client";

import { ArrowRight, Check, ChevronRight, Clock3, MapPin, Search, SlidersHorizontal, TriangleAlert } from "lucide-react";
import { useState } from "react";
import type { MatchResult } from "@/lib/types";
import { formatDate, isSensitiveId, readable } from "@/lib/utils";
import { BackButton, Button, ItemImage, Note } from "./common";

export function ScoreBadge({ score }: { score: number }) {
  return <span className="score-badge">{Math.round(Math.max(0, Math.min(100, score)))}% prototype match</span>;
}

export function MatchExplanation({ result, expanded = false }: { result: MatchResult; expanded?: boolean }) {
  return <div className="match-explanation">{result.matched_features.length > 0 && <div className="matching-features">{result.matched_features.slice(0, expanded ? undefined : 3).map((feature, index) => <span key={index}><Check size={13} />{feature}</span>)}</div>}<p>{result.explanation}</p>{expanded && <>
    {result.conflicting_features.length > 0 && <div className="mismatch-note"><strong><TriangleAlert size={15} /> Details to check</strong><ul>{result.conflicting_features.map((feature, index) => <li key={index}>{feature}</li>)}</ul></div>}
    {(result.needs_review || result.item.analysis.needs_review) && <Note title="Take another look">{result.item.analysis.uncertainty_notes.join(" ") || "The AI is uncertain about some details. Please compare the photographs carefully."}</Note>}
    <details className="score-details"><summary>How this prototype score was calculated</summary><dl><div><dt>AI similarity · 55% weight</dt><dd>{Math.round(result.ai_similarity * 100)}%</dd></div><div><dt>Visible features · 20% weight</dt><dd>{Math.round(result.deterministic_feature_score * 100)}%</dd></div><div><dt>Location · 15% weight</dt><dd>{Math.round(result.location_score * 100)}%</dd></div><div><dt>Time proximity · 10% weight</dt><dd>{Math.round(result.time_proximity_score * 100)}%</dd></div></dl><p>A ranking aid, not a verified identity probability or proof of ownership.</p></details>
  </>}</div>;
}

export function ResultCard({ result, onSelect, disabled }: { result: MatchResult; onSelect: () => void; disabled: boolean }) {
  const item = result.item;
  return <article className="result-card"><div className="result-card-main"><ItemImage src={item.image_urls.front} alt={`Front of ${item.analysis.object_name}`} className={isSensitiveId(item.analysis) ? "sensitive-id-image" : ""} /><div className="result-card-info"><ScoreBadge score={result.score} /><h2>{item.analysis.object_name}</h2><p><MapPin size={12} />{item.found_location}</p><p><Clock3 size={12} />{formatDate(item.found_at)}</p></div></div><button type="button" className="result-action" onClick={onSelect} disabled={disabled}>View details <ArrowRight size={16} /></button></article>;
}

export function Results({ results, description, onEdit, onSelect, busy }: { results: MatchResult[]; description: string; onEdit: () => void; onSelect: (result: MatchResult) => void; busy: boolean }) {
  return <div className="fade-in"><BackButton onClick={onEdit} disabled={busy}>New search</BackButton><h1>Search results</h1><p className="view-description">{results.length} possible {results.length === 1 ? "match" : "matches"}</p><div className="query-summary"><span title={description}>{description}</span><button type="button" onClick={onEdit} disabled={busy} aria-label="Edit search"><SlidersHorizontal size={16} />Edit</button></div>{results.length ? <div className="result-list">{[...results].sort((a, b) => b.score - a.score || a.item.id.localeCompare(b.item.id)).map((result) => <ResultCard key={result.item.id} result={result} onSelect={() => onSelect(result)} disabled={busy} />)}</div> : <div className="empty-results"><span className="empty-icon"><Search size={31} /></span><h2>No matching item</h2><p>Try changing the description or filters.</p><Button secondary onClick={onEdit}>Adjust search <ChevronRight size={16} /></Button></div>}</div>;
}

export function ResultDetail({ result, onBack, onConfirm, busy }: { result: MatchResult; onBack: () => void; onConfirm: () => void; busy: boolean }) {
  const [view, setView] = useState<"front" | "back">("front");
  const { item } = result;
  return <div className="fade-in"><BackButton onClick={onBack} disabled={busy}>Results</BackButton><div className="detail-photo"><ItemImage src={item.image_urls[view]} alt={`${view} view of ${item.analysis.object_name}`} className={isSensitiveId(item.analysis) ? "sensitive-id-image" : ""} /><div className="view-toggle" aria-label="Photograph view"><button type="button" aria-pressed={view === "front"} className={view === "front" ? "active" : ""} onClick={() => setView("front")}>Front</button><button type="button" aria-pressed={view === "back"} className={view === "back" ? "active" : ""} onClick={() => setView("back")}>Back</button></div></div><div className="detail-status"><ScoreBadge score={result.score} /><span><span className="status-dot" />{item.status === "available" ? "Available" : "Retrieved"}</span></div><h1 className="item-title">{item.analysis.object_name}</h1><p className="item-summary">{item.analysis.short_description}</p><dl className="detail-rows"><div><dt>Found at</dt><dd>{item.found_location}</dd></div><div><dt>Date found</dt><dd>{formatDate(item.found_at)}</dd></div><div><dt>Item code</dt><dd>{item.item_code}</dd></div><div><dt>Condition</dt><dd>{readable(item.analysis.condition)}</dd></div></dl><h2 className="small-heading">Match details</h2><MatchExplanation result={result} expanded /><div className="stacked-actions"><Button onClick={onConfirm} loading={busy} disabled={item.status !== "available"}>This is my item <ArrowRight size={17} /></Button><Button secondary onClick={onBack} disabled={busy}>Not mine</Button></div></div>;
}
