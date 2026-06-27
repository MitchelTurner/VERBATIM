import { useState } from "react";
import { api } from "../api";
import type { SyncJob, SyncRun } from "../types";

/** Single sync job card with expandable run history (lazy-loaded on first expand). */
interface Props {
  job: SyncJob;
  frequencyMap: Record<string, string>;
  running: boolean;
  onRun: (id: number) => void;
  onEdit: (job: SyncJob) => void;
  onDelete: (id: number) => void;
  formatDate: (value: string | null) => string;
}

function statusClass(status: string) {
  return `status status-${status}`;
}

export function JobCard({
  job,
  frequencyMap,
  running,
  onRun,
  onEdit,
  onDelete,
  formatDate,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [runs, setRuns] = useState<SyncRun[] | null>(null);
  const [runsLoading, setRunsLoading] = useState(false);

  async function toggleHistory() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (runs !== null) return;
    setRunsLoading(true);
    try {
      setRuns(await api.listRuns(job.id));
    } catch {
      setRuns([]);
    } finally {
      setRunsLoading(false);
    }
  }

  return (
    <article className="job-card">
      <header>
        <div>
          <h3>{job.name || job.channel_account}</h3>
          <div className="meta">{job.channel_account}</div>
        </div>
        <span className={statusClass(job.last_status)}>{job.last_status}</span>
      </header>

      <div className="pill-list">
        <span className="pill">{frequencyMap[job.frequency] || job.frequency}</span>
        <span className="pill">{job.max_videos ?? "All"} items</span>
        {job.include_live && <span className="pill">Live</span>}
        {job.include_streams && <span className="pill">Streams</span>}
        {job.include_videos && <span className="pill">Videos</span>}
        <span className="pill">{job.enabled ? "Scheduled" : "Manual"}</span>
      </div>

      <div className="meta">
        Last run: {formatDate(job.last_run_at)} · Next run: {formatDate(job.next_run_at)}
      </div>

      {job.last_error && <div className="inline-error">{job.last_error}</div>}

      <div className="actions">
        <button
          className="btn btn-primary"
          type="button"
          onClick={() => onRun(job.id)}
          disabled={job.last_status === "running" || running}
        >
          {job.last_status === "running" || running ? "Running..." : "Run now"}
        </button>
        <button className="btn btn-secondary" type="button" onClick={() => onEdit(job)}>
          Edit
        </button>
        <button className="btn btn-secondary" type="button" onClick={toggleHistory}>
          {expanded ? "Hide history" : "History"}
        </button>
        <button className="btn btn-danger" type="button" onClick={() => onDelete(job.id)}>
          Delete
        </button>
      </div>

      {expanded && (
        <div className="run-history">
          {runsLoading ? (
            <p className="meta">Loading run history...</p>
          ) : runs && runs.length > 0 ? (
            <ul>
              {runs.map((run) => (
                <li key={run.id}>
                  <strong>{run.status}</strong> · {formatDate(run.started_at)} · saved{" "}
                  {run.transcripts_saved}/{run.videos_processed}
                  {run.message ? ` · ${run.message}` : ""}
                </li>
              ))}
            </ul>
          ) : (
            <p className="meta">No runs recorded yet.</p>
          )}
        </div>
      )}
    </article>
  );
}
