import type { Metadata } from "next";
import {
  ArrowRight,
  Check,
  Gauge,
  Minus,
  Monitor,
  Smartphone,
  TerminalSquare,
} from "lucide-react";
import {
  MpButton,
  MpCard,
  MpContainer,
  MpHeading,
  MpLinkCard,
  MpHeroImage,
  MpPageHero,
  MpProse,
  MpSection,
} from "@/components/marketing/mp-ui";

export const metadata: Metadata = {
  title: "Platforms — Real & Demo Trading Accounts | StockEx",
  description:
    "Two ways to trade on StockEx: a real Demat + trading account with every segment included, and a risk-free demo account on live NSE, BSE & MCX prices.",
};

const PLATFORMS = [
  {
    href: "/standard",
    icon: Monitor,
    title: "Real Account",
    body: "The real-money Demat + trading account. Every segment, priority support, API access, and a 5-minute online opening flow.",
    featured: true,
    facts: [
      { label: "Account opening", value: "5 min" },
      { label: "Segments", value: "All" },
      { label: "Stocks", value: "7000+" },
      { label: "Settlement", value: "T+1" },
    ],
  },
  {
    href: "/demo",
    icon: TerminalSquare,
    title: "Demo Account",
    body: "Practise on live NSE, BSE & MCX prices with virtual funds. No KYC, no real money, unlimited resets.",
    facts: [
      { label: "Virtual funds", value: "Included" },
      { label: "KYC", value: "Not needed" },
      { label: "Duration", value: "Unlimited" },
      { label: "Platforms", value: "All" },
    ],
  },
];

// `true` → included, `false` → not available, string → qualified value.
const COMPARISON: { feature: string; real: boolean | string; demo: boolean | string }[] = [
  { feature: "Equity, F&O & Commodities", real: true, demo: true },
  { feature: "Live NSE, BSE & MCX prices", real: true, demo: true },
  { feature: "Advanced charts & option chain", real: true, demo: true },
  { feature: "Real money & real settlement", real: true, demo: false },
  { feature: "KYC required", real: "Yes", demo: "No" },
  { feature: "Support", real: "Priority", demo: "Standard" },
  { feature: "Dedicated relationship manager", real: true, demo: false },
  { feature: "API / algo access", real: true, demo: false },
  { feature: "Virtual funds & resets", real: false, demo: true },
];

const SURFACES = [
  {
    icon: Monitor,
    title: "Web terminal",
    body: "The full trading terminal in the browser — charts, market depth, option chain and the order ticket side by side.",
  },
  {
    icon: Smartphone,
    title: "Mobile PWA",
    body: "Install StockEx to your home screen and get a native-feeling app with push alerts, on both Android and iOS.",
  },
  {
    icon: Gauge,
    title: "Same engine everywhere",
    body: "Positions, margins and orders are the same objects on every surface, so nothing is out of sync when you switch device.",
  },
];

/** Cell renderer for the comparison table. */
function Cell({ value }: { value: boolean | string }) {
  if (value === true) {
    return (
      <>
        <Check className="mx-auto size-4 text-mp-primary" aria-hidden />
        <span className="sr-only">Included</span>
      </>
    );
  }
  if (value === false) {
    return (
      <>
        <Minus className="mx-auto size-4 text-mp-text-mut/50" aria-hidden />
        <span className="sr-only">Not available</span>
      </>
    );
  }
  return <span className="text-mp-text-mut">{value}</span>;
}

export default function PlatformsPage() {
  return (
    <>
      <MpPageHero
        eyebrow="Platforms"
        title="One Real Account, Plus a Demo to Practise On"
        lead="One real account with every segment, priority support and API access included — and a risk-free demo account to practise on first."
        media={<MpHeroImage src="/images/platform_img.png" alt="StockEx trading platform on desktop and mobile" />}
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
          Try the Demo Account
        </MpButton>
      </MpPageHero>

      {/* Platform cards */}
      <MpSection>
        <MpHeading
          eyebrow="Choose a platform"
          title="Pick the Account That Fits"
          lead="Every account trades the same markets on the same engine. What changes is the support, tooling and whether the money is real."
        />
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {PLATFORMS.map((p) => (
            <MpLinkCard
              key={p.href}
              href={p.href}
              iconNode={<p.icon className="size-5" />}
              title={p.title}
              body={p.body}
              facts={p.facts}
              featured={p.featured}
              cta={`Explore ${p.title}`}
            />
          ))}
        </div>
      </MpSection>

      {/* Comparison */}
      <MpSection light>
        <MpHeading
          eyebrow="Comparison"
          title="Side by Side"
          lead="The practical differences, in one table."
        />
        <div className="mt-10 overflow-x-auto rounded-2xl border border-mp-border bg-mp-surface">
          <table className="w-full min-w-[620px] text-left text-sm">
            <caption className="sr-only">
              Feature comparison of the Real and Demo accounts
            </caption>
            <thead>
              <tr className="border-b border-mp-border text-xs uppercase tracking-wide text-mp-text-mut">
                <th scope="col" className="px-5 py-4 font-medium">
                  Feature
                </th>
                <th scope="col" className="px-5 py-4 text-center font-medium text-mp-primary">
                  Real Account
                </th>
                <th scope="col" className="px-5 py-4 text-center font-medium">
                  Demo Account
                </th>
              </tr>
            </thead>
            <tbody>
              {COMPARISON.map((row) => (
                <tr key={row.feature} className="border-b border-mp-border last:border-0">
                  <th scope="row" className="px-5 py-4 text-left font-medium text-mp-text">
                    {row.feature}
                  </th>
                  <td className="bg-mp-primary/[0.04] px-5 py-4 text-center">
                    <Cell value={row.real} />
                  </td>
                  <td className="px-5 py-4 text-center">
                    <Cell value={row.demo} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </MpSection>

      {/* Where it runs */}
      <MpSection>
        <MpHeading eyebrow="Access" title="Trade From Anywhere" />
        <MpProse className="mt-6">
          There is no separate download and no desktop-only feature set. The
          same terminal runs in the browser and installs to your phone as a
          progressive web app.
        </MpProse>
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {SURFACES.map((s) => (
            <MpCard key={s.title} className="flex flex-col gap-4">
              <span className="grid size-11 place-items-center rounded-xl bg-mp-primary/10 text-mp-primary">
                <s.icon className="size-5" />
              </span>
              <h3 className="font-display text-lg font-semibold text-mp-text">
                {s.title}
              </h3>
              <p className="text-sm leading-[1.6] text-mp-text-mut">{s.body}</p>
            </MpCard>
          ))}
        </div>
      </MpSection>

      {/* CTA band */}
      <section className="mp-dark relative overflow-hidden bg-mp-bg text-mp-text">
        <div className="mp-grid-texture absolute inset-0 opacity-50" aria-hidden />
        <MpContainer className="relative py-20 text-center sm:py-24">
          <h2 className="mx-auto max-w-3xl font-display text-3xl font-bold leading-[1.1] text-mp-text sm:text-4xl">
            Not Sure Which to Pick?
          </h2>
          <p className="mx-auto mt-5 max-w-2xl text-lg leading-[1.6] text-mp-text-mut">
            Start on a paper account — it needs no KYC — and switch to a live
            account whenever you are ready.
          </p>
          <div className="mt-9 flex flex-col justify-center gap-3 sm:flex-row">
            <MpButton href="/demo" size="lg" className="w-full sm:w-auto">
              Open Demo Account
              <ArrowRight className="size-4" />
            </MpButton>
            <MpButton
              href="/register"
              variant="secondary"
              size="lg"
              className="w-full border-mp-border text-mp-text sm:w-auto"
            >
              Open Live Account
            </MpButton>
          </div>
        </MpContainer>
      </section>
    </>
  );
}
