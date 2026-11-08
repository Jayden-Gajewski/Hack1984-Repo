"use client";

import { useEffect, useRef } from "react";
import type { Severity } from "@/lib/api";

export interface Blip {
  id: string;
  severity: Severity;
  label: string; // "AT&T, critical"
}

interface Props {
  blips: Blip[];
  scanning: boolean;
  label: string; // the scope's accessible summary, e.g. "2 critical and 3 high threats"
}

const SIZE = 200;
const C = SIZE / 2;
const R = 92;
// Closer to the centre is more urgent.
const RING: Record<Severity, number> = { critical: 0.3, high: 0.52, medium: 0.72, low: 0.88 };

// A stable spot for each threat: the angle comes from its id, so dots don't jump between renders.
function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}

function position(id: string, severity: Severity) {
  const h = hash(id);
  const angle = ((h % 360) * Math.PI) / 180;
  const radius = R * (RING[severity] + (((h >> 9) % 9) - 4) * 0.012);
  return { x: C + radius * Math.cos(angle), y: C + radius * Math.sin(angle) };
}

// The monitor's one signature move: a radar whose sweep turns slowly while watching and fast while
// a scan runs (same animation, sped up, so it never jumps). Still for reduced-motion users.
export default function RadarScope({ blips, scanning, label }: Props) {
  const sweep = useRef<HTMLDivElement>(null);
  const spin = useRef<Animation | null>(null);

  useEffect(() => {
    const el = sweep.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    spin.current = el.animate([{ transform: "rotate(0turn)" }, { transform: "rotate(1turn)" }], {
      duration: 9000,
      iterations: Infinity,
    });
    return () => spin.current?.cancel();
  }, []);

  useEffect(() => {
    spin.current?.updatePlaybackRate(scanning ? 4.5 : 1);
  }, [scanning]);

  return (
    <div className={scanning ? "radar scanning" : "radar"} role="img" aria-label={label}>
      <div ref={sweep} className="radar-sweep" aria-hidden="true" />
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} aria-hidden="true">
        {[0.3, 0.52, 0.72, 0.94].map((f) => (
          <circle key={f} className="radar-ring" cx={C} cy={C} r={R * f} />
        ))}
        <path className="radar-cross" d={`M${C} ${C - R}V${C + R}M${C - R} ${C}H${C + R}`} />
        {blips.map((b) => {
          const { x, y } = position(b.id, b.severity);
          return (
            <g key={b.id} className={`radar-blip sev-${b.severity}`}>
              <circle cx={x} cy={y} r={8} className="radar-halo" />
              <circle cx={x} cy={y} r={3.75} className="radar-dot">
                <title>{b.label}</title>
              </circle>
            </g>
          );
        })}
        <circle className="radar-core" cx={C} cy={C} r={3} />
      </svg>
    </div>
  );
}
