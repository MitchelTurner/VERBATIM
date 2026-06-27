import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import type { ChannelSummary, TranscriptDetail, TranscriptSummary } from "../types";

/** Search and read stored transcripts from the database. */
interface Props {
  channels: ChannelSummary[];
}

export function TranscriptPanel({ channels }: Props) {
  const [search, setSearch] = useState("");
  const [channelId, setChannelId] = useState<number | "">("");
  const [results, setResults] = useState<TranscriptSummary[]>([]);
  const [selected, setSelected] = useState<TranscriptDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);

  async function loadTranscripts(query = search, channel = channelId) {
    setLoading(true);
    try {
      const data = await api.listTranscripts({
        search: query || undefined,
        channel_id: channel === "" ? undefined : channel,
      });
      setResults(data);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadTranscripts("", "");
  }, []);

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    setSelected(null);
    await loadTranscripts();
  }

  async function openTranscript(id: number) {
    setDetailLoading(true);
    try {
      setSelected(await api.getTranscript(id));
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <div className="transcript-layout">
      <section className="panel">
        <h2>Browse transcripts</h2>
        <form className="search-row" onSubmit={handleSearch}>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search title or transcript text..."
          />
          <select
            value={channelId}
            onChange={(e) =>
              setChannelId(e.target.value ? Number(e.target.value) : "")
            }
          >
            <option value="">All channels</option>
            {channels.map((channel) => (
              <option key={channel.id} value={channel.id}>
                {channel.name || channel.youtube_channel_id}
              </option>
            ))}
          </select>
          <button className="btn btn-primary" type="submit">
            Search
          </button>
        </form>

        {loading ? (
          <p className="empty">Loading transcripts...</p>
        ) : results.length === 0 ? (
          <div className="empty-state">
            <p>No transcripts found.</p>
            <p className="meta">Run a sync job first, then search here.</p>
          </div>
        ) : (
          <div className="transcript-list">
            {results.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`transcript-item ${selected?.id === item.id ? "active" : ""}`}
                onClick={() => openTranscript(item.id)}
              >
                <div className="transcript-item-title">
                  {item.video_title || item.youtube_video_id}
                </div>
                <div className="meta">
                  {item.channel_name} · {item.language_code}
                  {item.is_live ? " · live" : ""}
                  {item.content_type === "stream" ? " · stream" : ""}
                </div>
                <div className="transcript-preview">{item.preview}</div>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="panel transcript-detail">
        <h2>Transcript</h2>
        {detailLoading ? (
          <p className="empty">Loading...</p>
        ) : selected ? (
          <>
            <div className="detail-header">
              <h3>{selected.video_title || selected.youtube_video_id}</h3>
              <div className="meta">
                {selected.channel_name} · {selected.language} · fetched{" "}
                {new Date(selected.fetched_at).toLocaleString()}
              </div>
              <a href={selected.video_url} target="_blank" rel="noreferrer">
                Open on YouTube
              </a>
            </div>
            <pre className="transcript-body">{selected.content}</pre>
          </>
        ) : (
          <div className="empty-state">
            <p>Select a transcript to read it here.</p>
          </div>
        )}
      </section>
    </div>
  );
}
