// OWNER: Evidence
// Stage 2: "public by" date for each exposure. Every date is labeled with its source.
import { earliestSnapshot } from '../services/wayback.js';

export async function dateExposures(exposures) {
  return Promise.all(
    exposures.map(async (e) => {
      let publicBy = { date: null, source: 'unknown', url: null };
      try {
        const snap = await earliestSnapshot(e.url);
        if (snap) publicBy = { date: snap.date, source: 'Wayback Machine earliest snapshot', url: snap.snapshotUrl };
      } catch (err) {
        console.warn('[stage2] wayback failed for', e.url, err.message);
      }
      if (!publicBy.date && e.publishedDate) {
        publicBy = { date: e.publishedDate.slice(0, 10), source: 'search API published date', url: null };
      }
      // TODO(evidence): use wayback.snapshots() to find when each field first appears.
      return { ...e, publicBy };
    }),
  );
}
