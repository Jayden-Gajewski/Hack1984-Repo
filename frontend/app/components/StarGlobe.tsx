"use client";

import { useEffect, useRef } from "react";

// Illustration for the empty Exposures area: a slowly turning globe of connected stars, drawn on a canvas.
// No dependencies and no network. Colors come from the theme tokens in globals.css.
// Decorative only: aria-hidden, no pointer events, a still frame under reduced motion.

const STAR_COUNT = 170;
const LINKS_PER_STAR = 3;
const SPIN = (2 * Math.PI) / 300; // one turn every 5 minutes
const TILT = 0.38; // radians the axis leans toward the viewer

type Vec = [number, number, number];

function fibonacciSphere(n: number): Vec[] {
  const pts: Vec[] = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    // A little jitter so it reads as stars, not a mesh.
    const theta = golden * i + Math.sin(i * 12.9898) * 0.35;
    pts.push([Math.cos(theta) * r, y, Math.sin(theta) * r]);
  }
  return pts;
}

function nearestLinks(pts: Vec[], k: number): [number, number][] {
  const seen = new Set<string>();
  const links: [number, number][] = [];
  pts.forEach((a, i) => {
    pts
      .map((b, j) => ({ j, d: (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2 }))
      .filter((o) => o.j !== i)
      .sort((x, y) => x.d - y.d)
      .slice(0, k)
      .forEach(({ j }) => {
        const key = i < j ? `${i}-${j}` : `${j}-${i}`;
        if (!seen.has(key)) {
          seen.add(key);
          links.push([i, j]);
        }
      });
  });
  return links;
}

function rgb(color: string, fallback: string): string {
  const hex = color.trim().replace("#", "");
  if (!/^[0-9a-f]{6}$/i.test(hex)) return fallback;
  return `${parseInt(hex.slice(0, 2), 16)}, ${parseInt(hex.slice(2, 4), 16)}, ${parseInt(hex.slice(4, 6), 16)}`;
}

export default function StarGlobe() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const stars = fibonacciSphere(STAR_COUNT);
    const links = nearestLinks(stars, LINKS_PER_STAR);
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const scheme = window.matchMedia("(prefers-color-scheme: dark)");

    let width = 0;
    let height = 0;
    let starColor = "20, 26, 34";
    let lineColor = "35, 64, 142";
    let angle = 0.6;
    let last = 0;
    let frame = 0;

    function readColors() {
      const css = getComputedStyle(document.documentElement);
      starColor = rgb(css.getPropertyValue("--text"), starColor);
      lineColor = rgb(css.getPropertyValue("--accent"), lineColor);
    }

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = canvas!.clientWidth;
      height = canvas!.clientHeight;
      canvas!.width = Math.round(width * dpr);
      canvas!.height = Math.round(height * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function draw() {
      // Centered in its box, with room for the nearest stars to stay inside the edges.
      const radius = Math.min(width, height) * 0.44;
      const cx = width / 2;
      const cy = height / 2;
      const cosA = Math.cos(angle);
      const sinA = Math.sin(angle);
      const cosT = Math.cos(TILT);
      const sinT = Math.sin(TILT);

      const projected = stars.map(([x, y, z]) => {
        const x1 = x * cosA + z * sinA; // spin around the axis
        const z1 = -x * sinA + z * cosA;
        const y2 = y * cosT - z1 * sinT; // lean the axis
        const z2 = y * sinT + z1 * cosT;
        return { x: cx + x1 * radius, y: cy - y2 * radius, depth: (z2 + 1) / 2 };
      });

      ctx!.clearRect(0, 0, width, height);
      ctx!.lineWidth = 1;
      for (const [i, j] of links) {
        const a = projected[i];
        const b = projected[j];
        const depth = (a.depth + b.depth) / 2;
        ctx!.strokeStyle = `rgba(${lineColor}, ${(0.05 + depth * 0.3).toFixed(3)})`;
        ctx!.beginPath();
        ctx!.moveTo(a.x, a.y);
        ctx!.lineTo(b.x, b.y);
        ctx!.stroke();
      }
      for (const p of projected) {
        ctx!.fillStyle = `rgba(${starColor}, ${(0.15 + p.depth * 0.6).toFixed(3)})`;
        ctx!.beginPath();
        ctx!.arc(p.x, p.y, 0.8 + p.depth * 1.6, 0, Math.PI * 2);
        ctx!.fill();
      }
    }

    function tick(now: number) {
      if (last) angle += (SPIN * Math.min(now - last, 100)) / 1000;
      last = now;
      draw();
      frame = requestAnimationFrame(tick);
    }

    function start() {
      cancelAnimationFrame(frame);
      last = 0;
      if (motion.matches || document.hidden) draw();
      else frame = requestAnimationFrame(tick);
    }

    function onTheme() {
      readColors();
      draw();
    }

    function onResize() {
      resize();
      draw();
    }

    readColors();
    resize();
    start();
    canvas.dataset.ready = "true";

    const observer = new ResizeObserver(onResize);
    observer.observe(canvas);
    document.addEventListener("visibilitychange", start);
    motion.addEventListener("change", start);
    scheme.addEventListener("change", onTheme);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      document.removeEventListener("visibilitychange", start);
      motion.removeEventListener("change", start);
      scheme.removeEventListener("change", onTheme);
    };
  }, []);

  return <canvas ref={canvasRef} className="star-globe" aria-hidden="true" />;
}
