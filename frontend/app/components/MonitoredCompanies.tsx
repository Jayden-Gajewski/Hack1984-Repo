"use client";

import { useEffect, useState } from "react";
import { api, type Company, type MonitorConfig, type MonitoredCompany } from "@/lib/api";
import { localTime, timeAgo } from "@/lib/display";
import CompanyPicker from "./CompanyPicker";

interface Props {
  monitored: MonitoredCompany[];
  config: MonitorConfig;
  refreshing: boolean;
  onChanged: () => Promise<void>;
  onSearchNews: (companyId: string) => Promise<void>;
}

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

// The companies you have accounts with. HIBP's breach list is downloaded whole and matched on
// this laptop, so HIBP never learns which companies these are; news searches send the name only.
export default function MonitoredCompanies({ monitored, config, refreshing, onChanged, onSearchNews }: Props) {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.companies().then(setCompanies, (err) => setError(message(err)));
  }, []);

  async function run(work: () => Promise<unknown>) {
    setError(null);
    try {
      await work();
      await onChanged();
    } catch (err) {
      setError(message(err));
    }
  }

  const add = (id: string) => {
    const company = companies.find((c) => c.id === id);
    if (company) run(() => api.monitor.addCompany(company.name));
  };
  const remove = (id: string) => run(() => api.monitor.removeCompany(id));
  async function create(name: string): Promise<Company> {
    const company = await api.addCompany(name); // same website lookup as the account picker
    setCompanies((prev) => (prev.some((c) => c.id === company.id) ? prev : [...prev, company]));
    await run(() => api.monitor.addCompany(company.name));
    return company;
  }

  const newsReady = config.news_search && config.local_llm;

  return (
    <section className="section" aria-labelledby="companies-h">
      <div className="task-panel">
        <h2 id="companies-h">Companies you have accounts with</h2>
        <p className="muted">
          Have I Been Pwned&apos;s whole breach list is downloaded and matched on this laptop, so it never learns which
          companies you use. Adding a company that isn&apos;t listed looks up its website with one Exa search, and a
          news search sends the company name; both send the name only. Never a password.
        </p>
        <CompanyPicker
          companies={companies}
          selected={monitored.map((c) => c.id)}
          onAdd={add}
          onRemove={remove}
          onCreate={create}
        />
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>

      {monitored.length > 0 && (
        <ul className="watch-list" aria-label="Monitored companies">
          {monitored.map((c) => (
            <li key={c.id}>
              <div className="watch-main">
                <strong>{c.name}</strong>{" "}
                <span className="muted small">{c.domains[0]}</span>
                <p className="muted small">
                  <span title={localTime(c.last_checked)}>Breach list checked {timeAgo(c.last_checked)}</span>
                  {". "}
                  <span title={localTime(c.last_news_check)}>News searched {timeAgo(c.last_news_check)}</span>
                  {". "}
                  {c.incidents === 0 ? "No incidents" : `${c.incidents} incident${c.incidents === 1 ? "" : "s"}`}.
                </p>
                {c.messages.map((m) => (
                  <p key={m} className="small notice">
                    {m}
                  </p>
                ))}
              </div>
              <div className="watch-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onSearchNews(c.id)}
                  disabled={refreshing || !newsReady}
                  title={newsReady ? undefined : "Needs a Tavily or Exa key and the local LLM"}
                >
                  Search news &amp; notices
                </button>
                <button type="button" className="quiet" onClick={() => remove(c.id)}>
                  Stop monitoring
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {monitored.length > 0 && (
        <p className="muted small mt">
          News and official-notice searches use Tavily and Exa credits and the local LLM, about a minute per company.
          {!newsReady && " They need a Tavily or Exa key in .env and Ollama running."}
        </p>
      )}
    </section>
  );
}
