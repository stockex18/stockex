"use client";

/**
 * Scrolling announcement strip for the top of the home page.
 *
 * Two things here are easy to get wrong and are the reason this is a component
 * rather than a few divs:
 *
 * THE LINE IS RENDERED TWICE. The track slides by exactly -50%, so at the end
 * of a lap the second copy sits precisely where the first one started and the
 * loop restarts with no visible jump. One copy, or any translate other than
 * 50%, gives a gap or a stutter every lap.
 *
 * SPEED COMES FROM THE DIVISOR, NOT THE DURATION. The duration is derived from
 * the text length, so a long announcement and a short one scroll at the same
 * reading pace - the long one simply takes more seconds per lap. A fixed
 * duration instead makes short text crawl and long text race.
 *
 * Colours come from the app's theme tokens rather than being hard-coded, so
 * the strip follows light/dark with everything else.
 */

type Props = {
  /** Lines to scroll. Empty / blank-only renders nothing. */
  messages: string[];
  /** Reading speed in px/sec. ~70 is comfortable; raise for faster. */
  pxPerSec?: number;
  /** Separator drawn between messages. */
  separator?: string;
  className?: string;
};

/** Roughly the width of one character at the font size below. Only used to
 *  turn a character count into a duration - it does not need to be exact. */
const CHAR_PX = 5.5;

export function Ticker({
  messages,
  pxPerSec = 70,
  separator = "     •     ",
  className = "",
}: Props) {
  const lines = (messages ?? []).map((m) => (m ?? "").trim()).filter(Boolean);
  if (lines.length === 0) return null;

  const line = lines.join(separator);
  // One copy travels its own width per lap, so length sets the lap time and
  // the divisor sets the pace. Floored so a two-word ticker still moves.
  const seconds = Math.max(6, Math.round((line.length * CHAR_PX) / pxPerSec));

  return (
    // A yellow highlighter band with bold dark text (operator: "yellow colour
    // me bold me highlight me dikhe line"). Deliberately NOT theme tokens: a
    // highlight has to read as a highlight in light and dark alike, and black
    // on yellow does in both.
    <div
      className={`overflow-hidden border-y border-yellow-500/60 bg-yellow-300 py-2 ${className}`}
    >
      <style>{`
        @keyframes tk-marquee {
          from { transform: translateX(0); }
          to   { transform: translateX(-50%); }
        }
        .tk-track {
          display: flex;
          width: max-content;
          white-space: nowrap;
          animation: tk-marquee var(--tk-duration, 30s) linear infinite;
        }
        /* Motion sensitivity: hold the text still rather than hide it. */
        @media (prefers-reduced-motion: reduce) {
          .tk-track { animation: none; }
        }
      `}</style>
      <div
        className="tk-track text-[13px] font-bold tracking-wide text-black"
        style={{ ["--tk-duration" as string]: `${seconds}s` }}
      >
        <span className="px-4">{line}</span>
        {/* The duplicate is what makes -50% loop seamlessly. Hidden from
            screen readers so the text is not announced twice. */}
        <span className="px-4" aria-hidden>
          {line}
        </span>
      </div>
    </div>
  );
}
