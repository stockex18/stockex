import type { Metadata } from "next";
import {
  ArrowRight,
  BarChart3,
  CandlestickChart,
  Clock,
  Layers,
  LineChart,
  ShieldCheck,
  Wallet,
} from "lucide-react";
import {
  MpButton,
  MpCard,
  MpContainer,
  MpHeading,
  MpLinkCard,
  MpPageHero,
  MpProse,
  MpSection,
} from "@/components/marketing/mp-ui";

export const metadata: Metadata = {
  title: "Trading — Equity, F&O, Commodities & Indices | StockEx",
  description:
    "Trade every Indian market from one account: Equity on NSE & BSE, Futures & Options on NFO, Commodities on MCX, and index derivatives on Nifty, Bank Nifty & Sensex.",
};

// Figures mirror each segment's own page so the hub can never contradict
// the detail view it links to.
const SEGMENTS = [
  {
    href: "/equity",
    icon: Wallet,
    title: "Equity",
    body: "Own shares of India's leading companies. Delivery for long-term portfolios, intraday for active trading — both on NSE and BSE.",
    facts: [
      { label: "Exchanges", value: "NSE / BSE" },
      { label: "Listed stocks", value: "7000+" },
      { label: "Settlement", value: "T+1" },
      { label: "Brokerage", value: "₹0 delivery" },
    ],
  },
  {
    href: "/futures-options",
    icon: CandlestickChart,
    title: "Futures & Options",
    body: "Index and stock derivatives on the NSE F&O segment, with a live option chain and transparent SPAN + Exposure margins.",
    facts: [
      { label: "Segment", value: "NSE F&O" },
      { label: "Contracts", value: "200+" },
      { label: "Expiry", value: "Weekly" },
      { label: "Margin", value: "SPAN + Exp" },
    ],
  },
  {
    href: "/commodities",
    icon: BarChart3,
    title: "Commodities",
    body: "Diversify beyond equities with Gold, Silver, Crude Oil and more on MCX, including the extended evening session.",
    facts: [
      { label: "Exchange", value: "MCX" },
      { label: "Commodities", value: "15+" },
      { label: "Hours", value: "9 AM–11:30 PM" },
      { label: "Margin", value: "SPAN + Exp" },
    ],
  },
  {
    href: "/indices",
    icon: LineChart,
    title: "Indices",
    body: "Take a view on the whole market through Nifty 50, Bank Nifty and Sensex index futures & options.",
    facts: [
      { label: "Exchanges", value: "NSE / BSE" },
      { label: "Indices", value: "10+" },
      { label: "Expiries", value: "Weekly & Monthly" },
      { label: "Margin", value: "SPAN + Exp" },
    ],
  },
];

// Lot sizes match the ones already published on /instruments and /equity so
// the hub can't quote a different contract size from the detail pages.
const TOP_INSTRUMENTS = [
  { symbol: "NIFTY 50", exchange: "NSE · Index F&O", lot: "65 units", segment: "Futures & Options" },
  { symbol: "BANKNIFTY", exchange: "NSE · Index F&O", lot: "35 units", segment: "Futures & Options" },
  { symbol: "SENSEX", exchange: "BSE · Index F&O", lot: "20 units", segment: "Futures & Options" },
  { symbol: "RELIANCE", exchange: "NSE / BSE", lot: "1 share", segment: "Equity" },
  { symbol: "HDFCBANK", exchange: "NSE / BSE", lot: "1 share", segment: "Equity" },
  { symbol: "GOLD", exchange: "MCX", lot: "100 grams", segment: "Commodities" },
  { symbol: "CRUDEOIL", exchange: "MCX", lot: "100 barrels", segment: "Commodities" },
];

const STATS = [
  { value: "4", label: "Market Segments" },
  { value: "3", label: "Exchanges" },
  { value: "7000+", label: "Instruments" },
  { value: "₹20", label: "Max Per Order" },
];

const WHY = [
  {
    icon: Layers,
    title: "One account, every segment",
    body: "Equity, derivatives and commodities settle against a single margin pool — no separate logins, no moving funds between products.",
  },
  {
    icon: ShieldCheck,
    title: "Transparent margins",
    body: "SPAN + Exposure is shown before you place the order, so the requirement is never a surprise after execution.",
  },
  {
    icon: Clock,
    title: "Built for market hours",
    body: "Equity, F&O and the MCX evening session are all covered, from the 9:15 open through to the 11:30 PM commodity close.",
  },
];

export default function TradingPage() {
  return (
    <>
      <MpPageHero
        eyebrow="Trading"
        title="Trade Every Indian Market"
        lead="Equity, Futures & Options, Commodities and Indices — across NSE, BSE and MCX, from a single account and a single margin pool."
      >
        <MpButton href="/register" size="lg">
          Open Account
          <ArrowRight className="size-4" />
        </MpButton>
        <MpButton
          href="/demo"
          variant="secondary"
          size="lg"
          className="border-mp-border text-mp-text"
        >
          Try Paper Trading
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

      {/* Segments */}
      <MpSection>
        <MpHeading
          eyebrow="Segments"
          title="Pick Your Market"
          lead="Each segment has its own margins, hours and contract rules. Open one to see the full specification."
        />
        <div className="mt-10 grid gap-5 md:grid-cols-2">
          {SEGMENTS.map((s) => (
            <MpLinkCard
              key={s.href}
              href={s.href}
              iconNode={<s.icon className="size-5" />}
              title={s.title}
              body={s.body}
              facts={s.facts}
              cta={`Explore ${s.title}`}
            />
          ))}
        </div>
      </MpSection>

      {/* Top instruments */}
      <MpSection className="bg-mp-surface-2/60">
        <MpHeading
          eyebrow="Instruments"
          title="Top Tradable Instruments"
          lead="The contracts that see the most volume across our segments. Lot size is the minimum quantity one contract carries — NIFTY trades in lots of 65 units."
        />
        <div className="mt-10 overflow-x-auto rounded-2xl border border-mp-border bg-mp-surface">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead>
              <tr className="border-b border-mp-border text-xs uppercase tracking-wide text-mp-text-mut">
                <th className="px-5 py-4 font-medium">Symbol</th>
                <th className="px-5 py-4 font-medium">Exchange</th>
                <th className="px-5 py-4 font-medium">Lot Size</th>
                <th className="px-5 py-4 font-medium">Segment</th>
              </tr>
            </thead>
            <tbody>
              {TOP_INSTRUMENTS.map((ins) => (
                <tr key={ins.symbol} className="border-b border-mp-border last:border-0">
                  <td className="mp-num px-5 py-4 font-semibold text-mp-text">{ins.symbol}</td>
                  <td className="px-5 py-4 text-mp-text-mut">{ins.exchange}</td>
                  <td className="mp-num px-5 py-4 text-mp-text-mut">{ins.lot}</td>
                  <td className="px-5 py-4 text-mp-text-mut">{ins.segment}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </MpSection>

      {/* Why */}
      <MpSection>
        <MpHeading eyebrow="Why StockEx" title="Why Trade with StockEx" />
        <MpProse className="mt-6">
          One SEBI-registered account covers cash equity, derivatives and
          commodities. Margins are computed against a single pool and disclosed
          before execution, and the same charts, option chain and order ticket
          work across every segment.
        </MpProse>
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {WHY.map((f) => (
            <MpCard key={f.title} className="flex flex-col gap-4">
              <span className="grid size-11 place-items-center rounded-xl bg-mp-primary/10 text-mp-primary">
                <f.icon className="size-5" />
              </span>
              <h3 className="font-display text-lg font-semibold text-mp-text">
                {f.title}
              </h3>
              <p className="text-sm leading-[1.6] text-mp-text-mut">{f.body}</p>
            </MpCard>
          ))}
        </div>
      </MpSection>

      {/* CTA band */}
      <section className="mp-dark relative overflow-hidden bg-mp-bg text-mp-text">
        <div className="mp-grid-texture absolute inset-0 opacity-50" aria-hidden />
        <MpContainer className="relative py-20 text-center sm:py-24">
          <h2 className="mx-auto max-w-3xl font-display text-3xl font-bold leading-[1.1] text-mp-text sm:text-4xl">
            Ready to Start Trading?
          </h2>
          <p className="mx-auto mt-5 max-w-2xl text-lg leading-[1.6] text-mp-text-mut">
            Open your Demat &amp; trading account and access every segment on
            NSE, BSE &amp; MCX.
          </p>
          <div className="mt-9 flex justify-center">
            <MpButton href="/register" size="lg" className="w-full sm:w-auto">
              Open Account Now
              <ArrowRight className="size-4" />
            </MpButton>
          </div>
        </MpContainer>
      </section>
    </>
  );
}
