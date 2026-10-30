"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Play, X } from "lucide-react";

/* ═══ INTRODUCTION VIDEO — change it here ═══════════════════════════════════
 *
 * The video the home page "▶ Watch intro" button plays.
 * Current: "StockEx Introduction" on the StockEX YouTube channel —
 *          https://youtube.com/shorts/LHTC4Q3Qlqo
 *
 * To use a different video:
 *   1. On YouTube, open the video → Share → copy the link.
 *   2. Take the 11-character video id from the link:
 *        youtube.com/shorts/LHTC4Q3Qlqo?si=…   → LHTC4Q3Qlqo
 *        youtube.com/watch?v=LHTC4Q3Qlqo&t=…   → LHTC4Q3Qlqo
 *        youtu.be/LHTC4Q3Qlqo?si=…             → LHTC4Q3Qlqo
 *      (leave out `?si=…` and anything after it).
 *   3. Put that id between the quotes below, then commit and deploy.
 *
 * The video must be Public or Unlisted on YouTube, with embedding allowed.
 * The player is sized for a vertical Short (9:16); a wide video still plays,
 * with black bars above and below.
 * ═══════════════════════════════════════════════════════════════════════════ */
const INTRO_VIDEO_ID = "LHTC4Q3Qlqo";

/**
 * "▶ Watch intro" button for the home hero. Opens the video in a pop-up
 * player (vertical, sized for a Short) with sound. The YouTube player loads
 * only when the pop-up opens, from youtube-nocookie.com, so the home page
 * pays nothing for it otherwise.
 *
 * `onOpen` / `onClose` let the hero pause its background film and metro
 * sound so they don't play over the video.
 */
export function WatchIntro({ onOpen, onClose }: { onOpen?: () => void; onClose?: () => void }) {
  const videoId = INTRO_VIDEO_ID;
  const [open, setOpen] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);

  function close() {
    setOpen(false);
    onClose?.();
  }

  // While open: no page scroll behind the player, focus on the close button.
  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={(e) => {
          // The hero starts its metro sound on any click -- not this one.
          e.stopPropagation();
          onOpen?.();
          setOpen(true);
        }}
        className="flex h-11 items-center gap-2 rounded-full border border-white/20 bg-black/55 pl-3 pr-4 text-sm font-semibold text-white shadow-lg backdrop-blur-md transition-colors hover:bg-black/70"
      >
        <span className="grid size-7 place-items-center rounded-full bg-white text-black">
          <Play className="ml-0.5 size-3.5 fill-current" aria-hidden />
        </span>
        Watch intro
      </button>

      {open &&
        createPortal(
          <div
            role="dialog"
            aria-modal="true"
            aria-label="StockEx intro video"
            className="fixed inset-0 z-[100] flex items-center justify-center bg-black/85 p-4 backdrop-blur-sm"
            // Portals still bubble through the React tree to the hero, which
            // would start its metro sound -- stop events at the backdrop.
            onClick={(e) => {
              e.stopPropagation();
              close();
            }}
            // Esc is handled here, not on window: stopping the event (so the
            // hero's Enter/Space handler can't fire) also stops it reaching
            // a window listener. Once focus is inside the YouTube player its
            // keys never reach the page -- ✕ and clicking outside still close.
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === "Escape") close();
            }}
          >
            <button
              ref={closeRef}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                close();
              }}
              aria-label="Close video"
              className="absolute right-4 top-4 grid size-11 place-items-center rounded-full border border-white/20 bg-black/60 text-white transition-colors hover:bg-black/80"
            >
              <X className="size-5" aria-hidden />
            </button>
            {/* 9:16 for a Short: as tall as fits, never wider than the screen.
                80vh leaves room above it for the close button on phones. */}
            <div
              className="relative aspect-[9/16] overflow-hidden rounded-2xl bg-black shadow-2xl ring-1 ring-white/10"
              style={{ height: "min(80vh, calc((100vw - 2rem) * 16 / 9))" }}
              onClick={(e) => e.stopPropagation()}
            >
              <iframe
                src={`https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&rel=0&playsinline=1&modestbranding=1`}
                title="StockEx intro video"
                allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
                allowFullScreen
                className="absolute inset-0 h-full w-full border-0"
              />
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
