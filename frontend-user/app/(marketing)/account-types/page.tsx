import type { Metadata } from "next";
import {
  ArrowRight,
  Briefcase,
  Check,
  FileCheck2,
  Gamepad2,
  Minus,
  TrendingUp,
  UserPlus,
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
  title: "Accounts — Trading, Brokerage & Games Accounts | StockEx",
  description:
    "Open a StockEx account: trade every market from one terminal, run your own brokerage and earn from your client network, or play skill-based games tied to live markets.",
};

// Mirrors the account types defined in data/joinStockexAccounts.js, which
// drives the same three offerings on the homepage — one source of truth
// for what StockEx actually sells.
const ACCOUNTS = [
  {
    href: "/standard",
    icon: TrendingUp,
    title: "Trading Account",
    body: "Trade every market — options, stocks, commodities and crypto — from a single terminal, with referral income on top.",
    facts: [
      { label: "Markets", value: "All segments" },
      { label: "KYC", value: "Required" },
      { label: "Opening", value: "100% online" },
      { label: "Referrals", value: "Included" },
    ],
    featured: true,
    cta: "Explore Trading",
  },
  {
    href: "/ib-management",
    icon: Briefcase,
    title: "Brokerage Account",
    body: "Run your own brokerage. Earn brokerage on every client trade, game share, and override income from your sub-broker network.",
    facts: [
      { label: "For", value: "Entrepreneurs" },
      { label: "Income", value: "4 streams" },
      { label: "Dashboard", value: "Full admin" },
      { label: "Sub-brokers", value: "Unlimited" },
    ],
    cta: "Explore Brokerage",
  },
  {
    href: "/nifty-games",
    icon: Gamepad2,
    title: "Games Account",
    body: "Skill-based games tied to live market prices — fast rounds, jackpots and daily challenges, settled against real prices.",
    facts: [
      { label: "Rounds", value: "Every 15 min" },
      { label: "Tied to", value: "Live prices" },
      { label: "Games", value: "4 formats" },
      { label: "Referrals", value: "Included" },
    ],
    cta: "Explore Games",
  },
];

const COMPARISON: {
  feature: string;
  trading: boolean | string;
  brokerage: boolean | string;
  games: boolean | string;
}[] = [
  { feature: "Trade Equity, F&O & Commodities", trading: true, brokerage: true, games: false },
  { feature: "Live market data", trading: true, brokerage: true, games: true },
  { feature: "Skill-based games", trading: true, brokerage: true, games: true },
  { feature: "Referral earnings", trading: true, brokerage: true, games: true },
  { feature: "Earn from client trades", trading: false, brokerage: true, games: false },
  { feature: "Sub-broker network & overrides", trading: false, brokerage: true, games: false },
  { feature: "Admin dashboard", trading: false, brokerage: true, games: false },
  { feature: "KYC required", trading: "Yes", brokerage: "Yes", games: "Yes" },
];

const STEPS = [
  {
    n: "1",
    icon: UserPlus,
    title: "Sign up",
    body: "Enter your name, mobile and email, and pick the broker you want to join under.",
  },
  {
    n: "2",
    icon: FileCheck2,
    title: "Complete KYC",
    body: "Submit PAN and bank details online. No paperwork and no branch visit.",
  },
  {
    n: "3",
    icon: Wallet,
    title: "Add funds & trade",
    body: "Deposit via UPI, NEFT, IMPS or RTGS and start trading across every segment.",
  },
];

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

export default function AccountTypesPage() {
  return (
    <>
      <MpPageHero
        eyebrow="Accounts"
        title="An Account for How You Trade"
        lead="Trade the markets yourself, build a brokerage business on top of them, or play skill-based games settled against live prices."
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

      {/* Account types */}
      <MpSection>
        <MpHeading
          eyebrow="Account types"
          title="Choose Your Account"
          lead="All three run on the same platform and the same live data. What changes is who earns, and from what."
        />
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {ACCOUNTS.map((a) => (
            <MpLinkCard
              key={a.href}
              href={a.href}
              iconNode={<a.icon className="size-5" />}
              title={a.title}
              body={a.body}
              facts={a.facts}
              featured={a.featured}
              cta={a.cta}
            />
          ))}
        </div>
      </MpSection>

      {/* Comparison */}
      <MpSection className="bg-mp-surface-2/60">
        <MpHeading
          eyebrow="Comparison"
          title="What Each Account Gets"
          lead="A brokerage account is a superset of a trading account — it adds the earning side on top."
        />
        <div className="mt-10 overflow-x-auto rounded-2xl border border-mp-border bg-mp-surface">
          <table className="w-full min-w-[640px] text-left text-sm">
            <caption className="sr-only">
              Feature comparison of the Trading, Brokerage and Games accounts
            </caption>
            <thead>
              <tr className="border-b border-mp-border text-xs uppercase tracking-wide text-mp-text-mut">
                <th scope="col" className="px-5 py-4 font-medium">
                  Feature
                </th>
                <th scope="col" className="px-5 py-4 text-center font-medium text-mp-primary">
                  Trading
                </th>
                <th scope="col" className="px-5 py-4 text-center font-medium">
                  Brokerage
                </th>
                <th scope="col" className="px-5 py-4 text-center font-medium">
                  Games
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
                    <Cell value={row.trading} />
                  </td>
                  <td className="px-5 py-4 text-center">
                    <Cell value={row.brokerage} />
                  </td>
                  <td className="px-5 py-4 text-center">
                    <Cell value={row.games} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </MpSection>

      {/* How to open */}
      <MpSection>
        <MpHeading eyebrow="Getting started" title="Open an Account in Three Steps" />
        <MpProse className="mt-6">
          Account opening is fully online. Most applications are ready to trade
          the same day once KYC clears.
        </MpProse>
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {STEPS.map((s) => (
            <MpCard key={s.n} className="flex flex-col gap-4">
              <div className="flex items-center gap-3">
                <span className="grid size-11 place-items-center rounded-xl bg-mp-primary/10 text-mp-primary">
                  <s.icon className="size-5" />
                </span>
                <span className="mp-num text-sm font-semibold text-mp-text-mut">
                  Step {s.n}
                </span>
              </div>
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
            Open Your Account Today
          </h2>
          <p className="mx-auto mt-5 max-w-2xl text-lg leading-[1.6] text-mp-text-mut">
            100% online, no paperwork. Start trading across NSE, BSE &amp; MCX.
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
