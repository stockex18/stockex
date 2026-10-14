"use client";

import { useEffect } from "react";

const MINE = process.env.NEXT_PUBLIC_BUILD_ID;
const CHECK_EVERY_MS = 5 * 60_000;

function typing(): boolean {
  const el = document.activeElement as HTMLElement | null;
  return !!el && (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable);
}

/**
 * Reloads the panel when a newer build is live.
 *
 * The admin / broker panel is left open for days, often as an installed app.
 * A deploy does not reach it: the page keeps the JS it loaded, and signing in
 * again inside it does not reload anything — so a fixed bug stayed broken on
 * that one device ("still logging out" after the fix was live). This checks
 * the server's build on open, on return to the tab and every few minutes, and
 * reloads once it differs — never while the user is typing.
 */
export function BuildWatcher() {
  useEffect(() => {
    if (!MINE || process.env.NODE_ENV === "development") return;
    let stale = false;

    const reloadIfSafe = () => {
      if (stale && document.visibilityState === "visible" && !typing()) window.location.reload();
    };
    const check = async () => {
      try {
        const r = await fetch("/build-version", { cache: "no-store" });
        const { build } = await r.json();
        if (build && build !== MINE) {
          stale = true;
          reloadIfSafe();
        }
      } catch {
        // Offline / mid-deploy — try again on the next tick.
      }
    };
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      reloadIfSafe();
      void check();
    };

    document.addEventListener("visibilitychange", onVisible);
    const timer = window.setInterval(check, CHECK_EVERY_MS);
    void check();
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.clearInterval(timer);
    };
  }, []);

  return null;
}
