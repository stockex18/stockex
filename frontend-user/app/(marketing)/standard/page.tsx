import type { Metadata } from "next";
import { ArrowRight, Check } from "lucide-react";
import {
  MpButton,
  MpContainer,
  MpHeading,
  MpHeroImage,
  MpPageHero,
  MpSection,
} from "@/components/marketing/mp-ui";

export const metadata: Metadata = {
  title: "Real Account — Demat + Trading on NSE, BSE & MCX | StockEx",
  description:
    "StockEx's real-money account: a complete Demat + trading account with Equity, Intraday, F&O and Commodities across NSE, BSE & MCX. Opens in 5 minutes.",
};

const STATS = [
  { value: "5 min", label: "Account Opening" },
  { value: "All", label: "Segments" },
  { value: "7000+", label: "Stocks" },
  { value: "T+1", label: "Settlement" },
];

// One real account, so everything that used to sit behind a separate
// "Pro" tier — priority support, a dedicated manager, API/algo access —
// is simply part of the account. There is no upgrade to sell.
const FEATURES = [
  "Educational content & tutorials",
  "Priority 24x7 customer support",
  "Demat + trading account (CDSL/NSDL)",
  "Trade Equity, F&O, Commodities & IPO",
  "Dedicated relationship manager",
  "API / algo access for programmatic trading",
  "Transparent terms, no hidden conditions",
  "Add funds via Net Banking",
  "Real-time NSE, BSE & MCX data",
  "Advanced charts, GTT & basket orders",
  "Premium market research & F&O analytics",
  "Mobile trading apps",
];

// Two accounts, so two columns. Everything upstream of settlement is
// deliberately identical between them — that is the whole point of the
// demo account.
const COMPARE = {
  cols: ["Feature", "Real Account", "Demo Account"],
  rows: [
    ["Equity Delivery", "Included", "Virtual"],
    ["Intraday & F&O", "Included", "Virtual"],
    ["Commodities (MCX)", "Included", "Virtual"],
    ["Live option chain", "Yes", "Yes"],
    ["Advanced charts", "Yes", "Yes"],
    ["GTT & basket orders", "Yes", "Yes"],
    ["API / algo access", "Included", "—"],
    ["Margin", "SPAN + Exposure", "SPAN + Exposure"],
    ["Support", "Priority 24x7", "24x7"],
    ["Profits can be withdrawn", "Yes", "—"],
    ["Deposit required", "Yes", "No"],
  ],
};

export default function StandardAccountPage() {
  return (
    <>
      <MpPageHero
        eyebrow="For Everyday Investors & Retail Traders"
        title="Real Account"
        lead="StockEx's real-money account. A complete Demat + trading account with access to Equity, Intraday, F&O and Commodities across NSE, BSE & MCX — one account, every segment, nothing held back behind a tier."
        media={<MpHeroImage src="/images/platform_img.png" alt="The StockEx Real Account trading platform" />}
      >
        <MpButton href="/register" size="lg">
          Open Real Account
          <ArrowRight className="size-4" />
        </MpButton>
      </MpPageHero>

      {/* Stats strip */}
      <div className="border-b border-mp-border bg-mp-surface-2/60">
        <MpContainer>
          <dl className="grid grid-cols-2 divide-mp-border lg:grid-cols-4 lg:divide-x">
            {STATS.map((s, i) => (
              <div
                key={s.label}
                className={
                  "flex flex-col gap-1 px-2 py-7 text-center sm:py-9 " +
                  (i < 2 ? "border-b border-mp-border lg:border-b-0" : "")
                }
              >
                <dd className="mp-num text-2xl font-semibold text-mp-text sm:text-3xl">
                  {s.value}
                </dd>
                <dt className="text-xs font-medium uppercase tracking-wide text-mp-text-mut sm:text-[13px]">
                  {s.label}
                </dt>
              </div>
            ))}
          </dl>
        </MpContainer>
      </div>

      {/* Features */}
      <MpSection>
        <MpHeading eyebrow="What's included" title="Account Features" />
        <div className="mt-10 grid gap-4 sm:grid-cols-2">
          {FEATURES.map((f) => (
            <div key={f} className="flex items-start gap-3">
              <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-mp-primary/10 text-mp-primary">
                <Check className="size-3.5" />
              </span>
              <p className="text-sm leading-[1.6] text-mp-text">{f}</p>
            </div>
          ))}
        </div>
      </MpSection>

      {/* Compare */}
      <MpSection light>
        <MpHeading eyebrow="Compare" title="Real vs Demo" />
        <div className="mt-10 overflow-x-auto rounded-2xl border border-mp-border bg-mp-surface">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead>
              <tr className="border-b border-mp-border text-xs uppercase tracking-wide text-mp-text-mut">
                {COMPARE.cols.map((c, i) => (
                  <th
                    key={c}
                    className={cnHead(i)}
                  >
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {COMPARE.rows.map((row) => (
                <tr key={row[0]} className="border-b border-mp-border last:border-0">
                  <td className="px-5 py-4 font-medium text-mp-text">{row[0]}</td>
                  <td className="px-5 py-4 font-medium text-mp-primary">{row[1]}</td>
                  <td className="px-5 py-4 text-mp-text-mut">{row[2]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </MpSection>

      {/* CTA band */}
      <section className="mp-dark relative overflow-hidden bg-mp-bg text-mp-text">
        <div className="mp-grid-texture absolute inset-0 opacity-50" aria-hidden />
        <MpContainer className="relative py-20 text-center sm:py-24">
          <h2 className="mx-auto max-w-3xl font-display text-3xl font-bold leading-[1.1] text-mp-text sm:text-4xl">
            Ready to Start Investing?
          </h2>
          <p className="mx-auto mt-5 max-w-2xl text-lg leading-[1.6] text-mp-text-mut">
            Open your Real Account today and start trading across NSE, BSE &amp; MCX.
          </p>
          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <MpButton href="/register" size="lg" className="w-full sm:w-auto">
              Open Real Account
              <ArrowRight className="size-4" />
            </MpButton>
            <MpButton
              href="/demo"
              variant="secondary"
              size="lg"
              className="w-full border-mp-border text-mp-text hover:border-mp-primary/60 sm:w-auto"
            >
              Try the Demo Account First
            </MpButton>
          </div>
        </MpContainer>
      </section>

      {/* Disclaimer */}
      <MpSection>
        <p className="mx-auto max-w-2xl text-center text-sm leading-[1.6] text-mp-text-mut">
          Investments in securities market are subject to market risks. Read all
          the related documents carefully before investing.
        </p>
      </MpSection>
    </>
  );
}

// Highlight the Real Account column header (it's this page's account).
function cnHead(i: number) {
  const base = "px-5 py-4 font-medium";
  return i === 1 ? `${base} text-mp-primary` : base;
}
