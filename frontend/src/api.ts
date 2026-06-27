/**
 * Typed HTTP client for the FastAPI backend (/api/*).
 * Throws Error with the server detail message on non-2xx responses.
 */
import type {
  ChannelSummary,
  FrequencyOption,
  Stats,
  SyncJob,
  SyncJobInput,
  SyncRun,
  TranscriptDetail,
  TranscriptSummary,
} from "./types";

const API_BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // ignore
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

export const api = {
  getStats: () => request<Stats>("/stats"),
  listFrequencies: () => request<FrequencyOption[]>("/frequencies"),
  listChannels: () => request<ChannelSummary[]>("/channels"),
  listJobs: () => request<SyncJob[]>("/jobs"),
  createJob: (payload: SyncJobInput) =>
    request<SyncJob>("/jobs", { method: "POST", body: JSON.stringify(payload) }),
  updateJob: (id: number, payload: Partial<SyncJobInput>) =>
    request<SyncJob>(`/jobs/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteJob: (id: number) => request<void>(`/jobs/${id}`, { method: "DELETE" }),
  runJob: (id: number) => request<{ status: string }>(`/jobs/${id}/run`, { method: "POST" }),
  listRuns: (id: number) => request<SyncRun[]>(`/jobs/${id}/runs`),
  listTranscripts: (params?: { search?: string; channel_id?: number; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.search) query.set("search", params.search);
    if (params?.channel_id !== undefined) query.set("channel_id", String(params.channel_id));
    if (params?.limit !== undefined) query.set("limit", String(params.limit));
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<TranscriptSummary[]>(`/transcripts${suffix}`);
  },
  getTranscript: (id: number) => request<TranscriptDetail>(`/transcripts/${id}`),
};
