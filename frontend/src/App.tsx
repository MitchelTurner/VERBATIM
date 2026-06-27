/**
 * Root dashboard: sync job management and transcript browser.
 *
 * Data refreshes every 10s so job status updates without a manual reload.
 * API calls go through api.ts; in dev, Vite proxies /api to port 8000.
 */
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { JobCard } from "./components/JobCard";
import { JobForm } from "./components/JobForm";
import { StatsBar } from "./components/StatsBar";
import { ToastContainer } from "./components/ToastContainer";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { useToast } from "./hooks/useToast";
import type { ChannelSummary, FrequencyOption, Stats, SyncJob, SyncJobInput } from "./types";
import "./App.css";

const defaultForm: SyncJobInput = {
  name: "",
  channel_account: "",
  max_videos: 25,
  languages: ["en"],
  frequency: "24h",
  enabled: true,
  force_refresh: false,
  include_videos: true,
  include_streams: true,
  include_live: true,
};

type Tab = "jobs" | "transcripts";

function formatDate(value: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

export default function App() {
  const { toasts, push, dismiss } = useToast();
  const [tab, setTab] = useState<Tab>("jobs");
  const [jobs, setJobs] = useState<SyncJob[]>([]);
  const [channels, setChannels] = useState<ChannelSummary[]>([]);
  const [frequencies, setFrequencies] = useState<FrequencyOption[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [form, setForm] = useState<SyncJobInput>(defaultForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [runningJobs, setRunningJobs] = useState<Set<number>>(new Set());

  const frequencyMap = useMemo(
    () => Object.fromEntries(frequencies.map((item) => [item.value, item.label])),
    [frequencies],
  );

  const refresh = useCallback(async () => {
    const [jobsData, channelsData, frequencyData, statsData] = await Promise.all([
      api.listJobs(),
      api.listChannels(),
      api.listFrequencies(),
      api.getStats(),
    ]);
    setJobs(jobsData);
    setChannels(channelsData);
    setFrequencies(frequencyData);
    setStats(statsData);
    setStatsLoading(false);
  }, []);

  useEffect(() => {
    refresh()
      .catch((err: Error) => push("error", err.message))
      .finally(() => setLoading(false));
  }, [refresh, push]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      refresh().catch(() => undefined);
    }, 10000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  function resetForm() {
    setForm(defaultForm);
    setEditingId(null);
  }

  function startEdit(job: SyncJob) {
    setEditingId(job.id);
    setForm({
      name: job.name || "",
      channel_account: job.channel_account,
      max_videos: job.max_videos,
      languages: job.languages,
      frequency: job.frequency,
      enabled: job.enabled,
      force_refresh: job.force_refresh,
      include_videos: job.include_videos,
      include_streams: job.include_streams,
      include_live: job.include_live,
    });
    setTab("jobs");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);

    const payload: SyncJobInput = {
      ...form,
      name: form.name?.trim() || null,
      languages: form.languages
        .flatMap((value) => value.split(","))
        .map((value) => value.trim())
        .filter(Boolean),
      max_videos: form.max_videos ? Number(form.max_videos) : null,
    };

    try {
      if (editingId) {
        await api.updateJob(editingId, payload);
        push("success", "Sync job updated");
      } else {
        await api.createJob(payload);
        push("success", "Sync job created");
      }
      resetForm();
      await refresh();
    } catch (err) {
      push("error", err instanceof Error ? err.message : "Failed to save job");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(jobId: number) {
    if (!window.confirm("Delete this sync job?")) return;
    try {
      await api.deleteJob(jobId);
      if (editingId === jobId) resetForm();
      push("success", "Sync job deleted");
      await refresh();
    } catch (err) {
      push("error", err instanceof Error ? err.message : "Failed to delete job");
    }
  }

  async function handleRun(jobId: number) {
    setRunningJobs((current) => new Set(current).add(jobId));
    try {
      await api.runJob(jobId);
      push("info", "Sync started in the background");
      await refresh();
    } catch (err) {
      push("error", err instanceof Error ? err.message : "Failed to start job");
    } finally {
      setRunningJobs((current) => {
        const next = new Set(current);
        next.delete(jobId);
        return next;
      });
    }
  }

  return (
    <div className="app">
      <ToastContainer toasts={toasts} onDismiss={dismiss} />

      <header className="hero">
        <div>
          <h1>YouTube Transcript Sync</h1>
          <p>
            Schedule channel syncs, browse stored transcripts, and keep live streams up to date.
          </p>
        </div>
      </header>

      <StatsBar stats={stats} loading={statsLoading} />

      <nav className="tab-nav" aria-label="Main navigation">
        <button
          type="button"
          className={`tab-btn ${tab === "jobs" ? "active" : ""}`}
          onClick={() => setTab("jobs")}
        >
          Sync jobs
        </button>
        <button
          type="button"
          className={`tab-btn ${tab === "transcripts" ? "active" : ""}`}
          onClick={() => setTab("transcripts")}
        >
          Transcripts
        </button>
      </nav>

      {tab === "jobs" ? (
        <>
          <div className="layout">
            <JobForm
              form={form}
              editingId={editingId}
              saving={saving}
              frequencies={frequencies}
              onChange={setForm}
              onSubmit={handleSubmit}
              onCancel={resetForm}
            />

            <section className="panel">
              <h2>Synced channels</h2>
              {channels.length === 0 ? (
                <div className="empty-state">
                  <p>No channels synced yet.</p>
                  <p className="meta">Create a job and run it to populate transcripts.</p>
                </div>
              ) : (
                <div className="channel-list">
                  {channels.map((channel) => (
                    <div className="channel-item" key={channel.id}>
                      <div>
                        <strong>{channel.name || channel.youtube_channel_id}</strong>
                        <div className="meta">{channel.url}</div>
                      </div>
                      <span className="pill">{channel.transcript_count} transcripts</span>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>

          <section className="panel jobs-panel">
            <h2>Sync jobs</h2>
            {loading ? (
              <p className="empty">Loading jobs...</p>
            ) : jobs.length === 0 ? (
              <div className="empty-state">
                <p>No jobs yet.</p>
                <p className="meta">Use a quick-start template above or create a custom job.</p>
              </div>
            ) : (
              <div className="stack">
                {jobs.map((job) => (
                  <JobCard
                    key={job.id}
                    job={job}
                    frequencyMap={frequencyMap}
                    running={runningJobs.has(job.id)}
                    onRun={handleRun}
                    onEdit={startEdit}
                    onDelete={handleDelete}
                    formatDate={formatDate}
                  />
                ))}
              </div>
            )}
          </section>
        </>
      ) : (
        <TranscriptPanel channels={channels} />
      )}
    </div>
  );
}
