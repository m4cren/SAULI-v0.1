"use client";

import { ArrowRight, CalendarDays, Clock3, MapPin, Search } from "lucide-react";
import { BackButton, Button } from "./common";
import { ImageUploader } from "./image-uploader";
import type { SearchFilters } from "@/lib/types";
import { manilaNowInput } from "@/lib/utils";

export function SearchForm({ description, onDescription, photo, onPhoto, onNext }: {
  description: string; onDescription: (value: string) => void; photo: File | null; onPhoto: (file: File | null) => void; onNext: () => void;
}) {
  return <div className="fade-in">
    <h1>What did you lose?</h1><p className="view-description">Describe the item and any detail you remember.</p>
    <form onSubmit={(event) => { event.preventDefault(); onNext(); }} className="search-form">
      <div className="description-card"><label htmlFor="description"><span className="ask-icon"><Search size={16} /></span> Ask SAULI</label><textarea id="description" name="description" value={description} onChange={(event) => onDescription(event.target.value)} required minLength={3} maxLength={2500} placeholder="I lost a blue water bottle with a loop handle and a small dent near the top…" aria-describedby="description-hint" /><div className="description-card-bottom"><span id="description-hint">Describe it in your own words</span><span>{description.length}/2500</span></div></div>
      <ImageUploader compact label="A photo to help?" hint="Optional · JPG, PNG or WebP · up to 10 MB" file={photo} onChange={onPhoto} />
      <Button type="submit" disabled={description.trim().length < 3}>Find my lost item <ArrowRight size={18} /></Button>
    </form>
  </div>;
}

export function FilterForm({ filters, onChange, onBack, onSubmit, busy }: {
  filters: SearchFilters; onChange: (filters: SearchFilters) => void; onBack: () => void; onSubmit: () => void; busy: boolean;
}) {
  const update = (key: keyof SearchFilters, value: string) => onChange({ ...filters, [key]: value });
  return <div className="fade-in">
    <BackButton onClick={onBack} disabled={busy}>Back</BackButton><h1>Search details</h1>
    <form className="filter-form" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
      <div className="field"><label htmlFor="last-location">Where was it last seen? <span className="required">*</span></label><div className="input-icon"><MapPin size={17} /><input id="last-location" value={filters.last_seen_location} onChange={(event) => update("last_seen_location", event.target.value)} placeholder="e.g. Library, second floor" required maxLength={200} disabled={busy} /></div></div>
      <div className="field"><label htmlFor="last-time">Date & time last seen <span className="required">*</span></label><div className="input-icon"><CalendarDays size={17} /><input id="last-time" type="datetime-local" value={filters.last_seen_at} onChange={(event) => update("last_seen_at", event.target.value)} max={manilaNowInput()} required disabled={busy} aria-describedby="time-zone" /></div><p id="time-zone" className="field-hint"><Clock3 size={12} /> Philippine time (Asia/Manila, UTC+8)</p></div>
      <div className="optional-divider"><span>Optional filters</span></div>
      <div className="field"><label htmlFor="category">Item category</label><select id="category" value={filters.category} onChange={(event) => update("category", event.target.value)} disabled={busy}><option value="">Choose a category</option><option>Electronics</option><option>Bags</option><option>Personal accessories</option><option>Drinkware</option><option>Keys</option><option>Clothing</option><option>Stationery</option><option>Documents</option><option>Other</option></select></div>
      <div className="filter-pair"><div className="field"><label htmlFor="color">Primary color</label><select id="color" value={filters.primary_color} onChange={(event) => update("primary_color", event.target.value)} disabled={busy}><option value="">Choose a color</option>{["Black", "White", "Gray", "Silver", "Blue", "Green", "Red", "Pink", "Purple", "Yellow", "Orange", "Brown", "Multicolor"].map((color) => <option key={color}>{color}</option>)}</select></div><div className="field"><label htmlFor="brand">Brand or label</label><input id="brand" value={filters.brand} onChange={(event) => update("brand", event.target.value)} placeholder="e.g. AquaFlask" maxLength={120} disabled={busy} /></div></div>
      <Button type="submit" loading={busy}>{busy ? "Looking for possible matches…" : "Search stored items"}{!busy && <Search size={18} />}</Button>
    </form>
  </div>;
}

export function SearchSkeleton({ onCancel }: { onCancel: () => void }) {
  return <div className="search-loading" role="status" aria-live="polite"><div className="loading-orbit"><Search size={27} /></div><strong>Searching stored items</strong><p>Local AI is comparing eligible records.</p><div className="skeleton-card"><span /><div><i /><i /><i /></div></div><button className="text-button" type="button" onClick={onCancel}>Cancel</button></div>;
}
