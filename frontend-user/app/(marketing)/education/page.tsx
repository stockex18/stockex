import type { Metadata } from "next";
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  Clock,
  GraduationCap,
  Landmark,
  Layers,
  PlayCircle,
  Smartphone,
  Target,
  Trophy,
} from "lucide-react";
import {
  MpButton,
  MpCard,
  MpHeading,
  MpHeroImage,
  MpPageHero,
  MpSection,
} from "@/components/marketing/mp-ui";

export const metadata: Metadata = {
  title: "Trading Tutorials — Learn to Trade NSE, BSE & MCX | StockEx",
  description:
    "Learn to trade the Indian markets at your own pace with comprehensive video courses and tutorials — from stock-market basics to F&O and intraday strategies.",
};

// The four learning tracks. `material` lists what each track covers — the
// same card, one extra list inside it.
const COURSES = [
  {
    icon: BookOpen,
    level: "Beginner",
    title: "Beginners",
    body: "Learn how the Indian stock market works — NSE, BSE, Demat accounts, and placing your first Delivery and Intraday trades.",
    duration: "2 hours",
    lessons: "12 lessons",
    material: [
      "How the NSE, BSE and MCX actually work",
      "Demat and trading accounts explained",
      "Reading a quote: LTP, bid, ask and volume",
      "Placing your first Delivery and Intraday order",
      "Order types — Market, Limit, SL and SL-M",
    ],
  },
  {
    icon: BarChart3,
    level: "Intermediate",
    title: "Technical",
    body: "Master candlestick patterns, chart indicators, and technical analysis used to trade Nifty 50, Bank Nifty and individual stocks.",
    duration: "4 hours",
    lessons: "20 lessons",
    material: [
      "Candlestick patterns that actually repeat",
      "Support, resistance and trendlines",
      "Moving averages, RSI and MACD in practice",
      "Volume as confirmation, not decoration",
      "Building a chart setup you can trade daily",
    ],
  },
  {
    icon: Layers,
    level: "Intermediate",
    title: "Futures & Options",
    body: "Understand F&O — option chain, expiry, premiums, SPAN + Exposure margin and proven strategies on index and stock derivatives.",
    duration: "3 hours",
    lessons: "15 lessons",
    material: [
      "Reading the option chain end to end",
      "Strike selection, premium and time decay",
      "Weekly vs monthly expiry behaviour",
      "SPAN + Exposure margin, before you trade",
      "Core strategies: covered call, spread, straddle",
    ],
  },
  {
    icon: Target,
    level: "Advanced",
    title: "Intraday Strategy",
    body: "Learn momentum, breakout and scalping strategies for Intraday trading on NSE & BSE, with strict risk management.",
    duration: "5 hours",
    lessons: "25 lessons",
    material: [
      "The first 15 minutes: opening range playbook",
      "Momentum and breakout entries",
      "Scalping the index with tight stops",
      "Position sizing and the daily loss limit",
      "Squaring off: when to hold and when to cut",
    ],
  },
  {
    icon: Landmark,
    level: "Beginner",
    title: "IPO & Long-Term Investing",
    body: "Apply for IPOs, analyse companies with fundamental analysis, and build a long-term portfolio of stocks and mutual funds.",
    duration: "3 hours",
    lessons: "14 lessons",
    // Not one of the four tracks above — no material list, so the card
    // renders exactly as it did before.
    material: [] as string[],
  },
];

const WHY = [
  {
    icon: GraduationCap,
    title: "Expert Instructors",
    body: "Learn from professional traders with years of experience.",
  },
  {
    icon: Smartphone,
    title: "Learn Anywhere",
    body: "Access courses on any device, anytime, anywhere.",
  },
  {
    icon: Trophy,
    title: "Practical Skills",
    body: "Apply what you learn immediately in your trading.",
  },
];

export default function EducationPage() {
  return (
    <>
      <MpPageHero
        eyebrow="Trading Tutorials"
        title="Learn to trade the Indian markets"
        lead="Learn to trade the Indian markets — NSE, BSE & MCX — at your own pace with our comprehensive video courses and tutorials."
        media={<MpHeroImage src="/images/Education_banner.png" alt="StockEx trading courses and tutorials" />}
      >
        <MpButton href="/register" size="lg">
          Browse All Courses
          <ArrowRight className="size-4" />
        </MpButton>
      </MpPageHero>

      {/* Featured courses */}
      <MpSection>
        <MpHeading eyebrow="Courses" title="Featured Courses" />
        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {COURSES.map((c) => (
            <MpCard key={c.title} className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <span className="grid size-11 place-items-center rounded-xl bg-mp-primary/10 text-mp-primary">
                  <c.icon className="size-5" />
                </span>
                <span className="rounded-full bg-mp-surface-2 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-mp-text-mut">
                  {c.level}
                </span>
              </div>
              <h3 className="font-display text-lg font-semibold leading-snug text-mp-text">
                {c.title}
              </h3>
              <p className="text-sm leading-[1.6] text-mp-text-mut">{c.body}</p>
              {c.material.length ? (
                <ul className="flex flex-col gap-1.5 border-t border-mp-border pt-3">
                  {c.material.map((m) => (
                    <li
                      key={m}
                      className="flex items-start gap-2 text-[13px] leading-[1.5] text-mp-text-mut"
                    >
                      <span
                        aria-hidden
                        className="mt-[7px] size-1 shrink-0 rounded-full bg-mp-primary"
                      />
                      {m}
                    </li>
                  ))}
                </ul>
              ) : null}
              <div className="mt-1 flex items-center gap-4 text-xs font-medium text-mp-text-mut">
                <span className="flex items-center gap-1.5">
                  <Clock className="size-3.5" />
                  {c.duration}
                </span>
                <span className="flex items-center gap-1.5">
                  <PlayCircle className="size-3.5" />
                  {c.lessons}
                </span>
              </div>
              <MpButton href="/register" variant="secondary" className="mt-auto w-full">
                Start Learning
                <ArrowRight className="size-4" />
              </MpButton>
            </MpCard>
          ))}
        </div>
      </MpSection>

      {/* Why learn */}
      <MpSection light>
        <MpHeading
          align="center"
          eyebrow="Why StockEx"
          title="Why Learn with StockEx?"
        />
        <div className="mt-12 grid gap-5 lg:grid-cols-3">
          {WHY.map((w) => (
            <MpCard key={w.title} className="flex flex-col items-center gap-4 text-center">
              <span className="grid size-12 place-items-center rounded-2xl bg-mp-primary/10 text-mp-primary">
                <w.icon className="size-6" />
              </span>
              <h3 className="font-display text-lg font-semibold text-mp-text">
                {w.title}
              </h3>
              <p className="text-sm leading-[1.6] text-mp-text-mut">{w.body}</p>
            </MpCard>
          ))}
        </div>
      </MpSection>

      {/* CTA + disclaimer */}
      <MpSection>
        <div className="flex flex-col items-center gap-6 text-center">
          <MpButton href="/register" size="lg">
            Browse All Courses
            <ArrowRight className="size-4" />
          </MpButton>
          <p className="max-w-2xl text-sm leading-[1.6] text-mp-text-mut">
            Investments in securities market are subject to market risks. Read
            all the related documents carefully before investing.
          </p>
        </div>
      </MpSection>
    </>
  );
}
