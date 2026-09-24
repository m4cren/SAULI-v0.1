import type { FoundItem, FoundItemAnalysis, PipelineEvent, ReconcileReviewRequest, Retrieval, SearchResponse } from "./types";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const REQUEST_TIMEOUT = 15 * 60 * 1000;

export class ApiError extends Error {
  constructor(message: string, public status = 0) { super(message); this.name = "ApiError"; }
}

async function responseError(response: Response): Promise<never> {
  let detail = `Request failed (${response.status}). Please try again.`;
  try {
    const data = await response.json();
    if (typeof data.detail === "string") detail = data.detail;
    else if (Array.isArray(data.detail)) {
      detail = data.detail.map((entry: { loc?: string[]; msg?: string }) =>
        `${entry.loc?.slice(1).join(" ") || "Request"}: ${entry.msg || "Invalid value"}`,
      ).join(". ");
    }
  } catch { /* An upstream error may not have a JSON body. */ }
  throw new ApiError(detail, response.status);
}

// Keep the timeout active while reading a streamed response, not just its headers.
async function request<T>(path: string, init: RequestInit, read: (response: Response) => Promise<T>): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  init.signal?.addEventListener("abort", abort, { once: true });
  if (init.signal?.aborted) controller.abort();
  let timedOut = false;
  const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, REQUEST_TIMEOUT);
  try {
    const response = await fetch(`${API_BASE}${path}`, { ...init, signal: controller.signal, cache: "no-store" });
    if (!response.ok) await responseError(response);
    return await read(response);
  } catch (error) {
    if (timedOut) throw new ApiError("The request took longer than 15 minutes. Check the backend before trying again.");
    if (controller.signal.aborted) throw new ApiError("Request canceled. Any saving already started on the server may still finish.");
    if (error instanceof ApiError) throw error;
    if (error instanceof TypeError) throw new ApiError("Cannot reach the SAULI backend. Check that FastAPI is running and NEXT_PUBLIC_API_BASE_URL is correct.");
    throw error;
  } finally {
    clearTimeout(timeout);
    init.signal?.removeEventListener("abort", abort);
  }
}

export function analyzeFoundItem(form: FormData, signal: AbortSignal): Promise<FoundItemAnalysis> {
  return request("/api/found-items/analyze", {
    method: "POST", body: form, signal,
  }, (response) => response.json());
}

export function reconcileFoundItemReview(payload: ReconcileReviewRequest, signal: AbortSignal): Promise<FoundItemAnalysis> {
  return request("/api/found-items/reconcile-review", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  }, (response) => response.json());
}

export function confirmAndStoreItem(form: FormData, idempotencyKey: string, onEvent: (event: PipelineEvent) => void, signal: AbortSignal): Promise<FoundItem> {
  return request("/api/found-items/confirm-and-store", {
    method: "POST", body: form, signal,
    headers: { Accept: "text/event-stream", "X-Idempotency-Key": idempotencyKey },
  }, async (response) => {
    if (!response.headers.get("content-type")?.includes("text/event-stream")) return response.json();
    const reader = response.body?.getReader();
    if (!reader) throw new ApiError("The backend returned an empty response.");
    const decoder = new TextDecoder();
    let buffer = "";
    let item: FoundItem | undefined;
    const parseEvent = (block: string) => {
      const data = block.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
      if (!data) return;
      const event: PipelineEvent = JSON.parse(data);
      onEvent(event);
      if (event.stage === "error") throw new ApiError(event.message || "The item could not be saved.", event.status);
      if (event.stage === "complete" && event.item) item = event.item;
    };
    try {
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done }).replace(/\r/g, "");
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
          parseEvent(buffer.slice(0, boundary));
          buffer = buffer.slice(boundary + 2);
        }
        if (done) break;
      }
      if (buffer.trim()) parseEvent(buffer);
    } finally { reader.releaseLock(); }
    if (!item) throw new ApiError("The connection ended before saving was confirmed. Check the backend before submitting again.");
    return item;
  });
}

export function searchItems(form: FormData, signal: AbortSignal): Promise<SearchResponse> {
  return request("/api/matches/search", { method: "POST", body: form, signal }, (response) => response.json());
}

export function getItem(id: string, signal: AbortSignal): Promise<FoundItem> {
  return request(`/api/found-items/${encodeURIComponent(id)}`, { signal }, (response) => response.json());
}

export function simulateRetrieval(id: string, searchRequestId: string, anonymousSessionId: string, signal: AbortSignal): Promise<Retrieval> {
  return request(`/api/retrievals/${encodeURIComponent(id)}/simulate`, {
    method: "POST", signal, headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ search_request_id: searchRequestId, anonymous_session_id: anonymousSessionId }),
  }, (response) => response.json());
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}
