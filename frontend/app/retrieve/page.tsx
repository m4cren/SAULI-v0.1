"use client";

import { useEffect, useRef, useState } from "react";
import { ErrorMessage } from "@/components/common";
import { FilterForm, SearchForm, SearchSkeleton } from "@/components/search-forms";
import { ResultDetail, Results } from "@/components/results";
import { RetrievalComplete, RetrievalPass, SimulatedLocation } from "@/components/retrieval-simulation";
import { ApiError, errorMessage, getItem, searchItems, simulateRetrieval } from "@/lib/api";
import type { MatchResult, Retrieval, SearchFilters } from "@/lib/types";
import { manilaToISO } from "@/lib/utils";

type Stage = "search" | "filter" | "results" | "detail" | "pass" | "location" | "complete";
const EMPTY_FILTERS: SearchFilters = { last_seen_location: "", last_seen_at: "", category: "", primary_color: "", brand: "" };

export default function RetrievePage() {
  const [stage, setStage] = useState<Stage>("search");
  const [description, setDescription] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const [filters, setFilters] = useState<SearchFilters>(EMPTY_FILTERS);
  const [results, setResults] = useState<MatchResult[]>([]);
  const [selected, setSelected] = useState<MatchResult | null>(null);
  const [retrieval, setRetrieval] = useState<Retrieval | null>(null);
  const [pass, setPass] = useState({ token: "", expiresAt: 0 });
  const [anonymousSessionId, setAnonymousSessionId] = useState("");
  const [searchRequestId, setSearchRequestId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const view = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const storageKey = "sauli-anonymous-session-id";
    let value = sessionStorage.getItem(storageKey);
    if (!value) { value = crypto.randomUUID(); sessionStorage.setItem(storageKey, value); }
    const initialize = window.setTimeout(() => setAnonymousSessionId(value), 0);
    return () => { window.clearTimeout(initialize); request.current?.abort(); };
  }, []);
  useEffect(() => { view.current?.focus({ preventScroll: true }); window.scrollTo({ top: 0, behavior: "smooth" }); }, [stage]);

  const move = (next: Stage) => { setError(""); setStage(next); };
  const beginRequest = () => { request.current = new AbortController(); setBusy(true); setError(""); return request.current.signal; };

  const search = async () => {
    if (busy) return;
    if (!anonymousSessionId) { setError("The anonymous search session is still starting. Please try again."); return; }
    if (!filters.last_seen_at || !filters.last_seen_location.trim()) { setError("Enter the place and time you last saw your item."); return; }
    let lastSeen: string;
    try { lastSeen = manilaToISO(filters.last_seen_at); } catch { setError("Choose a valid date and time in Philippine time."); return; }
    if (new Date(lastSeen).getTime() > Date.now()) { setError("The last-seen time cannot be in the future."); return; }
    const form = new FormData();
    form.append("description", description.trim());
    form.append("last_seen_location", filters.last_seen_location.trim());
    form.append("last_seen_at", lastSeen);
    form.append("anonymous_session_id", anonymousSessionId);
    form.append("idempotency_key", crypto.randomUUID());
    for (const key of ["category", "primary_color", "brand"] as const) if (filters[key].trim()) form.append(key, filters[key].trim());
    if (photo) form.append("query_image", photo);
    try { const response = await searchItems(form, beginRequest()); setSearchRequestId(response.search_id); setResults(response.results); setStage("results"); }
    catch (issue) { setError(errorMessage(issue)); }
    finally { setBusy(false); }
  };

  const openItem = async (result: MatchResult) => {
    if (busy) return;
    try {
      const item = await getItem(result.item.id, beginRequest());
      if (item.status !== "available") { setResults((current) => current.filter((entry) => entry.item.id !== item.id)); throw new ApiError("This item has just been retrieved. Please choose another result or search again.", 409); }
      setSelected({ ...result, item }); setStage("detail");
    } catch (issue) { setError(errorMessage(issue)); }
    finally { setBusy(false); }
  };

  const createPass = async () => {
    if (!selected || busy) return;
    try {
      const item = await getItem(selected.item.id, beginRequest());
      if (item.status !== "available") throw new ApiError("This item is no longer available. Return to search for an updated list.", 409);
      setSelected({ ...selected, item });
      // Prototype only: client-side token, no authentication or authorization claim.
      setPass({ token: crypto.randomUUID(), expiresAt: Date.now() + 10 * 60 * 1000 });
      setStage("pass");
    } catch (issue) { setError(errorMessage(issue)); }
    finally { setBusy(false); }
  };

  const scan = () => { if (Date.now() >= pass.expiresAt) { setError("This demonstration pass has expired. Generate a new one to continue."); return; } move("location"); };
  const remove = async () => {
    if (!selected || busy) return;
    try {
      const response = await simulateRetrieval(selected.item.id, searchRequestId, anonymousSessionId, beginRequest());
      setRetrieval(response); setResults((current) => current.filter((result) => result.item.id !== selected.item.id)); setStage("complete");
    } catch (issue) {
      setError(errorMessage(issue));
      if (issue instanceof ApiError && issue.status === 409) { setResults((current) => current.filter((result) => result.item.id !== selected.item.id)); setStage("results"); }
    } finally { setBusy(false); }
  };

  const reset = () => { setDescription(""); setPhoto(null); setFilters(EMPTY_FILTERS); setResults([]); setSelected(null); setRetrieval(null); setSearchRequestId(""); setPass({ token: "", expiresAt: 0 }); move("search"); };
  const currentStep = stage === "search" ? 0 : stage === "filter" ? 1 : stage === "results" || stage === "detail" ? 2 : 3;

  return <main className="retrieve-main retrieve-main-simple"><section className="retrieve-workspace"><div className="journey-progress" aria-label="Search and retrieval progress">{["Describe", "Details", "Matches", "Retrieve"].map((label, index) => <div key={label} className={index === currentStep ? "active" : index < currentStep ? "done" : ""} aria-current={index === currentStep ? "step" : undefined}><span /><small>{label}</small></div>)}</div><div ref={view} tabIndex={-1} className="retrieve-view" aria-busy={busy}>
      {stage === "search" && <SearchForm description={description} onDescription={setDescription} photo={photo} onPhoto={setPhoto} onNext={() => move("filter")} />}
      {stage === "filter" && <><FilterForm filters={filters} onChange={setFilters} onBack={() => move("search")} onSubmit={search} busy={busy} />{busy && <SearchSkeleton onCancel={() => request.current?.abort()} />}</>}
      {stage === "results" && <Results results={results} description={description} onEdit={() => move("filter")} onSelect={openItem} busy={busy} />}
      {stage === "detail" && selected && <ResultDetail result={selected} onBack={() => move("results")} onConfirm={createPass} busy={busy} />}
      {stage === "pass" && selected && <RetrievalPass key={pass.token} item={selected.item} token={pass.token} expiresAt={pass.expiresAt} onBack={() => move("detail")} onScan={scan} onRenew={createPass} />}
      {stage === "location" && <SimulatedLocation onRemove={remove} onBack={() => move("pass")} busy={busy} />}
      {stage === "complete" && retrieval && <RetrievalComplete retrieval={retrieval} onSearch={reset} />}
      <ErrorMessage message={error} />
    </div></section></main>;
}
