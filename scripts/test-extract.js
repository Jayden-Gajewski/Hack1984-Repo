// FIRST-HOUR EXPERIMENT: does Tavily Extract work on broker pages?
// Usage: npm run test:extract -- "Jane Doe" "Boston" "MA"
// Only run this on yourself or a teammate who agreed to it.
// Results are written to scripts/output/ (gitignored, it may contain real personal data).
import 'dotenv/config';
import { mkdirSync, writeFileSync } from 'node:fs';
import brokers from '../server/data/brokers.json' with { type: 'json' };
import * as tavily from '../server/services/tavily.js';
import { getOutboundLog } from '../server/lib/outbound.js';

const [name, city, state = ''] = process.argv.slice(2);
if (!name || !city) {
  console.error('Usage: npm run test:extract -- "First Last" "City" "ST"');
  process.exit(1);
}

const report = [];
for (const b of brokers) {
  const row = { broker: b.name, url: null, search: 'no result', extract: '-', chars: 0, snippetChars: 0 };
  try {
    const { results = [] } = await tavily.search(`"${name}" ${city} ${state}`.trim(), {
      include_domains: [b.domain],
      max_results: 3,
    });
    const hit = results[0];
    if (hit) {
      row.url = hit.url;
      row.search = 'found';
      row.snippetChars = hit.content?.length ?? 0;
      const ex = await tavily.extract(hit.url);
      const text = ex.results?.[0]?.raw_content ?? '';
      row.chars = text.length;
      const mentionsName = text.toLowerCase().includes(name.toLowerCase().split(' ').at(-1));
      row.extract = !text ? 'BLOCKED' : text.length < 500 || !mentionsName ? 'thin' : 'OK';
    }
  } catch (err) {
    row.search = `error: ${err.message.slice(0, 60)}`;
  }
  report.push(row);
  console.log(`${b.name.padEnd(18)} ${row.search.padEnd(10)} extract=${row.extract.padEnd(8)} chars=${row.chars}`);
}

mkdirSync('scripts/output', { recursive: true });
writeFileSync('scripts/output/extract-report.json', JSON.stringify({ report, outbound: getOutboundLog() }, null, 2));
console.log('\nFull report: scripts/output/extract-report.json');
console.log('Decision: brokers marked OK use Extract; BLOCKED/thin fall back to search snippets.');
