"use client";

import { useState } from "react";
import { api, type MonitorEvent, type MonitorSchedule } from "@/lib/api";
import { EVENT_LABEL, SCHEDULE_LABEL, localTime, timeAgo } from "@/lib/display";

interface Props {
  schedule: MonitorSchedule;
  events: MonitorEvent[];
  onChanged: () => Promise<void>;
}

const INTERVALS = [6, 12, 24, 168] as const;

// Scheduled checks and the history of what the monitor did. Scheduled checks are a loop inside
// the backend on this laptop: they only run while it's running. Nothing runs in the cloud.
export default function MonitorActivity({ schedule, events, onChanged }: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(change: Partial<Pick<MonitorSchedule, "enabled" | "interval_hours" | "include_news">>) {
    setSaving(true);
    setError(null);
    try {
      await api.monitor.setSchedule({
        enabled: schedule.enabled,
        interval_hours: schedule.interval_hours,
        include_news: schedule.include_news,
        ...change,
      });
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <section className="section" aria-labelledby="schedule-h">
        <div className="task-panel">
          <h2 id="schedule-h">Scheduled checks</h2>
          <p className="muted">
            Scheduled checks run inside the backend on this laptop, so only while it&apos;s running. Nothing runs in
            the cloud, and a closed laptop doesn&apos;t check. Their exact requests appear in the outbound log until the
            backend restarts; the history below keeps the results.
          </p>
          <div className="schedule-row">
            <label className="check">
              <input
                type="checkbox"
                checked={schedule.enabled}
                disabled={saving}
                onChange={(e) => save({ enabled: e.target.checked })}
              />
              <span>Check automatically</span>
            </label>
            <label className="inline-select">
              <span className="sr-only">How often</span>
              <select
                value={schedule.interval_hours}
                disabled={saving}
                onChange={(e) => save({ interval_hours: Number(e.target.value) as MonitorSchedule["interval_hours"] })}
              >
                {INTERVALS.map((h) => (
                  <option key={h} value={h}>
                    {SCHEDULE_LABEL[h]}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="check mt">
            <input
              type="checkbox"
              checked={schedule.include_news}
              disabled={saving}
              onChange={(e) => save({ include_news: e.target.checked })}
            />
            <span>Include news and official notices (uses Tavily and Exa credits and the local LLM)</span>
          </label>
          <p className="muted small mt">
            {schedule.enabled
              ? `Next check ${schedule.next_run ? localTime(schedule.next_run) : "soon"}, if the backend is running then. `
              : "Off. "}
            Last full check {timeAgo(schedule.last_run)}.
          </p>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </div>
      </section>

      <section className="section" aria-labelledby="history-h">
        <div className="section-head">
          <h2 id="history-h">History</h2>
          <span className="muted small">Newest first, kept on this laptop</span>
        </div>
        {events.length === 0 ? (
          <p className="muted">Nothing yet. Adding a company or running a check shows up here.</p>
        ) : (
          <ol className="event-list">
            {events.map((e) => (
              <li key={e.id}>
                <time className="event-time" dateTime={e.time} title={localTime(e.time)}>
                  {timeAgo(e.time)}
                </time>
                <span className={`event-kind ${e.kind}`}>{EVENT_LABEL[e.kind]}</span>
                <span>{e.message}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </>
  );
}
