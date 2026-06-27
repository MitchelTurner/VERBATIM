import { FormEvent } from "react";
import type { FrequencyOption, SyncJobInput } from "../types";

/** One-click presets that pre-fill the job form for common use cases. */
const TEMPLATES: { label: string; values: Partial<SyncJobInput> }[] = [
  {
    label: "Daily uploads",
    values: {
      frequency: "24h",
      enabled: true,
      include_videos: true,
      include_streams: true,
      include_live: true,
      max_videos: 25,
      force_refresh: false,
    },
  },
  {
    label: "Live streams",
    values: {
      frequency: "15m",
      enabled: true,
      include_videos: false,
      include_streams: true,
      include_live: true,
      max_videos: 10,
      force_refresh: false,
    },
  },
  {
    label: "Manual once",
    values: {
      frequency: "manual",
      enabled: false,
      include_videos: true,
      include_streams: true,
      include_live: true,
      max_videos: 50,
      force_refresh: false,
    },
  },
];

interface Props {
  form: SyncJobInput;
  editingId: number | null;
  saving: boolean;
  frequencies: FrequencyOption[];
  onChange: (form: SyncJobInput) => void;
  onSubmit: (event: FormEvent) => void;
  onCancel: () => void;
}

export function JobForm({
  form,
  editingId,
  saving,
  frequencies,
  onChange,
  onSubmit,
  onCancel,
}: Props) {
  const contentSelected =
    form.include_videos || form.include_streams || form.include_live;

  return (
    <section className="panel">
      <h2>{editingId ? "Edit sync job" : "New sync job"}</h2>

      {!editingId && (
        <div className="template-row">
          <span className="meta">Quick start:</span>
          {TEMPLATES.map((template) => (
            <button
              key={template.label}
              type="button"
              className="btn btn-secondary btn-small"
              onClick={() => onChange({ ...form, ...template.values })}
            >
              {template.label}
            </button>
          ))}
        </div>
      )}

      <form className="stack" onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="name">Job name (optional)</label>
          <input
            id="name"
            value={form.name || ""}
            onChange={(e) => onChange({ ...form, name: e.target.value })}
            placeholder="Weekly channel sync"
          />
        </div>

        <div className="field">
          <label htmlFor="channel">YouTube channel</label>
          <input
            id="channel"
            required
            value={form.channel_account}
            onChange={(e) => onChange({ ...form, channel_account: e.target.value })}
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
              onChange={(e) => onChange({ ...form, frequency: e.target.value })}
            >
              {frequencies.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="maxVideos">Max items per run</label>
            <input
              id="maxVideos"
              type="number"
              min={1}
              value={form.max_videos ?? ""}
              onChange={(e) =>
                onChange({
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
              onChange({
                ...form,
                languages: e.target.value.split(",").map((value) => value.trim()),
              })
            }
            placeholder="en, es"
          />
        </div>

        <div className="field">
          <label>Content to sync</label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.include_live}
              onChange={(e) => onChange({ ...form, include_live: e.target.checked })}
            />
            Currently live broadcast
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.include_streams}
              onChange={(e) => onChange({ ...form, include_streams: e.target.checked })}
            />
            Past live streams
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.include_videos}
              onChange={(e) => onChange({ ...form, include_videos: e.target.checked })}
            />
            Regular uploaded videos
          </label>
          {!contentSelected && (
            <small className="field-error">Select at least one content type.</small>
          )}
        </div>

        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => onChange({ ...form, enabled: e.target.checked })}
          />
          Enable scheduled syncs
        </label>

        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.force_refresh}
            onChange={(e) => onChange({ ...form, force_refresh: e.target.checked })}
          />
          Re-fetch existing transcripts
        </label>

        <div className="actions">
          <button
            className="btn btn-primary"
            type="submit"
            disabled={saving || !contentSelected}
          >
            {saving ? "Saving..." : editingId ? "Update job" : "Create job"}
          </button>
          {editingId && (
            <button className="btn btn-secondary" type="button" onClick={onCancel}>
              Cancel edit
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
