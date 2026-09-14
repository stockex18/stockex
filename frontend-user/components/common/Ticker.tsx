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

const HIGHLIGHT = "mx-4 rounded bg-yellow-300 px-2 py-0.5 text-black";

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
    <div
      className={`overflow-hidden border-b border-border bg-primary/5 py-1.5 ${className}`}
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
        {/* The WORDS are highlighted, not the strip (operator: background
            stays as it was, the text in yellow highlight). Black on yellow
            reads as a highlighter in light and dark alike. Margin, not
            padding, spaces the two copies so the highlight hugs the text. */}
        <span className={HIGHLIGHT}>{line}</span>
        {/* The duplicate is what makes -50% loop seamlessly. Hidden from
            screen readers so the text is not announced twice. */}
        <span className={HIGHLIGHT} aria-hidden>
          {line}
        </span>
      </div>
    </div>
  );
}
