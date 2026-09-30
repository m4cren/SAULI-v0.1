"use client";

import { CalendarClock, Check, CircleAlert, Clock3, MapPin, RotateCcw, Save, ScanLine, Sparkles, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button, ErrorMessage, ItemImage, Note } from "@/components/common";
import { ImageUploader } from "@/components/image-uploader";
import { formatProcessDuration, ProgressIndicator, type PipelineLogEntry } from "@/components/progress-indicator";
import { analyzeFoundItem, confirmAndStoreItem, errorMessage, reconcileFoundItemReview } from "@/lib/api";
import type { FoundItem, FoundItemAnalysis, PipelineEvent } from "@/lib/types";
import { formatDate, isSensitiveId, manilaNowInput, manilaToISO, readable } from "@/lib/utils";

type StationScreen = "capture" | "details" | "identifying" | "review" | "saving" | "result";

const SAVE_MESSAGES: Partial<Record<PipelineEvent["stage"], string>> = {
  uploading: "Uploading the two item photos.",
  analyzing: "Checking the confirmed item details.",
  saving: "Saving the confirmed item record.",
  complete: "Item saved successfully.",
};

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
  const [correctionNotes, setCorrectionNotes] = useState("");
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
      setCorrectionNotes("");
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
    if (submissionInFlight.current || !front || !back || !analysis) return;
    if (!analysis.extraction_summary.trim()) {
      setError("SAULI did not produce a searchable summary. Analyze the photos again.");
      return;
    }
    submissionInFlight.current = true;
    const note = correctionNotes.trim();
    beginOperation(note ? "Applying the correction note to the item details." : "Preparing the confirmed item details.");
    setScreen("saving");
    try {
      let confirmedAnalysis = analysis;
      if (note) {
        confirmedAnalysis = await reconcileFoundItemReview({
          analysis,
          correction_notes: note,
        }, request.current!.signal);
        setAnalysis(confirmedAnalysis);
        setCorrectionNotes("");
        setLogs((current) => [...current, logEntry("reconciled", "Corrections applied to the summary and matching details.")]);
      }

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
    setAnalysis(null); setCorrectionNotes(""); setBusy(false); setLogs([]); setProcessElapsedMs(0);
    setAnalysisElapsedMs(0); setSavingElapsedMs(0); setError(""); setSaved(null);
    idempotencyKey.current = "";
  };

  const currentFile = captureSide === 1 ? front : back;
  const updateCurrentFile = (file: File | null) => {
    setError(""); setAnalysis(null); setCorrectionNotes(""); idempotencyKey.current = "";
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
    setAnalysis(null); setCorrectionNotes(""); idempotencyKey.current = "";
  };
  const returnToDetails = () => {
    if (submissionInFlight.current) return;
    setScreen("details"); setError(""); setAnalysis(null); setCorrectionNotes(""); idempotencyKey.current = "";
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

      {screen === "review" && analysis && <form className="kiosk-review-form" onSubmit={confirmAndSave}>
        <div className="kiosk-page-heading"><div><h1>Review item details</h1><p>Correct anything that does not match the item before saving.</p></div><KioskSteps step={2} /></div>
        <div className="kiosk-review-layout">
          <div className="kiosk-review-sidebar">
            <CapturedPhotos frontPreview={frontPreview} backPreview={backPreview} onRetake={() => editSide(1)} />
            <div className="review-context"><span><MapPin size={14} /> {location}</span><span><Clock3 size={14} /> Identified in {formatProcessDuration(analysisElapsedMs)}</span></div>
          </div>
          <section className="kiosk-review-fields">
            <div className="ai-review-notice"><CircleAlert size={19} /><div><strong>Review before saving</strong><p>Check the summary against the photos. Add a correction note if anything is wrong.</p></div></div>
            <fieldset className="review-field-grid">
              <div className="field review-field-wide"><span className="review-summary-label">Searchable summary</span><p className="review-summary-text">{analysis.extraction_summary || analysis.short_description || "No summary available."}</p></div>
              <div className="field review-field-wide"><label htmlFor="review-notes">Correction note <span className="field-optional">(optional)</span></label><textarea id="review-notes" value={correctionNotes} onChange={(event) => { setCorrectionNotes(event.target.value); setError(""); }} rows={3} maxLength={1500} placeholder="For example: the helmet is yellow, not white; the visor is scratched." /><p className="field-hint">SAULI updates the summary and related matching details. The note is not saved separately.</p></div>
            </fieldset>
            <ErrorMessage message={error} />
            <div className="kiosk-review-actions"><Button type="submit" disabled={busy}><Save size={17} /> Confirm and save item</Button><Button type="button" secondary disabled={busy} onClick={returnToDetails}>Back to item details</Button></div>
            <p className="sauli-review-disclaimer">SAULI can make mistakes. Check important information before saving.</p>
          </section>
        </div>
      </form>}

      {screen === "saving" && <section className="kiosk-identifying" aria-live="polite">
        <KioskSteps step={3} />
        <div className="kiosk-identifying-card">
          <div className={`kiosk-loader ${busy ? "spin" : ""}`}><Save size={28} /></div><strong>Details confirmed</strong>
          <h1>{busy ? "Saving the item…" : "Saving stopped"}</h1>
          <p>{busy ? "SAULI is applying any correction, then saving the item." : "Review the message below before trying again."}</p>
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
          <div className="kiosk-result-images"><div><span>Side 1</span><ItemImage src={saved.image_urls.front} alt={`Side 1 of ${saved.analysis.object_name}`} className={isSensitiveId(saved.analysis) ? "sensitive-id-image" : ""} /></div><div><span>Side 2</span><ItemImage src={saved.image_urls.back} alt={`Side 2 of ${saved.analysis.object_name}`} className={isSensitiveId(saved.analysis) ? "sensitive-id-image" : ""} /></div></div>
        </div>
      </section>}
    </main>;
}
