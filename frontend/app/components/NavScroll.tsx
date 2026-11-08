"use client";

import { useEffect } from "react";

// Marks the sticky nav once the page has scrolled, so it gains a backdrop only when content
// passes under it.
export default function NavScroll() {
  useEffect(() => {
    const nav = document.querySelector<HTMLElement>(".nav-bar");
    const onScroll = () => nav?.toggleAttribute("data-scrolled", window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return null;
}
