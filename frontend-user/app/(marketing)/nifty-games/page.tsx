import type { Metadata } from "next";
import {
  ArrowRight,
  Bitcoin,
  Clock,
  Coins,
  Gamepad2,
  Hash,
  ShieldCheck,
  Split,
  Trophy,
  TrendingUp,
  Wallet,
  Zap,
} from "lucide-react";
import {
  MpButton,
  MpCard,
  MpHeading,
  MpPageHero,
  MpSection,
  MpStatGrid,
} from "@/components/marketing/mp-ui";

export const metadata: Metadata = {
  title: "Nifty Games — Up/Down, Number, Bracket & Jackpot on Live NIFTY & BTC | StockEx",
  description:
    "Play Nifty Games on StockEx — Up/Down 15-minute rounds, Number (closing decimals), Bracket bands and Jackpot pools, settled automatically against the live NIFTY and Bitcoin feed.",
};

/* Ticket prices, payouts and windows below mirror the platform defaults in
   `GameSettings` (backend/app/models/games/settings.py). They are super-admin
   configurable per game, so the copy says "default" wherever a number could
   be re-tuned — a marketing page promising a fixed payout the admin can
   change is how you end up with a support ticket. */

const GAMES = [
  {
    icon: TrendingUp,
    asset: "NIFTY",
    title: "Nifty Up / Down",
    body: "Predict whether the NEXT 15-minute window closes higher or lower than this one. Result lands at the next window's close.",
    ticket: "◉ 600 / ticket",
    payout: "Win pay 1.6666 → ◉ 1,000",
    window: "15-min rounds · 09:15 – 15:15",
  },
  {
    icon: Bitcoin,
    asset: "BTC",
    title: "BTC Up / Down",
    body: "The same 15-minute call on Bitcoin — and because crypto never sleeps, the rounds run almost round the clock.",
    ticket: "◉ 600 / ticket",
    payout: "Win pay 1.6666 → ◉ 1,000",
    window: "15-min rounds · 00:00 – 22:30",
  },
  {
    icon: Hash,
    asset: "NIFTY",
    title: "Nifty Number",
    body: "Pick one or more decimals (.00 to .95). You win if NIFTY's closing decimals at result time match your number.",
    ticket: "◉ 675 / ticket",
    payout: "◉ 10,000/-",
    window: "Bids till 15:15 · result 15:45",
  },
  {
    icon: Bitcoin,
    asset: "BTC",
    title: "BTC Number",
    body: "Guess the last two digits of Bitcoin's price at result time. Full .00–.99 board, so every number is in play.",
    ticket: "◉ 675 / ticket",
    payout: "◉ 40,000/=",
    window: "00:00 – 21:00 · result 23:00 LTP",
  },
  {
    icon: Split,
    asset: "NIFTY",
    title: "Nifty Bracket",
    body: "Buy or Sell a band anchored to spot. A 20-point bracket around the live price decides the outcome at session close.",
    ticket: "◉ 1,125 / ticket",
    payout: "Win pay 1,125 → ◉ 2,000/-",
    window: "09:15 – 3:30 · result 3:31",
  },
  {
    icon: Trophy,
    asset: "NIFTY",
    title: "Nifty Jackpot",
    body: "Call the closing price outright. The 20 closest predictions share the prize pool — rank 1 takes 45% of the bank.",
    ticket: "◉ 1,100 / ticket",
    payout: "Top 20 share the pool",
    window: "09:15 – 3:00 · result 3:45",
  },
  {
    icon: Trophy,
    asset: "BTC",
    title: "BTC Jackpot",
    body: "Predict Bitcoin's price at result time and split the bank with the other closest calls. Same top-20 prize ladder.",
    ticket: "◉ 1,100 / ticket",
    payout: "Top 20 share the pool",
    window: "00:50 – 21:00 · result 23:00 LTP",
  },
];

const STATS = [
  { value: "7", label: "Live games", sub: "NIFTY and Bitcoin formats" },
  { value: "15 min", label: "Fastest round", sub: "Up / Down settles every window" },
  { value: "◉ 10,000", label: "Number game payout", sub: "Per winning ticket" },
  { value: "Auto", label: "Result settlement", sub: "Read straight off the live feed" },
];

const STEPS = [
  {
    icon: Wallet,
    step: "01",
    title: "Move coins into Games",
    body: "Games run on a separate Games Coins balance. Transfer from your main wallet in one tap — and move winnings back the same way, any time.",
  },
  {
    icon: Gamepad2,
    step: "02",
    title: "Pick a game and your tickets",
    body: "Choose a format, set how many tickets you want, and place the bid before the window's cut-off. Every stake and payout is shown before you confirm.",
  },
  {
    icon: Zap,
    step: "03",
    title: "Result settles itself",
    body: "At result time the engine reads the official NIFTY close or the live BTC price and credits winners automatically. No claiming, no waiting on support.",
  },
];

const WHY = [
  {
    icon: ShieldCheck,
    title: "Settled on the real feed",
    body: "Outcomes are resolved from the same live NSE and crypto price feed that powers the trading terminal — not a number we make up.",
  },
  {
    icon: Coins,
    title: "A wallet of its own",
    body: "Games Coins sit in a separate balance from your trading funds, so a game round can never touch the margin behind an open position.",
  },
  {
    icon: Clock,
    title: "Results you don't wait for",
    body: "Up/Down settles every 15 minutes; Number, Bracket and Jackpot settle the same session. Full history stays in your bet log and ledger.",
  },
];

export default function NiftyGamesPage() {
  return (
    <>
      <MpPageHero
        eyebrow="Nifty Games"
        title="The market, in a shorter format"
        lead="Up/Down calls, closing-decimal Numbers, Brackets and Jackpots — seven games on live NIFTY and Bitcoin prices, settled automatically the moment the window closes."
        media={
          // 1454x1082 — effectively the 4:3 frame the hero slot reserves,
          // so it fills without cropping.
          <img
            src="/images/games_img.png"
            alt="Nifty and Bitcoin prediction games"
            width={1454}
            height={1082}
            className="w-full rounded-2xl object-cover aspect-[4/3]"
          />
        }
      >
        <MpButton href="/register" size="lg">
          Start Playing
          <ArrowRight className="size-4" />
        </MpButton>
        <MpButton href="/login" size="lg" variant="secondary">
          I already have an account
        </MpButton>
      </MpPageHero>

      {/* At a glance */}
      <MpSection>
        <MpStatGrid items={STATS} />
      </MpSection>

      {/* The games */}
      <MpSection>
        <MpHeading
          eyebrow="Game formats"
          title="7 Live Games"
          lead="Every game runs on Games Coins (◉) and settles against the live feed. Ticket prices and payouts below are the platform defaults — your broker can tune them per game."
        />
        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {GAMES.map((g) => (
            <MpCard key={g.title} className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <span className="grid size-11 place-items-center rounded-xl bg-mp-primary/10 text-mp-primary">
                  <g.icon className="size-5" />
                </span>
                <span className="rounded-full bg-mp-surface-2 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-mp-text-mut">
                  {g.asset}
                </span>
              </div>
              <h3 className="font-display text-lg font-semibold leading-snug text-mp-text">
                {g.title}
              </h3>
              <p className="text-sm leading-[1.6] text-mp-text-mut">{g.body}</p>
              <dl className="mt-1 flex flex-col gap-1.5 border-t border-mp-border pt-3 text-xs">
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-mp-text-mut">Ticket</dt>
                  <dd className="font-semibold text-mp-text">{g.ticket}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-mp-text-mut">Win pays</dt>
                  <dd className="font-semibold text-mp-primary">{g.payout}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-mp-text-mut">Window</dt>
                  <dd className="text-right font-medium text-mp-text">{g.window}</dd>
                </div>
              </dl>
              <MpButton href="/register" variant="secondary" className="mt-auto w-full">
                Play Now
                <ArrowRight className="size-4" />
              </MpButton>
            </MpCard>
          ))}
        </div>
      </MpSection>

      {/* How it works */}
      <MpSection light>
        <MpHeading eyebrow="How it works" title="Three steps to your first ticket" />
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {STEPS.map((s) => (
            <MpCard key={s.step} className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <span className="grid size-11 place-items-center rounded-xl bg-mp-primary/10 text-mp-primary">
                  <s.icon className="size-5" />
                </span>
                <span className="mp-num font-display text-2xl font-bold text-mp-border">
                  {s.step}
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

      {/* Why play here */}
      <MpSection>
        <MpHeading
          align="center"
          eyebrow="Why StockEx Games"
          title="Built on the same engine as the terminal"
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
      <MpSection light>
        <div className="flex flex-col items-center gap-6 text-center">
          <span className="grid size-12 place-items-center rounded-2xl bg-mp-primary/10 text-mp-primary">
            <Gamepad2 className="size-6" />
          </span>
          <MpHeading
            align="center"
            title="Your first round is 15 minutes away"
            lead="Open an account, move a few coins across, and take your first Up/Down call on the next window."
          />
          <MpButton href="/register" size="lg">
            Start Playing
            <ArrowRight className="size-4" />
          </MpButton>
          <p className="max-w-2xl text-sm leading-[1.6] text-mp-text-mut">
            Games involve financial risk and can be habit-forming. Play only
            with money you can afford to lose, and only if games are permitted
            where you live. Ticket prices, payouts and game availability are set
            by your broker and can change. Games are not investment products —
            trading in the securities market is separately subject to market
            risks; read all related documents carefully before investing.
          </p>
        </div>
      </MpSection>
    </>
  );
}
