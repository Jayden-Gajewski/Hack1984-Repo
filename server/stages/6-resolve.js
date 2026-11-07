// OWNER: Search & extract
// Stage 6: find opt-out pages / privacy contacts and draft removal requests.
// Drafts are templates filled locally, so the user's details are never sent anywhere.
import brokers from '../data/brokers.json' with { type: 'json' };
import * as tavily from '../services/tavily.js';

export async function findOptOut(brokerName, brokerId) {
  const known = brokers.find((b) => b.id === brokerId);
  if (known?.optOutUrl) return { url: known.optOutUrl, source: 'known list' };
  const { results = [] } = await tavily.search(`${brokerName} opt out remove my listing`, { max_results: 3 });
  return { url: results[0]?.url ?? null, source: results[0] ? 'tavily search' : 'not found' };
}

export async function findPrivacyContact(company) {
  const { results = [] } = await tavily.search(`${company.name} privacy request delete my personal data contact`, {
    max_results: 3,
  });
  const text = results.map((r) => r.content).join(' ');
  const email = text.match(/privacy[\w.+-]*@[\w.-]+\.\w+/i)?.[0] ?? null;
  return { url: results[0]?.url ?? null, email };
}

export function draftBrokerOptOut({ user, exposure }) {
  return `Subject: Request to remove my personal information

To ${exposure.broker},

I am requesting that you remove my personal information from your website and stop selling or sharing it. The listing is here:
${exposure.url}

Name: ${user.name}
City: ${user.city}${user.state ? ', ' + user.state : ''}

Please confirm in writing once the listing has been removed and suppressed from future re-listing.

Thank you,
${user.name}`;
}

export function draftCompanyRequest({ user, company }) {
  return `Subject: Personal data deletion and do-not-sell request

To the ${company.name} privacy team,

Under applicable privacy law (including the CCPA/CPRA where it applies), I request that you:
1. Delete the personal information you hold about me.
2. Stop selling or sharing my personal information with third parties.
3. Tell me which third parties you have sold or shared my information with.

Name: ${user.name}
Account email: [fill in]

Please confirm receipt and completion within the legally required time frame.

Thank you,
${user.name}`;
}
