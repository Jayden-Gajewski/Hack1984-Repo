"use client";

import { useState } from "react";
import { api, type ScanResponse } from "@/lib/api";
import ExposureCard from "./components/ExposureCard";
import OutboundLog from "./components/OutboundLog";
import ScanForm from "./components/ScanForm";
import StatusLine from "./components/StatusLine";

export default function Home() {
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Demo fallback if the venue Wi-Fi fails: reload the last saved scan from local Postgres.
  async function loadLastScan() {
    setLoadError(null);
    try {
      setResult(await api.latestScan());
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Couldn't load the last scan");
    }
  }

  return (
    <main>
      <section>
        <h1>Hack1984</h1>
        <p className="muted">Find where your personal data is exposed. Analysis runs on this laptop.</p>
        <StatusLine />

        <ScanForm onResult={setResult} />
        <p className="row">
          <button type="button" className="secondary" onClick={loadLastScan}>
            Load last scan
          </button>
          {loadError && <span className="error">{loadError}</span>}
        </p>

        {result && (
          <div className="panel">
            <h2>
              {result.exposures.length} exposure{result.exposures.length === 1 ? "" : "s"} found
            </h2>
            {result.errors.map((err, i) => (
              <p key={i} className="muted">
                {err}
              </p>
            ))}
            {result.exposures.map((exposure) => (
              <ExposureCard key={exposure.id} exposure={exposure} />
            ))}
          </div>
        )}
      </section>

      <OutboundLog />
    </main>
  );
}
