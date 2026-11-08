"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

// The 35-second ad, served from this site (public/demo), never a remote player. It's silent, so it
// plays muted once most of it is on screen and pauses when it scrolls away. With reduced motion it
// waits for a click. Once it has started, a control bar stays on it: play and pause, a timeline to
// drag back and forth, the time, and full screen. After the visitor pauses it, scrolling never starts
// it again on its own. Every person and site in it is fictional sample data.

const SRC = "/demo/dossier-ad.mp4";
const POSTER = "/demo/dossier-ad-poster.jpg";
const SKIP_SECONDS = 5;

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
  const frame = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const scrub = useRef<HTMLInputElement>(null);
  const userPaused = useRef(false); // a pause the visitor chose; scrolling back doesn't undo it
  const resumeAfterDrag = useRef<boolean | null>(null); // while dragging the timeline: was it playing?
  const [started, setStarted] = useState(false);
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

  // Keep the timeline on the playhead. While playing, once per frame with no re-render, so the thumb
  // glides instead of jumping four times a second.
  function paint() {
    const el = video.current;
    const input = scrub.current;
    if (!el || !input || resumeAfterDrag.current !== null) return;
    const total = el.duration || duration;
    input.value = String(el.currentTime);
    input.style.setProperty("--progress", String(total ? el.currentTime / total : 0));
  }

  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const tick = () => {
      paint();
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]); // eslint-disable-line react-hooks/exhaustive-deps -- paint reads refs only

  function play() {
    const el = video.current;
    if (!el) return;
    userPaused.current = false;
    el.muted = true;
    el.play().catch(() => {});
  }

  function toggle() {
    const el = video.current;
    if (!el) return;
    if (el.paused) {
      play();
    } else {
      userPaused.current = true;
      el.pause();
    }
  }

  function seek(seconds: number) {
    const el = video.current;
    if (!el) return;
    const total = el.duration || duration;
    el.currentTime = Math.min(Math.max(seconds, 0), Math.max(total - 0.05, 0));
    setTime(el.currentTime);
    const input = scrub.current;
    if (input) {
      input.value = String(el.currentTime);
      input.style.setProperty("--progress", String(total ? el.currentTime / total : 0));
    }
  }

  // Dragging the timeline holds the film still, then picks up where it was let go.
  function startDrag(event: PointerEvent<HTMLInputElement>) {
    if (event.button !== 0) return;
    const el = video.current;
    resumeAfterDrag.current = !!el && !el.paused;
    el?.pause();
  }

  function endDrag() {
    const resume = resumeAfterDrag.current;
    resumeAfterDrag.current = null;
    if (resume) video.current?.play().catch(() => {});
  }

  // Keys anywhere on the player: Space or K plays and pauses, the arrows skip, Home and End jump.
  function onKey(event: KeyboardEvent<HTMLDivElement>) {
    const el = video.current;
    if (!el || event.altKey || event.ctrlKey || event.metaKey) return;
    const onButton = event.target instanceof HTMLButtonElement; // a focused button already answers Space
    switch (event.key) {
      case " ":
      case "k":
      case "K":
        if (onButton && event.key === " ") return;
        toggle();
        break;
      case "ArrowLeft":
        seek(el.currentTime - SKIP_SECONDS);
        break;
      case "ArrowRight":
        seek(el.currentTime + SKIP_SECONDS);
        break;
      case "Home":
        seek(0);
        break;
      case "End":
        seek(el.duration || duration);
        break;
      default:
        return;
    }
    event.preventDefault();
  }

  function fullscreen() {
    const el = frame.current;
    if (!el) return;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else el.requestFullscreen?.().catch(() => {});
  }

  return (
    <div className="film-stage" data-playing={playing || undefined}>
      <div ref={frame} className="film-frame" onKeyDown={onKey}>
        <video
          ref={video}
          className="film-video"
          poster={POSTER}
          muted
          loop
          playsInline
          preload="none"
          tabIndex={0} // clicking it focuses the player, so the keys work straight away
          aria-label="Dossier in 35 seconds, a silent demo with fictional sample data"
          aria-describedby="film-description"
          onClick={toggle}
          onPlay={() => {
            setStarted(true);
            setPlaying(true);
          }}
          onPause={() => setPlaying(false)}
          onTimeUpdate={(e) => {
            setTime(e.currentTarget.currentTime);
            if (e.currentTarget.paused) paint();
          }}
          onSeeked={paint}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || 35)}
        >
          <source src={SRC} type="video/mp4" />
        </video>

        {!started && (
          <button type="button" className="film-play" onClick={play}>
            <PlayIcon />
            Play the demo <span className="film-play-time">{clock(duration)}</span>
          </button>
        )}
        <div className="film-controls" hidden={!started} data-paused={!playing || undefined}>
          <button
            type="button"
            className="film-icon-btn"
            onClick={toggle}
            aria-label={playing ? "Pause the demo" : "Play the demo"}
          >
            {playing ? <PauseIcon /> : <PlayIcon />}
          </button>
          <input
            ref={scrub}
            type="range"
            className="film-scrub"
            min={0}
            max={duration}
            step="any"
            defaultValue={0}
            aria-label="Seek"
            aria-valuetext={`${clock(time)} of ${clock(duration)}`}
            onPointerDown={startDrag}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onLostPointerCapture={endDrag}
            onInput={(e) => {
              const el = video.current;
              const seconds = Number(e.currentTarget.value);
              if (!el) return;
              el.currentTime = seconds;
              setTime(seconds);
              e.currentTarget.style.setProperty("--progress", String(duration ? seconds / duration : 0));
            }}
          />
          <span className="film-time" aria-hidden="true">
            {clock(time)} / {clock(duration)}
          </span>
          <button type="button" className="film-icon-btn" onClick={fullscreen} aria-label="Watch full screen">
            <ExpandIcon />
          </button>
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
