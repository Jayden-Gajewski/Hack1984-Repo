// OWNER: Evidence
// Wayback Machine CDX API (no key needed).
import { outboundFetch } from '../lib/outbound.js';

const CDX = 'https://web.archive.org/cdx/search/cdx';

function toISO(ts) {
  // 20190314123456 -> 2019-03-14
  return `${ts.slice(0, 4)}-${ts.slice(4, 6)}-${ts.slice(6, 8)}`;
}

/** Earliest snapshot of a URL, or null. */
export async function earliestSnapshot(url) {
  const q = new URLSearchParams({ url, output: 'json', limit: '1', fl: 'timestamp,original' });
  const res = await outboundFetch('wayback', `${CDX}?${q}`);
  if (!res.ok) return null;
  const rows = await res.json(); // [["timestamp","original"], ["2019...", "..."]]
  if (rows.length < 2) return null;
  const [timestamp] = rows[1];
  return {
    date: toISO(timestamp),
    snapshotUrl: `https://web.archive.org/web/${timestamp}/${url}`,
  };
}

/** Up to `n` snapshots spread over time (one per year) for "when did each field appear". */
export async function snapshots(url, n = 5) {
  const q = new URLSearchParams({
    url, output: 'json', fl: 'timestamp', collapse: 'timestamp:4', limit: String(n),
  });
  const res = await outboundFetch('wayback', `${CDX}?${q}`);
  if (!res.ok) return [];
  const rows = await res.json();
  return rows.slice(1).map(([ts]) => ({
    date: toISO(ts),
    snapshotUrl: `https://web.archive.org/web/${ts}/${url}`,
  }));
}
