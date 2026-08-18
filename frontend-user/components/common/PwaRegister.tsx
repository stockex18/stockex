"use client";

import { useEffect } from "react";

/**
 * Mounts the service worker exactly once on first render of the app
 * shell. Also wires a one-shot listener that stashes the
 * `beforeinstallprompt` event onto `window.__mpInstallPrompt` so the
 * <InstallPwaButton> (or any other affordance) can trigger it later
 * without owning the listener itself.
 *
 * Deliberately a stand-alone client component with no UI so it can be
 * dropped into the root layout without forcing the whole tree to be
 * client-rendered.
 */
export function PwaRegister() {
  useEffect(() => {
    if (typeof window === "undefined") return;

    // ── Service worker registration ─────────────────────────────────
    if ("serviceWorker" in navigator) {
      const isDev = process.env.NODE_ENV === "development";

      if (isDev) {
        // In dev, tear the service worker down completely.
        //
        // Unregistering and clearing caches was already happening here,
        // but it was not enough on its own: if a SW from an earlier
        // production visit was CONTROLLING this page load, the HTML you
        // are looking at right now already came out of its cache. The
        // worker's navigation strategy is network-first with a 2 s
        // timeout, and a dev server frequently takes longer than that to
        // compile a route on first hit — so the cache wins the race and
        // paints the previous build. Cleaning up without reloading fixes
        // the NEXT navigation while leaving the current, stale page on
        // screen, which reads exactly like "my changes aren't showing".
        //
        // So: tear down, then reload ONCE if this document was served
        // under a controller. The sessionStorage flag makes that
        // strictly one-shot — without it, a reload that is itself served
        // from cache would loop forever.
        const RELOAD_FLAG = "mp.dev.sw-purged";
        const wasControlled = !!navigator.serviceWorker.controller;

        void (async () => {
          try {
            const regs = await navigator.serviceWorker.getRegistrations();
            await Promise.all(regs.map((r) => r.unregister()));
            if ("caches" in window) {
              const keys = await caches.keys();
              await Promise.all(keys.map((k) => caches.delete(k)));
            }
            if (
              wasControlled &&
              sessionStorage.getItem(RELOAD_FLAG) !== "1"
            ) {
              sessionStorage.setItem(RELOAD_FLAG, "1");
              window.location.reload();
            }
          } catch {
            /* Never let dev-only cleanup break the app shell. */
          }
        })();
      } else {
        const idle = (cb: () => void) =>
          ("requestIdleCallback" in window
            ? (window as any).requestIdleCallback(cb)
            : setTimeout(cb, 1000));
        idle(() => {
          navigator.serviceWorker
            .register("/sw.js", { scope: "/" })
            .catch(() => {});
        });
      }
    }

    // ── Install prompt capture ─────────────────────────────────────
    const onBeforeInstall = (e: Event) => {
      // Prevent the browser's mini-infobar — we surface our own
      // button.
      e.preventDefault();
      (window as any).__mpInstallPrompt = e;
      window.dispatchEvent(new CustomEvent("mp:install-available"));
    };
    const onInstalled = () => {
      (window as any).__mpInstallPrompt = null;
      window.dispatchEvent(new CustomEvent("mp:installed"));
    };
    window.addEventListener("beforeinstallprompt", onBeforeInstall);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstall);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  return null;
}
