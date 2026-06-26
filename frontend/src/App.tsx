import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { ChannelSummary, FrequencyOption, SyncJob, SyncJobInput } from "./types";
import "./App.css";

const defaultForm: SyncJobInput = {
  name: "",
  channel_account: "",
  max_videos: 25,
  languages: ["en"],
  frequency: "24h",
  enabled: true,
  force_refresh: false,
};

function formatDate(value: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function statusClass(status: string) {
  return `status status-${status}`;
}

export default function App() {
  const [jobs, setJobs] = useState<SyncJob[]>([]);
  const [channels, setChannels] = useState<ChannelSummary[]>([]);
  const [frequencies, setFrequencies] = useState<FrequencyOption[]>([]);
  const [form, setForm] = useState<SyncJobInput>(defaultForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runningJobs, setRunningJobs] = useState<Set<number>>(new Set());

  const frequencyMap = useMemo(
    () => Object.fromEntries(frequencies.map((item) => [item.value, item.label])),
    [frequencies],
  );

  const refresh = useCallback(async () => {
    const [jobsData, channelsData, frequencyData] = await Promise.all([
      api.listJobs(),
      api.listChannels(),
      api.listFrequencies(),
    ]);
    setJobs(jobsData);
    setChannels(channelsData);
    setFrequencies(frequencyData);
  }, []);

  useEffect(() => {
    refresh()
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [refresh]);

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
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);

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
      } else {
        await api.createJob(payload);
      }
      resetForm();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save job");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(jobId: number) {
    if (!window.confirm("Delete this sync job?")) return;
    setError(null);
    try {
      await api.deleteJob(jobId);
      if (editingId === jobId) resetForm();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete job");
    }
  }

  async function handleRun(jobId: number) {
    setError(null);
    setRunningJobs((current) => new Set(current).add(jobId));
    try {
      await api.runJob(jobId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start job");
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
      <header className="hero">
        <div>
          <h1>YouTube Transcript Sync</h1>
          <p>
            Choose a channel, set how often to scrape, and store transcripts in PostgreSQL.
          </p>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <div className="layout">
        <section className="panel">
          <h2>{editingId ? "Edit sync job" : "New sync job"}</h2>
          <form className="stack" onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor="name">Job name (optional)</label>
              <input
                id="name"
                value={form.name || ""}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Weekly MKBHD sync"
              />
            </div>

            <div className="field">
              <label htmlFor="channel">YouTube channel</label>
              <input
                id="channel"
                required
                value={form.channel_account}
                onChange={(e) => setForm({ ...form, channel_account: e.target.value })}
                placeholder="@mkbhd or https://www.youtube.com/@mkbhd"
              />
              <small>URL, @handle, or channel ID (UC...)</small>
            </div>

            <div className="row">
              <div className="field">
                <label htmlFor="frequency">Sync frequency</label>
                <select
                  id="frequency"
                  value={form.frequency}
                  onChange={(e) => setForm({ ...form, frequency: e.target.value })}
                >
                  {frequencies.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field">
                <label htmlFor="maxVideos">Max videos per run</label>
                <input
                  id="maxVideos"
                  type="number"
                  min={1}
                  value={form.max_videos ?? ""}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      max_videos: e.target.value ? Number(e.target.value) : null,
                    })
                  }
                />
              </div>
            </div>

            <div className="field">
              <label htmlFor="languages">Preferred languages</label>
              <input
                id="languages"
                value={form.languages.join(", ")}
                onChange={(e) =>
                  setForm({
                    ...form,
                    languages: e.target.value.split(",").map((value) => value.trim()),
                  })
                }
                placeholder="en, es"
              />
              <small>Comma-separated language codes. First match wins.</small>
            </div>

            <label className="checkbox">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
              />
              Enable scheduled syncs
            </label>

            <label className="checkbox">
              <input
                type="checkbox"
                checked={form.force_refresh}
                onChange={(e) => setForm({ ...form, force_refresh: e.target.checked })}
              />
              Re-fetch transcripts even if they already exist
            </label>

            <div className="actions">
              <button className="btn btn-primary" type="submit" disabled={saving}>
                {saving ? "Saving..." : editingId ? "Update job" : "Create job"}
              </button>
              {editingId && (
                <button className="btn btn-secondary" type="button" onClick={resetForm}>
                  Cancel edit
                </button>
              )}
            </div>
          </form>
        </section>

        <section className="panel">
          <h2>Synced channels</h2>
          {channels.length === 0 ? (
            <p className="empty">No channels synced yet. Run a job to populate data.</p>
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

      <section className="panel" style={{ marginTop: "1.25rem" }}>
        <h2>Sync jobs</h2>
        {loading ? (
          <p className="empty">Loading jobs...</p>
        ) : jobs.length === 0 ? (
          <p className="empty">No jobs yet. Create one to start scraping transcripts.</p>
        ) : (
          <div className="stack">
            {jobs.map((job) => (
              <article className="job-card" key={job.id}>
                <header>
                  <div>
                    <h3>{job.name || job.channel_account}</h3>
                    <div className="meta">{job.channel_account}</div>
                  </div>
                  <span className={statusClass(job.last_status)}>{job.last_status}</span>
                </header>

                <div className="pill-list">
                  <span className="pill">{frequencyMap[job.frequency] || job.frequency}</span>
                  <span className="pill">{job.max_videos ?? "All"} videos</span>
                  {job.languages.map((language) => (
                    <span className="pill" key={language}>
                      {language}
                    </span>
                  ))}
                  <span className="pill">{job.enabled ? "Enabled" : "Disabled"}</span>
                </div>

                <div className="meta">
                  Last run: {formatDate(job.last_run_at)} · Next run:{" "}
                  {formatDate(job.next_run_at)}
                </div>

                {job.last_error && <div className="error-banner">{job.last_error}</div>}

                <div className="actions">
                  <button
                    className="btn btn-primary"
                    onClick={() => handleRun(job.id)}
                    disabled={job.last_status === "running" || runningJobs.has(job.id)}
                  >
                    {job.last_status === "running" || runningJobs.has(job.id)
                      ? "Running..."
                      : "Run now"}
                  </button>
                  <button className="btn btn-secondary" onClick={() => startEdit(job)}>
                    Edit
                  </button>
                  <button className="btn btn-danger" onClick={() => handleDelete(job.id)}>
                    Delete
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
