import type {
  ChannelSummary,
  FrequencyOption,
  SyncJob,
  SyncJobInput,
  SyncRun,
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
};
