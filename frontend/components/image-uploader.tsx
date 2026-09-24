"use client";

import { Camera, Check, ImagePlus, RotateCcw, Upload, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { validateImage } from "@/lib/utils";

export function ImageUploader({ label, hint, file, onChange, disabled = false, compact = false }: {
  label: string; hint: string; file: File | null; onChange: (file: File | null) => void; disabled?: boolean; compact?: boolean;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState("");
  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    // This effect owns and cleans up the browser resource backing the preview.
    setPreview(url); // eslint-disable-line react-hooks/set-state-in-effect
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const select = (next: File | undefined) => {
    if (disabled || !next) return;
    const issue = validateImage(next);
    setError(issue || "");
    if (!issue) onChange(next);
  };

  return <div className={`upload-field ${compact ? "upload-compact" : ""}`}>
    <label className="upload-label" htmlFor={id}>{label}{file && <span className="tiny-status"><Check size={12} /> Ready</span>}</label>
    <input ref={input} id={id} type="file" accept="image/jpeg,image/png,image/webp" disabled={disabled} className="sr-only" aria-describedby={`${id}-help ${id}-error`} onChange={(event) => { select(event.target.files?.[0]); event.target.value = ""; }} />
    {file ? <div className="upload-preview">
      {preview && <img src={preview} alt={`${label}: ${file.name}`} />}
      <div className="preview-toolbar"><span title={file.name}>{file.name}</span><button type="button" aria-label={`Replace ${label.toLowerCase()}`} onClick={() => input.current?.click()} disabled={disabled}><RotateCcw size={15} /></button><button type="button" aria-label={`Remove ${label.toLowerCase()}`} onClick={() => { onChange(null); setError(""); setPreview(""); }} disabled={disabled}><X size={16} /></button></div>
    </div> : <button type="button" className={`upload-drop ${dragging ? "dragging" : ""}`} disabled={disabled} onClick={() => input.current?.click()} onDragOver={(event) => { event.preventDefault(); if (!disabled) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); const files = event.dataTransfer.files; if (files.length !== 1) { setError("Choose one photograph for this view."); return; } select(files[0]); }}>
      <span className="upload-icon">{compact ? <ImagePlus size={23} /> : <Camera size={25} strokeWidth={1.5} />}</span>
      <span className="upload-title">{compact ? "Add a reference photo" : "Choose a photograph"}</span>
      <span className="upload-subtitle">or drag and drop it here</span>
      {!compact && <span className="upload-add"><Upload size={13} /> Upload image</span>}
    </button>}
    <p id={`${id}-help`} className="field-hint">{hint}</p>
    <p id={`${id}-error`} className="field-error" role={error ? "alert" : undefined}>{error}</p>
  </div>;
}
