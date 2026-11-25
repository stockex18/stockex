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
 * 50%, gives a gap or a stutter every lap. Each copy ends with a separator, so
 * the two are identical and the seam matches the gap between announcements.
 *
 * SPEED COMES FROM THE DIVISOR, NOT THE DURATION. The duration is derived from
 * the text length, so a long announcement and a short one scroll at the same
 * reading pace - the long one simply takes more seconds per lap. A fixed
 * duration instead makes short text crawl and long text race.
 *
 * The strip is a gradient band with white text in both light and dark: berry
 * → violet for female clients' pink app, deep gold for everyone else
 * (--ticker-from / --ticker-to in globals.css; white clears 5.9:1 on all).
 * The super admin can replace either colour for the whole strip, and give any
 * announcement its own colours: that announcement's stretch of the band is
 * painted in them as it scrolls past. Anything unset keeps the strip's look.
 * (Colour options added as per client requirement.)
 */

/** One announcement and its own colours (`#rrggbb`, `null` = the strip's). */
export type TickerLine = {
  text: string;
  bg?: string | null;
  text_color?: string | null;
};

type Props = {
  /** Announcements with their own colours. Takes precedence over `messages`. */
  items?: TickerLine[];
  /** Plain lines, all in the strip colours. Empty / blank-only renders nothing. */
  messages?: string[];
  /** Reading speed in px/sec. ~70 is comfortable; raise for faster. */
  pxPerSec?: number;
  /** Separator drawn between announcements. */
  separator?: string;
  /** Solid strip colour (`#rrggbb`). Unset keeps the default gradient. */
  bgColor?: string | null;
  /** Text colour (`#rrggbb`). Unset keeps white. */
  textColor?: string | null;
  className?: string;
};

/** Roughly the width of one character at the font size below. Only used to
 *  turn a character count into a duration - it does not need to be exact. */
const CHAR_PX = 5.5;

/** Characters' worth of width the padding + separator add per announcement. */
const GAP_CHARS = 8;

export function Ticker({
  items,
  messages,
  pxPerSec = 70,
  separator = "•",
  bgColor,
  textColor,
  className = "",
}: Props) {
  const lines: TickerLine[] = (items ?? (messages ?? []).map((text) => ({ text })))
    .map((l) => ({ ...l, text: (l?.text ?? "").trim() }))
    .filter((l) => l.text);
  if (lines.length === 0) return null;

  const chars = lines.reduce((n, l) => n + l.text.length + GAP_CHARS, 0);
  // One copy travels its own width per lap, so length sets the lap time and
  // the divisor sets the pace. Floored so a two-word ticker still moves.
  const seconds = Math.max(6, Math.round((chars * CHAR_PX) / pxPerSec));

  const copy = (hidden: boolean) => (
    <div className="flex" aria-hidden={hidden || undefined}>
      {lines.map((l, i) => (
        <span key={i} className="flex items-stretch">
          {/* The block fills the strip's height, so its colour reads as the
              strip's colour while this announcement scrolls past. */}
          <span
            className="px-4 py-1.5"
            style={{
              ...(l.bg ? { backgroundColor: l.bg } : {}),
              ...(l.text_color ? { color: l.text_color } : {}),
            }}
          >
            {l.text}
          </span>
          <span className="px-2 py-1.5">{separator}</span>
        </span>
      ))}
    </div>
  );

  return (
    <div
      className={`overflow-hidden ${
        bgColor
          ? ""
          : "bg-gradient-to-r from-[hsl(var(--ticker-from))] to-[hsl(var(--ticker-to))]"
      } ${className}`}
      style={bgColor ? { backgroundColor: bgColor } : undefined}
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
        className="tk-track text-[13px] font-bold tracking-wide text-white"
        style={{
          ["--tk-duration" as string]: `${seconds}s`,
          ...(textColor ? { color: textColor } : {}),
        }}
      >
        {copy(false)}
        {/* The duplicate is what makes -50% loop seamlessly. Hidden from
            screen readers so the text is not announced twice. */}
        {copy(true)}
      </div>
    </div>
  );
}
