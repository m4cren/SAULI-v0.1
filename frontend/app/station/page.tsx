"use client";

import { CalendarClock, Check, CircleAlert, Clock3, MapPin, RefreshCw, RotateCcw, Save, ScanLine, Sparkles, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button, ErrorMessage, ItemImage, Note } from "@/components/common";
import { ImageUploader } from "@/components/image-uploader";
import { formatProcessDuration, ProgressIndicator, type PipelineLogEntry } from "@/components/progress-indicator";
import { analyzeFoundItem, confirmAndStoreItem, errorMessage, reconcileFoundItemReview } from "@/lib/api";
import type { FoundItem, FoundItemAnalysis, PipelineEvent } from "@/lib/types";
import { formatDate, manilaNowInput, manilaToISO, readable } from "@/lib/utils";

type StationScreen = "capture" | "details" | "identifying" | "review" | "saving" | "result";

interface ReviewDraft {
  objectName: string;
  genericName: string;
  category: string;
  subcategory: string;
  colors: string;
  materials: string;
  brand: string;
  model: string;
  markings: string;
  distinctiveFeatures: string;
  condition: FoundItemAnalysis["condition"];
  shortDescription: string;
  searchableSummary: string;
}

const SAVE_MESSAGES: Partial<Record<PipelineEvent["stage"], string>> = {
  uploading: "Uploading the two item photos.",
  analyzing: "Checking the confirmed item details.",
  saving: "Saving the confirmed item record.",
  complete: "Item saved successfully.",
};

const CONDITIONS: FoundItemAnalysis["condition"][] = ["new", "good", "fair", "poor", "unknown"];

function analysisToDraft(analysis: FoundItemAnalysis): ReviewDraft {
  return {
    objectName: analysis.object_name,
    genericName: analysis.generic_name,
    category: analysis.category,
    subcategory: analysis.subcategory,
    colors: analysis.colors.join(", "),
    materials: analysis.material.join(", "),
    brand: analysis.brand || "",
    model: analysis.model_or_variant || "",
    markings: analysis.visible_markings.join(", "),
    distinctiveFeatures: analysis.distinctive_features.join(", "),
    condition: analysis.condition,
    shortDescription: analysis.short_description,
    searchableSummary: analysis.extraction_summary,
  };
}

function commaSeparatedValues(value: string) {
  return [...new Set(value.split(",").map((entry) => entry.trim()).filter(Boolean))];
}

function applyReview(analysis: FoundItemAnalysis, draft: ReviewDraft): FoundItemAnalysis {
  return {
    ...analysis,
    object_name: draft.objectName.trim(),
    generic_name: draft.genericName.trim(),
    category: draft.category.trim(),
    subcategory: draft.subcategory.trim(),
    colors: commaSeparatedValues(draft.colors),
    material: commaSeparatedValues(draft.materials),
    brand: draft.brand.trim() || null,
    model_or_variant: draft.model.trim() || null,
    visible_markings: commaSeparatedValues(draft.markings),
    distinctive_features: commaSeparatedValues(draft.distinctiveFeatures),
    condition: draft.condition,
    short_description: draft.shortDescription.trim(),
    extraction_summary: draft.searchableSummary.trim(),
  };
}

function KioskSteps({ step }: { step: 1 | 2 | 3 }) {
  return <ol className="kiosk-steps" aria-label="Station intake progress">
    {["Capture", "Identify", "Saved"].map((label, index) => {
      const number = (index + 1) as 1 | 2 | 3;
      const state = number < step ? "done" : number === step ? "active" : "";
      return <li key={label} className={state} aria-current={number === step ? "step" : undefined}>
        <span>{number < step ? <Check size={15} /> : number}</span>{label}
      </li>;
    })}
  </ol>;
}

function SideStatus({ side, file, active, disabled = false, onClick }: {
  side: 1 | 2;
  file: File | null;
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return <button type="button" className={`kiosk-side-status ${active ? "active" : ""} ${file ? "captured" : ""}`} onClick={onClick} disabled={disabled}>
    {file && <Check size={17} />}
    <span><strong>Side {side}</strong><small>{file ? "Captured" : active ? "Ready" : "Waiting"}</small></span>
  </button>;
}

function CapturedPhotos({ frontPreview, backPreview, onRetake }: {
  frontPreview: string;
  backPreview: string;
  onRetake: () => void;
}) {
  return <section className="kiosk-photo-review" aria-label="Captured item photographs">
    <div className="kiosk-review-heading"><span><ScanLine size={19} /> Captured item</span><button type="button" onClick={onRetake}><RotateCcw size={14} /> Retake photos</button></div>
    <div className="saved-images"><div><span>Side 1</span><ItemImage src={frontPreview || undefined} alt="Captured side 1" /></div><div><span>Side 2</span><ItemImage src={backPreview || undefined} alt="Captured side 2" /></div></div>
  </section>;
}

export default function StationPage() {
  const [front, setFront] = useState<File | null>(null);
  const [back, setBack] = useState<File | null>(null);
  const [frontPreview, setFrontPreview] = useState("");
  const [backPreview, setBackPreview] = useState("");
  const [captureSide, setCaptureSide] = useState<1 | 2>(1);
  const [screen, setScreen] = useState<StationScreen>("capture");
  const [location, setLocation] = useState("");
  const [overrideTime, setOverrideTime] = useState(false);
  const [foundAtOverride, setFoundAtOverride] = useState("");
  const [analysis, setAnalysis] = useState<FoundItemAnalysis | null>(null);
  const [reviewDraft, setReviewDraft] = useState<ReviewDraft | null>(null);
  const [lastSyncedSummary, setLastSyncedSummary] = useState("");
  const [reconciling, setReconciling] = useState(false);
  const [busy, setBusy] = useState(false);
  const [logs, setLogs] = useState<PipelineLogEntry[]>([]);
  const [processElapsedMs, setProcessElapsedMs] = useState(0);
  const [analysisElapsedMs, setAnalysisElapsedMs] = useState(0);
  const [savingElapsedMs, setSavingElapsedMs] = useState(0);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<FoundItem | null>(null);
  const submissionInFlight = useRef(false);
  const request = useRef<AbortController | null>(null);
  const idempotencyKey = useRef("");
  const startedAt = useRef(0);
  const logId = useRef(0);
  const previewUrls = useRef({ front: "", back: "" });

  useEffect(() => () => {
    request.current?.abort();
    if (previewUrls.current.front) URL.revokeObjectURL(previewUrls.current.front);
    if (previewUrls.current.back) URL.revokeObjectURL(previewUrls.current.back);
  }, []);

  useEffect(() => {
    if (!busy || !startedAt.current) return;
    const updateElapsed = () => setProcessElapsedMs(performance.now() - startedAt.current);
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 100);
    return () => window.clearInterval(timer);
  }, [busy]);

  const logEntry = (eventStage: string, message: string): PipelineLogEntry => ({ id: ++logId.current, stage: eventStage, message });

  const handleSaveEvent = (event: PipelineEvent) => {
    const message = event.stage === "error"
      ? event.message || "The item could not be saved."
      : SAVE_MESSAGES[event.stage] || event.message || "Saving the item.";
    setLogs((current) => [...current, logEntry(event.stage, message)]);
  };

  const beginOperation = (initialMessage: string) => {
    request.current = new AbortController();
    startedAt.current = performance.now();
    logId.current = 0;
    setLogs([logEntry("start", initialMessage)]);
    setProcessElapsedMs(0);
    setBusy(true);
    setError("");
  };

  const analyze = async (event: React.SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submissionInFlight.current) return;
    if (!front || !back || !location.trim()) {
      setError("Add both item photos and the found location.");
      return;
    }
    if (overrideTime && !foundAtOverride) {
      setError("Choose the developer found date and time, or disable the override.");
      return;
    }

    submissionInFlight.current = true;
    beginOperation("Uploading the two item photos.");
    setScreen("identifying");
    setLogs((current) => [...current, logEntry("identify", "Checking the visible item details.")]);
    try {
      const form = new FormData();
      form.append("front_image", front);
      form.append("back_image", back);
      const result = await analyzeFoundItem(form, request.current!.signal);
      const elapsed = performance.now() - startedAt.current;
      setAnalysisElapsedMs(elapsed);
      setProcessElapsedMs(elapsed);
      setAnalysis(result);
      setReviewDraft(analysisToDraft(result));
      setLastSyncedSummary(result.extraction_summary.trim());
      idempotencyKey.current = "";
      setScreen("review");
    } catch (issue) {
      const message = errorMessage(issue);
      setError(message);
      setLogs((current) => [...current, logEntry("error", message)]);
    } finally {
      setProcessElapsedMs(performance.now() - startedAt.current);
      submissionInFlight.current = false;
      setBusy(false);
    }
  };

  const confirmAndSave = async (event: React.SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submissionInFlight.current || !front || !back || !analysis || !reviewDraft) return;
    if (!reviewDraft.objectName.trim() || !reviewDraft.genericName.trim()) {
      setError("Item name and generic name are required.");
      return;
    }
    if (reviewDraft.searchableSummary.trim() !== lastSyncedSummary) {
      setError("Update the related fields after changing the searchable summary, then review the result before saving.");
      return;
    }
    const listFields = [reviewDraft.colors, reviewDraft.materials, reviewDraft.markings, reviewDraft.distinctiveFeatures];
    if (listFields.some((value) => commaSeparatedValues(value).length > 60)) {
      setError("Use no more than 60 comma-separated entries in each list.");
      return;
    }

    const confirmedAnalysis = applyReview(analysis, reviewDraft);
    submissionInFlight.current = true;
    beginOperation("Preparing the confirmed item details.");
    setScreen("saving");
    try {
      const form = new FormData();
      form.append("front_image", front);
      form.append("back_image", back);
      form.append("found_location", location.trim());
      if (overrideTime) form.append("found_at_override", manilaToISO(foundAtOverride));
      form.append("analysis_json", JSON.stringify(confirmedAnalysis));

      if (!idempotencyKey.current) idempotencyKey.current = crypto.randomUUID();
      const item = await confirmAndStoreItem(form, idempotencyKey.current, handleSaveEvent, request.current!.signal);
      const elapsed = performance.now() - startedAt.current;
      setSavingElapsedMs(elapsed);
      setProcessElapsedMs(elapsed);
      setSaved(item);
      setScreen("result");
    } catch (issue) {
      const message = errorMessage(issue);
      setError(message);
      setLogs((current) => current.at(-1)?.stage === "error" ? current : [...current, logEntry("error", message)]);
    } finally {
      setProcessElapsedMs(performance.now() - startedAt.current);
      submissionInFlight.current = false;
      setBusy(false);
    }
  };

  const reset = () => {
    request.current?.abort();
    if (previewUrls.current.front) URL.revokeObjectURL(previewUrls.current.front);
    if (previewUrls.current.back) URL.revokeObjectURL(previewUrls.current.back);
    previewUrls.current = { front: "", back: "" };
    setFront(null); setBack(null); setFrontPreview(""); setBackPreview(""); setCaptureSide(1);
    setScreen("capture"); setLocation(""); setOverrideTime(false); setFoundAtOverride("");
    setAnalysis(null); setReviewDraft(null); setLastSyncedSummary(""); setReconciling(false); setBusy(false); setLogs([]); setProcessElapsedMs(0);
    setAnalysisElapsedMs(0); setSavingElapsedMs(0); setError(""); setSaved(null);
    idempotencyKey.current = "";
  };

  const currentFile = captureSide === 1 ? front : back;
  const updateCurrentFile = (file: File | null) => {
    setError(""); setAnalysis(null); setReviewDraft(null); setLastSyncedSummary(""); idempotencyKey.current = "";
    const key = captureSide === 1 ? "front" : "back";
    if (previewUrls.current[key]) URL.revokeObjectURL(previewUrls.current[key]);
    const preview = file ? URL.createObjectURL(file) : "";
    previewUrls.current[key] = preview;
    if (captureSide === 1) { setFront(file); setFrontPreview(preview); }
    else { setBack(file); setBackPreview(preview); }
  };
  const continueCapture = () => {
    if (!currentFile) return;
    if (captureSide === 1) setCaptureSide(2);
    else if (front && back) setScreen("details");
  };
  const editSide = (side: 1 | 2) => {
    if (submissionInFlight.current) return;
    setCaptureSide(side); setScreen("capture"); setError("");
    setAnalysis(null); setReviewDraft(null); setLastSyncedSummary(""); idempotencyKey.current = "";
  };
  const returnToDetails = () => {
    if (submissionInFlight.current) return;
    setScreen("details"); setError(""); setAnalysis(null); setReviewDraft(null); setLastSyncedSummary(""); idempotencyKey.current = "";
  };
  const updateReviewField = <K extends keyof ReviewDraft>(field: K, value: ReviewDraft[K]) => {
    setReviewDraft((current) => current ? { ...current, [field]: value } : current);
    setError("");
  };

  const summaryNeedsReconciliation = reviewDraft !== null
    && reviewDraft.searchableSummary.trim() !== lastSyncedSummary;

  const reconcileSummary = async () => {
    if (submissionInFlight.current || !analysis || !reviewDraft || !summaryNeedsReconciliation) return;
    const correctedSummary = reviewDraft.searchableSummary.trim();
    if (!correctedSummary) {
      setError("Enter a searchable summary before updating the related fields.");
      return;
    }

    const currentAnalysis = applyReview(analysis, reviewDraft);
    submissionInFlight.current = true;
    request.current = new AbortController();
    setReconciling(true);
    setError("");
    try {
      const result = await reconcileFoundItemReview({
        analysis: currentAnalysis,
        previous_summary: lastSyncedSummary,
        corrected_summary: correctedSummary,
      }, request.current.signal);
      const nextDraft = analysisToDraft(result);
      setAnalysis(result);
      setReviewDraft(nextDraft);
      setLastSyncedSummary(nextDraft.searchableSummary.trim());
    } catch (issue) {
      setError(errorMessage(issue));
    } finally {
      submissionInFlight.current = false;
      setReconciling(false);
    }
  };

  return <main id="main" className="kiosk-main">
      {screen === "capture" && <>
        <div className="kiosk-page-heading">
          <div><h1>Capture the {captureSide === 1 ? "first" : "second"} side</h1><p>{captureSide === 1 ? "Place the entire item inside the camera frame." : "Rotate the item to show its opposite side and unique details."}</p></div>
          <KioskSteps step={1} />
        </div>
        <div className="kiosk-capture-grid">
          <section className="kiosk-camera-frame" aria-label={`Capture side ${captureSide}`}>
            <ImageUploader label={`Side ${captureSide} photograph`} hint="JPG, PNG or WebP · up to 10 MB" file={currentFile} onChange={updateCurrentFile} />
          </section>
          <aside className="kiosk-capture-controls">
            <div className="kiosk-side-row">
              <SideStatus side={1} file={front} active={captureSide === 1} onClick={() => editSide(1)} />
              <SideStatus side={2} file={back} active={captureSide === 2} disabled={!front} onClick={() => editSide(2)} />
            </div>
            <div className="kiosk-instructions"><h2>Before capturing</h2><ol><li><span>1</span>Remove your hands from the frame.</li><li><span>2</span>Make the color, brand, and marks visible.</li><li><span>3</span>Keep the entire item inside the frame.</li></ol></div>
            <div className="kiosk-control-actions">
              <Button type="button" onClick={continueCapture} disabled={!currentFile}>{captureSide === 1 ? "Continue to side 2" : "Continue to item details"}</Button>
              <Button type="button" secondary onClick={reset}>Cancel</Button>
            </div>
          </aside>
        </div>
      </>}

      {screen === "details" && <form onSubmit={analyze} className="kiosk-details-form">
        <div className="kiosk-page-heading"><div><h1>Item details</h1><p>Add where the item was found before identification.</p></div><KioskSteps step={1} /></div>
        <div className="kiosk-details-grid">
          <CapturedPhotos frontPreview={frontPreview} backPreview={backPreview} onRetake={() => editSide(1)} />
          <section className="kiosk-detail-fields">
            <div className="field"><label htmlFor="found-location">Where was the item found? <span className="required">*</span></label><div className="input-icon"><MapPin size={17} /><input id="found-location" name="found_location" value={location} onChange={(event) => setLocation(event.target.value)} placeholder="e.g. Near the canteen" required maxLength={200} /></div></div>
            <div className="kiosk-developer-time">
              <div className="kiosk-developer-heading"><span><Wrench size={14} /> Developer input</span><small>Optional</small></div>
              <label className="developer-toggle"><input type="checkbox" checked={overrideTime} onChange={(event) => { setOverrideTime(event.target.checked); if (event.target.checked && !foundAtOverride) setFoundAtOverride(manilaNowInput()); }} /><span>Use a custom found date and time</span></label>
              <div className="field developer-time"><label htmlFor="found-time"><CalendarClock size={14} /> Found date and time</label><input id="found-time" type="datetime-local" value={foundAtOverride} onChange={(event) => setFoundAtOverride(event.target.value)} required={overrideTime} disabled={!overrideTime} /><p className="field-hint">{overrideTime ? "Asia/Manila (UTC+8)" : "Disabled — server time will be used"}</p></div>
            </div>
            <ErrorMessage message={error} />
            <div className="kiosk-detail-actions"><Button type="submit" disabled={!location.trim() || busy}><Sparkles size={17} /> Identify item</Button><Button type="button" secondary onClick={() => editSide(2)}>Back to photos</Button></div>
          </section>
        </div>
      </form>}

      {screen === "identifying" && <section className="kiosk-identifying" aria-live="polite">
        <KioskSteps step={2} />
        <div className="kiosk-identifying-card">
          <div className={`kiosk-loader ${busy ? "spin" : ""}`}><Sparkles size={30} /></div><strong>Two sides received</strong>
          <h1>{busy ? "Identifying the item…" : "Identification stopped"}</h1>
          <p>{busy ? "SAULI is checking the item type and visible details." : "Review the log below before trying again."}</p>
          <ProgressIndicator logs={logs} active={busy} elapsedMs={processElapsedMs} /><ErrorMessage message={error} />
          {!busy && error && <Button type="button" secondary onClick={returnToDetails}>Return to item details</Button>}
        </div>
      </section>}

      {screen === "review" && analysis && reviewDraft && <form className="kiosk-review-form" onSubmit={confirmAndSave}>
        <div className="kiosk-page-heading"><div><h1>Review item details</h1><p>Correct anything that does not match the item before saving.</p></div><KioskSteps step={2} /></div>
        <div className="kiosk-review-layout">
          <div className="kiosk-review-sidebar">
            <CapturedPhotos frontPreview={frontPreview} backPreview={backPreview} onRetake={() => editSide(1)} />
            <div className="review-context"><span><MapPin size={14} /> {location}</span><span><Clock3 size={14} /> Identified in {formatProcessDuration(analysisElapsedMs)}</span></div>
          </div>
          <section className="kiosk-review-fields">
            <div className="ai-review-notice"><CircleAlert size={19} /><div><strong>Review before saving</strong><p>SAULI prepared these details from the two photos. Correct anything that does not match the item.</p></div></div>
            <fieldset className="review-field-grid" disabled={reconciling}>
              <div className="field"><label htmlFor="review-object-name">Item name <span className="required">*</span></label><input id="review-object-name" value={reviewDraft.objectName} onChange={(event) => updateReviewField("objectName", event.target.value)} required maxLength={250} /></div>
              <div className="field"><label htmlFor="review-generic-name">Generic name <span className="required">*</span></label><input id="review-generic-name" value={reviewDraft.genericName} onChange={(event) => updateReviewField("genericName", event.target.value)} required maxLength={250} /></div>
              <div className="field"><label htmlFor="review-category">Category</label><input id="review-category" value={reviewDraft.category} onChange={(event) => updateReviewField("category", event.target.value)} maxLength={250} /></div>
              <div className="field"><label htmlFor="review-subcategory">Subcategory</label><input id="review-subcategory" value={reviewDraft.subcategory} onChange={(event) => updateReviewField("subcategory", event.target.value)} maxLength={250} /></div>
              <div className="field"><label htmlFor="review-colors">Colors</label><input id="review-colors" value={reviewDraft.colors} onChange={(event) => updateReviewField("colors", event.target.value)} placeholder="Blue, silver" maxLength={1500} /><p className="field-hint">Separate multiple values with commas.</p></div>
              <div className="field"><label htmlFor="review-materials">Materials</label><input id="review-materials" value={reviewDraft.materials} onChange={(event) => updateReviewField("materials", event.target.value)} placeholder="Plastic, metal" maxLength={1500} /><p className="field-hint">Separate multiple values with commas.</p></div>
              <div className="field"><label htmlFor="review-brand">Visible brand</label><input id="review-brand" value={reviewDraft.brand} onChange={(event) => updateReviewField("brand", event.target.value)} placeholder="Leave blank if none" maxLength={250} /></div>
              <div className="field"><label htmlFor="review-model">Model or variant</label><input id="review-model" value={reviewDraft.model} onChange={(event) => updateReviewField("model", event.target.value)} placeholder="Leave blank if unknown" maxLength={250} /></div>
              <div className="field"><label htmlFor="review-condition">Condition</label><select id="review-condition" value={reviewDraft.condition} onChange={(event) => updateReviewField("condition", event.target.value as ReviewDraft["condition"])}>{CONDITIONS.map((condition) => <option key={condition} value={condition}>{readable(condition)}</option>)}</select></div>
              <div className="field"><label htmlFor="review-markings">Visible markings</label><input id="review-markings" value={reviewDraft.markings} onChange={(event) => updateReviewField("markings", event.target.value)} placeholder="Logo, printed text, scratches" maxLength={1500} /><p className="field-hint">Separate multiple values with commas.</p></div>
              <div className="field review-field-wide"><label htmlFor="review-features">Distinguishing features</label><input id="review-features" value={reviewDraft.distinctiveFeatures} onChange={(event) => updateReviewField("distinctiveFeatures", event.target.value)} placeholder="Unique shape, damage, attachments" maxLength={1500} /><p className="field-hint">Separate multiple values with commas.</p></div>
              <div className="field review-field-wide"><label htmlFor="review-description">Short description</label><textarea id="review-description" value={reviewDraft.shortDescription} onChange={(event) => updateReviewField("shortDescription", event.target.value)} rows={3} maxLength={1500} /></div>
              <div className="field review-field-wide"><label htmlFor="review-summary">Searchable summary</label><textarea id="review-summary" value={reviewDraft.searchableSummary} onChange={(event) => updateReviewField("searchableSummary", event.target.value)} rows={4} maxLength={1500} required />
                {summaryNeedsReconciliation && <div className="summary-reconcile" aria-live="polite"><div><strong>Summary changed</strong><p>Update related fields so item attributes and matching data stay consistent.</p></div><button type="button" onClick={reconcileSummary} disabled={reconciling || !reviewDraft.searchableSummary.trim()}><RefreshCw size={14} className={reconciling ? "spin" : ""} />{reconciling ? "Updating…" : "Update related fields"}</button></div>}
              </div>
            </fieldset>
            <ErrorMessage message={error} />
            <div className="kiosk-review-actions"><Button type="submit" disabled={reconciling || summaryNeedsReconciliation}><Save size={17} /> Confirm and save item</Button><Button type="button" secondary disabled={reconciling} onClick={returnToDetails}>Back to item details</Button></div>
            <p className="sauli-review-disclaimer">SAULI can make mistakes. Check important information before saving.</p>
          </section>
        </div>
      </form>}

      {screen === "saving" && <section className="kiosk-identifying" aria-live="polite">
        <KioskSteps step={3} />
        <div className="kiosk-identifying-card">
          <div className={`kiosk-loader ${busy ? "spin" : ""}`}><Save size={28} /></div><strong>Details confirmed</strong>
          <h1>{busy ? "Saving the item…" : "Saving stopped"}</h1>
          <p>{busy ? "The photos and corrected details are being saved." : "Review the message below before trying again."}</p>
          <ProgressIndicator logs={logs} active={busy} elapsedMs={processElapsedMs} /><ErrorMessage message={error} />
          {!busy && error && <Button type="button" secondary onClick={() => { setScreen("review"); setError(""); }}>Return to review</Button>}
        </div>
      </section>}

      {screen === "result" && saved && <section className="kiosk-result">
        <div className="kiosk-page-heading"><div><h1>Item saved</h1><p>The reviewed item information is now available for matching.</p></div><KioskSteps step={3} /></div>
        <div className="kiosk-result-card">
          <div className="kiosk-result-info">
            <span className="badge">{saved.item_code}</span><h2>{saved.analysis.object_name}</h2>
            <p className="kiosk-process-time"><Clock3 size={14} /> Completed in {formatProcessDuration(analysisElapsedMs + savingElapsedMs)}</p>
            <p className="item-summary">{saved.analysis.extraction_summary || saved.analysis.short_description}</p>
            <div className="attribute-tags">{saved.analysis.colors.map((color) => <span key={color}>{color}</span>)}{saved.analysis.material.map((material) => <span key={material}>{material}</span>)}<span>{readable(saved.analysis.condition)}</span></div>
            <dl className="detail-rows"><div><dt><MapPin size={14} /> Found at</dt><dd>{saved.found_location}</dd></div><div><dt><Clock3 size={14} /> Date and time</dt><dd>{formatDate(saved.found_at)}</dd></div></dl>
            {saved.analysis.needs_review && <Note title="Some details remain uncertain">{saved.analysis.uncertainty_notes.join(" ") || "Some details could not be confirmed from these views."}</Note>}
            <Button type="button" onClick={reset}>Scan another item</Button>
          </div>
          <div className="kiosk-result-images"><div><span>Side 1</span><ItemImage src={saved.image_urls.front} alt={`Side 1 of ${saved.analysis.object_name}`} /></div><div><span>Side 2</span><ItemImage src={saved.image_urls.back} alt={`Side 2 of ${saved.analysis.object_name}`} /></div></div>
        </div>
      </section>}
    </main>;
}
