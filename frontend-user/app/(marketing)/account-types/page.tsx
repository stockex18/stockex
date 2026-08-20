import type { Metadata } from "next";
import {
  ArrowRight,
  Check,
  GraduationCap,
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
  MpHeroImage,
  MpLinkCard,
  MpPageHero,
  MpProse,
  MpSection,
} from "@/components/marketing/mp-ui";

export const metadata: Metadata = {
  title: "Accounts — Real & Demo Trading Accounts | StockEx",
  description:
    "StockEx offers two accounts: a real account to trade every market from one terminal, and a demo account to practise on live prices with virtual funds.",
};

// StockEx offers exactly TWO accounts. Brokerage (/ib-management) and
// Games (/nifty-games) used to be listed here as a third and fourth
// "account type" — they are products, not accounts, and still have their
// own pages and nav entries. Mirrors data/joinStockexAccounts.js, which
// drives the same two cards on the homepage.
const ACCOUNTS = [
  {
    href: "/standard",
    icon: TrendingUp,
    title: "Real Account",
    body: "Trade every market with real funds — options, stocks, commodities and crypto from a single terminal, with referral income on top.",
    facts: [
      { label: "Markets", value: "All segments" },
      { label: "KYC", value: "Required" },
      { label: "Opening", value: "100% online" },
      { label: "Referrals", value: "Included" },
    ],
    featured: true,
    cta: "Explore the Real Account",
  },
  {
    href: "/demo",
    icon: GraduationCap,
    title: "Demo Account",
    body: "Practise on the same live NSE, BSE and MCX prices with virtual funds. No KYC, no deposit, unlimited resets.",
    facts: [
      { label: "Funds", value: "Virtual" },
      { label: "KYC", value: "Not needed" },
      { label: "Resets", value: "Unlimited" },
      { label: "Duration", value: "Unlimited" },
    ],
    cta: "Explore the Demo Account",
  },
];

// Real = real money, Demo = practice. Everything upstream of settlement is
// deliberately identical, which is the whole point of the demo account.
const STANDARD_VS_PAPER = [
  { feature: "Money at stake", standard: "Real funds", paper: "Practice coins" },
  { feature: "Live market prices", standard: true, paper: true },
  { feature: "Full order types (Market, Limit, SL, SL-M)", standard: true, paper: true },
  { feature: "Every segment — NSE, BSE, MCX, Crypto", standard: true, paper: true },
  { feature: "Profits can be withdrawn", standard: true, paper: false },
  { feature: "Losses cost you money", standard: true, paper: false },
  { feature: "Deposit required to start", standard: "Yes", paper: "No" },
  { feature: "Best for", standard: "Trading for real", paper: "Learning & testing a strategy" },
];

// The KYC step was dropped from the opening flow, so this is a two-step
// journey now. Numbered 1–2 rather than 1–3: a visible gap in the sequence
// reads as a rendering bug to anyone on the page.
const STEPS = [
  {
    n: "1",
    icon: UserPlus,
    title: "Sign up",
    body: "Enter your name, mobile and email, and pick the broker you want to join under.",
  },
  {
    n: "2",
    icon: Wallet,
    title: "Add Stock Coin & Trade",
    body: "Top up your Stock Coin balance and start trading across every segment.",
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
        title="Two Accounts. That's It."
        lead="A real account to trade every market with your own funds, and a demo account to practise on the same live prices with virtual ones. Nothing else to choose between."
        media={<MpHeroImage src="/images/account.png" alt="StockEx real and demo account dashboards" />}
      >
        <MpButton href="/register" size="lg">
          Open Real Account
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

      {/* Account types */}
      <MpSection>
        <MpHeading
          eyebrow="Account types"
          title="Choose Your Account"
          lead="Both run on the same platform, the same terminal and the same live data. The only thing that changes is whether the money is real."
        />
        <div className="mt-10 grid gap-5 sm:grid-cols-2">
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

      {/* Real vs Demo */}
      <MpSection>
        <MpHeading
          eyebrow="Real vs Demo"
          title="Difference between the Real A/c and the Demo A/c"
          lead="Both accounts use the same live prices, the same order types and the same terminal. The only thing that changes is whether the money is real."
        />
        <div className="mt-10 overflow-x-auto rounded-2xl border border-mp-border bg-mp-surface">
          <table className="w-full min-w-[640px] text-left text-sm">
            <caption className="sr-only">
              Comparison of the Real account and the Demo (practice) account
            </caption>
            <thead>
              <tr className="border-b border-mp-border text-xs uppercase tracking-wide text-mp-text-mut">
                <th scope="col" className="px-5 py-4 font-medium">
                  What changes
                </th>
                <th scope="col" className="px-5 py-4 text-center font-medium text-mp-primary">
                  Real A/c
                </th>
                <th scope="col" className="px-5 py-4 text-center font-medium">
                  Demo A/c
                </th>
              </tr>
            </thead>
            <tbody>
              {STANDARD_VS_PAPER.map((row) => (
                <tr key={row.feature} className="border-b border-mp-border last:border-0">
                  <th scope="row" className="px-5 py-4 text-left font-medium text-mp-text">
                    {row.feature}
                  </th>
                  <td className="bg-mp-primary/[0.04] px-5 py-4 text-center">
                    <Cell value={row.standard} />
                  </td>
                  <td className="px-5 py-4 text-center">
                    <Cell value={row.paper} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </MpSection>

      {/* How to open */}
      <MpSection light>
        <MpHeading eyebrow="Getting started" title="Open an Account in Two Steps" />
        <MpProse className="mt-6">
          Account opening is fully online. Sign up, add your Stock Coin
          balance, and you are ready to trade.
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
