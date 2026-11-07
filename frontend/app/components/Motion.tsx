"use client";

import { useEffect } from "react";

// One observer for the landing page: reveals each [data-reveal] block once as it scrolls into
// view, and marks the nav after the page scrolls. Until this runs, and with reduced motion,
// everything is simply visible.
export default function Motion() {
  useEffect(() => {
    const root = document.querySelector<HTMLElement>(".site");
    const nav = document.querySelector<HTMLElement>(".nav-bar");
    const onScroll = () => nav?.toggleAttribute("data-scrolled", window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

    let observer: IntersectionObserver | undefined;
    if (root && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      // Blocks already on screen stay put; only what's below the fold waits to be revealed.
      const blocks = Array.from(root.querySelectorAll("[data-reveal]"));
      for (const el of blocks) {
        if (el.getBoundingClientRect().top < window.innerHeight) el.classList.add("is-in");
      }
      root.classList.add("motion-ready");
      observer = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            entry.target.classList.add("is-in");
            observer?.unobserve(entry.target);
          }
        },
        { rootMargin: "0px 0px -12% 0px" },
      );
      blocks.filter((el) => !el.classList.contains("is-in")).forEach((el) => observer?.observe(el));
    }

    return () => {
      window.removeEventListener("scroll", onScroll);
      observer?.disconnect();
    };
  }, []);

  return null;
}
