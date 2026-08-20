/* StockEx marketing UI primitives.
 *
 * Thin, presentational building blocks that read straight from the locked
 * `--mp-*` design tokens (registered in tailwind.config as the `mp` colour
 * family + `font-display` / `font-numeric`). Everything here is a server
 * component — no client JS — so marketing pages stay fast and SSR-clean.
 *
 * Rules from the design system that live here:
 *   • Buttons: 12px radius, firm (not pill). Primary = solid green + white
 *     text; Secondary = ghost/outline.
 *   • Cards: 16px radius, 1px --mp-border, subtle inner glow on hover, NO
 *     heavy drop shadows.
 *   • Section padding: 96px desktop / 56px mobile.
 *   • Content cap 1200px.
 */
import Link from "next/link";
import NextImage from "next/image";
import { Image as ImageIcon } from "lucide-react";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cn } from "@/lib/utils";

/* ── Layout ─────────────────────────────────────────────────────────── */

export function MpContainer({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("mx-auto w-full max-w-mp-content px-5 sm:px-8", className)}>
      {children}
    </div>
  );
}

/** A full-bleed section with the design-system vertical rhythm. Pass
 *  `dark` to flip the section to the dark surface palette. */
export function MpSection({
  id,
  dark = false,
  light = false,
  className,
  containerClassName,
  children,
}: {
  id?: string;
  dark?: boolean;
  /** Paint this band on the LIGHT surface of the palette. The mirror of
   *  `dark`, and the same contract: it only re-points the `--mp-*` tokens,
   *  so the children keep using `bg-mp-surface` / `text-mp-text-mut` and
   *  don't need to know which band they are on.
   *
   *  Unlike `dark` it adds no `bg-*` utility — `.mp-light` declares its own
   *  background in globals.css. These bands replaced a translucent
   *  `bg-mp-surface-2/60`, and leaving a bg utility here would let twMerge
   *  keep the caller's translucent one and wash the band out over navy. */
  light?: boolean;
  className?: string;
  containerClassName?: string;
  children: ReactNode;
}) {
  return (
    <section
      id={id}
      className={cn(
        "py-14 sm:py-24",
        dark && "mp-dark bg-mp-bg text-mp-text",
        light && "mp-light",
        className,
      )}
    >
      <MpContainer className={containerClassName}>{children}</MpContainer>
    </section>
  );
}

/* ── Type ───────────────────────────────────────────────────────────── */

export function MpEyebrow({
  children,
  className,
  plain = false,
}: {
  children: ReactNode;
  className?: string;
  /** When true, render the original underline-style eyebrow (used on the
   *  homepage so it stays unchanged). Default is the solid green pill tag. */
  plain?: boolean;
}) {
  if (plain) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-mp-primary",
          className,
        )}
      >
        <span className="h-px w-6 bg-mp-primary/50" aria-hidden />
        {children}
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-1.5 rounded-full bg-mp-primary px-3.5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-white shadow-sm shadow-mp-primary/20",
        className,
      )}
    >
      <span className="size-1.5 rounded-full bg-mp-accent" aria-hidden />
      {children}
    </span>
  );
}

/** Standard section header: eyebrow → title → optional lead paragraph. */
export function MpHeading({
  eyebrow,
  title,
  lead,
  align = "left",
  className,
  plain = false,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  lead?: ReactNode;
  align?: "left" | "center";
  className?: string;
  /** Pass through to MpEyebrow — homepage uses `plain` to keep its look. */
  plain?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-4",
        align === "center" && "items-center text-center",
        className,
      )}
    >
      {eyebrow ? <MpEyebrow plain={plain}>{eyebrow}</MpEyebrow> : null}
      <h2 className="font-display text-3xl font-bold leading-[1.1] text-mp-text sm:text-4xl">
        {title}
      </h2>
      {lead ? (
        <p
          className={cn(
            "max-w-mp-prose text-base leading-[1.65] text-mp-text-mut",
            align === "center" && "mx-auto",
          )}
        >
          {lead}
        </p>
      ) : null}
    </div>
  );
}

/** Dark page header band used at the top of inner marketing pages.
 *  eyebrow → title → lead, with optional CTA buttons passed as children. */
export function MpPageHero({
  eyebrow,
  title,
  lead,
  children,
  media,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  lead?: ReactNode;
  children?: ReactNode;
  /** Artwork for the right column. Omit for the dashed placeholder;
   *  pass `null` to run the hero full-width with no visual at all. */
  media?: ReactNode | null;
}) {
  return (
    <section className="mp-dark relative overflow-hidden bg-mp-bg text-mp-text">
      <div className="mp-grid-lines absolute inset-0 opacity-30" aria-hidden />
      <div
        className="absolute -top-32 left-1/2 h-[320px] w-[680px] -translate-x-1/2 rounded-full bg-mp-primary/15 blur-[130px]"
        aria-hidden
      />
      <MpContainer className="relative pb-16 pt-28 sm:pb-20 sm:pt-32">
        {/* Two columns from lg up: copy left, visual right — the reference
            hero shape. Below lg the image drops away entirely rather than
            stacking, so a phone gets the message without scrolling past a
            large empty box first. */}
        <div className="grid items-center gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
          <div className="flex max-w-3xl flex-col gap-5">
            {eyebrow ? <MpEyebrow>{eyebrow}</MpEyebrow> : null}
            <h1 className="font-display text-4xl font-semibold leading-[1.06] tracking-[-0.03em] text-mp-text sm:text-5xl">
              {title}
            </h1>
            {lead ? (
              <p className="max-w-2xl text-lg leading-[1.65] text-mp-text-mut">
                {lead}
              </p>
            ) : null}
            {children ? (
              <div className="mt-2 flex flex-col gap-3 sm:flex-row">{children}</div>
            ) : null}
          </div>

          {media === null ? null : (
            <div className="hidden lg:block">
              {media ?? <MpImagePlaceholder label="Hero image" ratio="4/3" />}
            </div>
          )}
        </div>
      </MpContainer>
    </section>
  );
}

/** Prose paragraph at the design-system reading measure. */
export function MpProse({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <p
      className={cn(
        "max-w-mp-prose text-base leading-[1.65] text-mp-text-mut",
        className,
      )}
    >
      {children}
    </p>
  );
}

/* ── Card ───────────────────────────────────────────────────────────── */

export function MpCard({
  className,
  hover = true,
  children,
}: {
  className?: string;
  hover?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-mp-border bg-mp-surface p-6",
        hover && "mp-card-glow",
        className,
      )}
    >
      {children}
    </div>
  );
}

/* ── Stat grid ──────────────────────────────────────────────────────── */

// Reference-style big-number stat cards in a mixed green / dark / accent /
// white palette. Cards cycle through tones for visual rhythm.
//
// The accent tile carries WHITE type. It used to be dark-on-lime, which was
// right while the accent was a pale colour; the accent is now #003E85, and
// dark text on it measures 1.48:1 — invisible.
const STAT_TONES = [
  { box: "bg-mp-primary", num: "text-white", label: "text-white", sub: "text-white/70" },
  { box: "bg-[#0c2a1e]", num: "text-white", label: "text-white", sub: "text-white/60" },
  { box: "bg-mp-accent", num: "text-white", label: "text-white", sub: "text-white/70" },
  {
    box: "border border-mp-border bg-mp-surface",
    num: "text-mp-primary",
    label: "text-mp-text",
    sub: "text-mp-text-mut",
  },
] as const;

export function MpStatGrid({
  items,
}: {
  items: { value: string; label: string; sub?: string }[];
}) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:gap-5 lg:grid-cols-4">
      {items.map((s, i) => {
        const t = STAT_TONES[i % STAT_TONES.length];
        return (
          <div
            key={s.label}
            className={cn(
              "flex min-h-[150px] flex-col justify-between rounded-3xl p-6 transition-transform duration-300 hover:-translate-y-1",
              t.box,
            )}
          >
            <span className={cn("mp-num font-display text-4xl font-bold leading-none", t.num)}>
              {s.value}
            </span>
            <div className="mt-4">
              <div className={cn("text-sm font-semibold", t.label)}>{s.label}</div>
              {s.sub ? <div className={cn("mt-1 text-xs", t.sub)}>{s.sub}</div> : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Button ─────────────────────────────────────────────────────────── */

type MpButtonVariant = "primary" | "secondary" | "ghost";
type MpButtonSize = "md" | "lg";

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-2 rounded-xl font-semibold transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-60";

const BUTTON_VARIANTS: Record<MpButtonVariant, string> = {
  primary:
    "bg-mp-primary text-white shadow-sm hover:bg-mp-primary-2 hover:shadow-md hover:shadow-mp-primary/20",
  secondary:
    "border border-mp-border bg-transparent text-mp-text hover:border-mp-primary/60 hover:text-mp-primary",
  ghost: "bg-transparent text-mp-text-mut hover:text-mp-text",
};

const BUTTON_SIZES: Record<MpButtonSize, string> = {
  md: "h-11 px-5 text-sm",
  lg: "h-12 px-6 text-[15px]",
};

type MpButtonProps = {
  variant?: MpButtonVariant;
  size?: MpButtonSize;
  href?: string;
  className?: string;
  children: ReactNode;
} & Omit<ComponentPropsWithoutRef<"button">, "ref">;

export function MpButton({
  variant = "primary",
  size = "md",
  href,
  className,
  children,
  ...rest
}: MpButtonProps) {
  const classes = cn(
    BUTTON_BASE,
    BUTTON_VARIANTS[variant],
    BUTTON_SIZES[size],
    className,
  );
  if (href) {
    return (
      <Link href={href} className={classes}>
        {children}
      </Link>
    );
  }
  return (
    <button className={classes} {...rest}>
      {children}
    </button>
  );
}

/* ── Link card ──────────────────────────────────────────────────────── */

/**
 * A whole-card link used by the three hub pages (Trading, Platforms,
 * Accounts) to fan out to their detail pages.
 *
 * Lives here rather than in each page so the hubs can't drift apart —
 * they are the same object repeated three times, and the previous
 * duplicate-nav episode is a good argument for not copy-pasting shared
 * chrome. `facts` renders as a small definition row under the body, which
 * is what makes these read as spec cards instead of link lists.
 */
export function MpLinkCard({
  href,
  iconNode,
  title,
  body,
  facts,
  cta = "Learn more",
  featured = false,
}: {
  href: string;
  /* A rendered ELEMENT (`<Wallet className="size-5" />`), not a component
     reference. lucide-react ships as a client module, so handing the bare
     component to this Server Component fails with "Unsupported Server
     Component type: undefined" — React has only a client reference at that
     point, not something it can invoke here. Rendering it at the call site
     keeps the icon on the caller's side of the boundary. */
  iconNode?: ReactNode;
  title: ReactNode;
  body: ReactNode;
  facts?: { label: string; value: string }[];
  cta?: string;
  featured?: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "mp-card-glow group flex flex-col rounded-2xl border bg-mp-surface p-6",
        featured ? "border-mp-primary/45" : "border-mp-border",
      )}
    >
      {iconNode ? (
        <span className="mb-5 grid size-11 place-items-center rounded-xl bg-mp-primary/10 text-mp-primary">
          {iconNode}
        </span>
      ) : null}

      <h3 className="font-display text-lg font-semibold text-mp-text">{title}</h3>
      <p className="mt-2.5 text-sm leading-[1.6] text-mp-text-mut">{body}</p>

      {facts?.length ? (
        <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-mp-border pt-5">
          {facts.map((f) => (
            <div key={f.label}>
              <dt className="text-[11px] uppercase tracking-wide text-mp-text-mut">
                {f.label}
              </dt>
              <dd className="mp-num mt-0.5 text-sm font-semibold text-mp-text">
                {f.value}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      <span className="mt-6 inline-flex items-center gap-1.5 text-sm font-semibold text-mp-primary">
        {cta}
        <span aria-hidden className="transition-transform duration-200 group-hover:translate-x-0.5">
          →
        </span>
      </span>
    </Link>
  );
}

/* ── Image placeholder ──────────────────────────────────────────────── */

/**
 * An empty image slot: a soft dashed box with an icon chip and a caption,
 * so a page with no artwork yet still reads as designed rather than
 * broken — and so whoever supplies the image knows the slot and its
 * aspect ratio.
 *
 * `ratio` takes a CSS aspect-ratio string ("16/9", "4/3", "1/1"). It is
 * applied inline because Tailwind can only emit arbitrary aspect ratios
 * it can see at build time, and these come from the page at runtime.
 */
export function MpImagePlaceholder({
  label = "Image",
  ratio,
  rounded = "rounded-2xl",
  className,
}: {
  label?: string;
  ratio?: string;
  rounded?: string;
  className?: string;
}) {
  return (
    <div
      className={cn("mp-img-ph", rounded, className)}
      style={ratio ? { aspectRatio: ratio } : undefined}
      role="img"
      aria-label={`${label} placeholder`}
    >
      <div className="relative z-10 flex flex-col items-center justify-center gap-2.5 px-6 text-center">
        <span className="grid size-12 place-items-center rounded-xl border border-mp-border bg-mp-surface">
          <ImageIcon className="size-[22px] text-mp-primary" />
        </span>
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-mp-text-mut">
          {label}
        </span>
      </div>
    </div>
  );
}

/** Real artwork for a `MpPageHero` `media` slot — the filled-in counterpart
 *  of `MpImagePlaceholder`, matching its 4/3 box, 2xl radius and hairline so
 *  swapping one for the other doesn't shift the hero layout.
 *
 *  Uses `next/image` rather than a bare `<img>`: the source art is a ~1.9 MB
 *  PNG, and the project already has AVIF/WebP output configured in
 *  next.config.js, so this ships an order of magnitude less over the wire.
 *  `sizes` is capped at the 26rem the hero's right column is actually given
 *  (see MpPageHero's grid) — without it Next would generate for the full
 *  viewport width and serve a needlessly large candidate.
 *
 *  `priority` because this sits in the hero, above the fold: it is the LCP
 *  candidate on these pages, so it must not wait for lazy-load. */
export function MpHeroImage({
  src,
  alt,
  className,
}: {
  src: string;
  alt: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "relative aspect-[4/3] overflow-hidden rounded-2xl border border-mp-border bg-mp-surface",
        className,
      )}
    >
      <NextImage
        src={src}
        alt={alt}
        fill
        priority
        sizes="(min-width: 1024px) 26rem, 0px"
        className="object-cover"
      />
    </div>
  );
}
