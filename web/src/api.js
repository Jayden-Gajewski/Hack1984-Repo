// All calls go to our own server (Vite proxies /api). The browser never calls Exa/Tavily directly.
async function req(method, path, body) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

export const api = {
  health: () => req('GET', '/health'),
  companies: () => req('GET', '/companies'),
  scan: (user) => req('POST', '/scan', user),
  breaches: (companyIds) => req('POST', '/breaches', { companyIds }),
  policies: (companyIds) => req('POST', '/policies', { companyIds }),
  rank: (payload) => req('POST', '/rank', payload),
  resolveBroker: (user, exposure) => req('POST', '/resolve/broker', { user, exposure }),
  resolveCompany: (user, companyId) => req('POST', '/resolve/company', { user, companyId }),
  inbox: () => req('GET', '/inbox/check'),
  outbound: () => req('GET', '/outbound'),
  clearOutbound: () => req('DELETE', '/outbound'),
};
