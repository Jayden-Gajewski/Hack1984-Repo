"use client";

import { useEffect, useRef, useState } from "react";

// The 35-second ad, served from this site (public/demo), never a remote player. It's silent, so it
// plays muted once most of it is on screen and pauses when it scrolls away. With reduced motion it
// waits for a click. Every person and site in it is fictional sample data.

const SRC = "/demo/dossier-ad.mp4";
const POSTER = "/demo/dossier-ad-poster.jpg";

function clock(seconds: number) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function PlayIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      <path d="M3.5 2.2v9.6a.6.6 0 0 0 .9.5l7.6-4.8a.6.6 0 0 0 0-1L4.4 1.7a.6.6 0 0 0-.9.5Z" fill="currentColor" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      <rect x="3" y="2" width="3" height="10" rx="0.8" fill="currentColor" />
      <rect x="8" y="2" width="3" height="10" rx="0.8" fill="currentColor" />
    </svg>
  );
}

function ExpandIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <path d="M2 5V2h3M9 2h3v3M12 9v3H9M5 12H2V9" />
    </svg>
  );
}

export default function FilmPlayer() {
  const stage = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const bar = useRef<HTMLSpanElement>(null);
  const userPaused = useRef(false); // a pause the visitor chose; scrolling back doesn't undo it
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(35);

  // Play when most of the film is on screen, pause when it leaves. Not for reduced motion.
  useEffect(() => {
    const el = video.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    el.muted = true;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !userPaused.current) el.play().catch(() => {});
        else if (!entry.isIntersecting && !el.paused) el.pause();
      },
      { threshold: 0.6 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // A smooth progress line while playing: one transform per frame, no re-render.
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const tick = () => {
      const el = video.current;
      if (el && bar.current && el.duration) bar.current.style.transform = `scaleX(${el.currentTime / el.duration})`;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  function toggle() {
    const el = video.current;
    if (!el) return;
    if (el.paused) {
      userPaused.current = false;
      el.muted = true;
      el.play().catch(() => {});
    } else {
      userPaused.current = true;
      el.pause();
    }
  }

  function fullscreen() {
    const el = frame.current;
    if (!el) return;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else el.requestFullscreen?.().catch(() => {});
  }

  return (
    <div ref={stage} className="film-stage" data-playing={playing || undefined}>
      <div ref={frame} className="film-frame">
        <video
          ref={video}
          className="film-video"
          poster={POSTER}
          muted
          loop
          playsInline
          preload="none"
          aria-label="Dossier in 35 seconds, a silent demo with fictional sample data"
          aria-describedby="film-description"
          onClick={toggle}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || 35)}
        >
          <source src={SRC} type="video/mp4" />
        </video>

        {!playing && (
          <button type="button" className="film-play" onClick={toggle}>
            <PlayIcon />
            Play the demo <span className="film-play-time">{clock(duration)}</span>
          </button>
        )}
        <div className="film-controls" hidden={!playing}>
          <button type="button" className="film-icon-btn" onClick={toggle} aria-label="Pause the demo">
            <PauseIcon />
          </button>
          <span className="film-time" aria-hidden="true">
            {clock(time)} / {clock(duration)}
          </span>
          <button type="button" className="film-icon-btn film-expand" onClick={fullscreen} aria-label="Watch full screen">
            <ExpandIcon />
          </button>
        </div>
        <div className="film-progress" aria-hidden="true">
          <span ref={bar} />
        </div>
      </div>

      <p id="film-description" className="sr-only">
        A people-search listing types out a name, home address and phone number, and the same person turns up on
        site after site. Where did they get it? Dossier: Find it, by scanning people-search sites for your name and
        city. Trace it, by ranking the likely source with the evidence behind it: a breach notice, a privacy policy
        and an email alias all point to one sample company. Take it down, by drafting opt-out requests and re-scanning
        until the listings are removed. Every request is logged, including what the AI reads, and searches use your name and city
        only.
      </p>
    </div>
  );
}
