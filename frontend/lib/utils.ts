import type { FoundItemAnalysis } from "./types";

export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
export const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

export function validateImage(file: File): string | null {
  if (!IMAGE_TYPES.includes(file.type)) return "Choose a JPG, PNG, or WebP image.";
  if (file.size > MAX_IMAGE_BYTES) return "This image is too large. The limit is 10 MB per photograph.";
  if (!file.size) return "This file is empty. Please choose another photograph.";
  return null;
}

export function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Time unavailable";
  return new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila", month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
  }).format(date);
}

// datetime-local has no zone. These inputs explicitly represent Philippine time.
export function manilaToISO(value: string): string {
  return new Date(`${value}:00+08:00`).toISOString();
}

export function manilaNowInput(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Manila", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date());
  const part = (name: string) => parts.find((p) => p.type === name)?.value;
  return `${part("year")}-${part("month")}-${part("day")}T${part("hour")}:${part("minute")}`;
}

export function readable(value?: string | null): string {
  if (!value) return "Not visible";
  return value.replaceAll("_", " ");
}

export function isSensitiveId(analysis: Pick<FoundItemAnalysis, "generic_name" | "object_name" | "category" | "subcategory" | "document_kind">): boolean {
  if (analysis.document_kind && analysis.document_kind !== "none") return true;
  const label = `${analysis.generic_name} ${analysis.object_name} ${analysis.subcategory}`.toLowerCase();
  if (/\b(?:identification(?: card)?|id card|school id|student id|government id|national id|driver'?s? licen[cs]e|passport|bank card|credit card|debit card|atm card)\b/.test(label)) return true;
  return /\bdocument\b/i.test(analysis.category) && /\b(?:id|licen[cs]e)\b/.test(label);
}
