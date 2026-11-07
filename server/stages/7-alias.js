// OWNER: Local LLM & ranking
// Stage 7: per-company email aliases + local inbox check. Runs entirely locally, no search.
import { randomBytes } from 'node:crypto';
import inbox from '../data/mock-inbox.json' with { type: 'json' };

const ALIAS_DOMAIN = 'alias.local';

export function generateAlias(companyName) {
  const slug = companyName.toLowerCase().replace(/[^a-z0-9]+/g, '').slice(0, 12);
  return `${slug}-${randomBytes(2).toString('hex')}@${ALIAS_DOMAIN}`;
}

const domainOf = (addr) => addr.split('@')[1]?.toLowerCase() ?? '';

/** Mail to a company's alias from a sender outside that company = Proven leak by that company. */
export function checkInbox(data = inbox) {
  const byAlias = new Map(data.aliases.map((a) => [a.alias, a]));
  const matches = [];
  for (const msg of data.messages) {
    const alias = byAlias.get(msg.to);
    if (!alias) continue;
    const from = domainOf(msg.from);
    const fromCompany = alias.companyDomains.some((d) => from === d || from.endsWith('.' + d));
    if (!fromCompany) {
      matches.push({
        tier: 'Proven',
        company: alias.company,
        alias: alias.alias,
        fromDomain: from,
        subject: msg.subject,
        date: msg.date,
      });
    }
  }
  return { aliases: data.aliases, matches };
}
