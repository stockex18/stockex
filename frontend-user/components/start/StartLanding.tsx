"use client";

import Link from "next/link";
import {
  BarChart3,
  Bitcoin,
  CandlestickChart,
  Coins,
  Gauge,
  Globe2,
  Headset,
  LineChart,
  Plus,
  ShieldCheck,
  Smartphone,
  Wallet,
} from "lucide-react";
import { LiveTicker } from "@/components/landing/live-ticker";
import { LeadForm, useLeadTags } from "./LeadForm";

// Copy rule for this page: say only what the platform actually does. No user
// counts, ratings or testimonials until there are real ones to quote -- an
// invented number on a broker's ad page is worse than no number.

const MARKETS = [
  { icon: CandlestickChart, name: "NSE / BSE", note: "Stocks & futures" },
  { icon: BarChart3, name: "F&O", note: "Index & stock options" },
  { icon: Coins, name: "MCX", note: "Gold, silver, crude & more" },
  { icon: Globe2, name: "Forex", note: "Major currency pairs" },
  { icon: Bitcoin, name: "Crypto", note: "Bitcoin, Ethereum & more" },
];

const BENEFITS = [
  {
    icon: Wallet,
    title: "Free demo account",
    body: "Every new account starts on demo with a virtual balance. Learn the platform without risking a rupee.",
  },
  {
    icon: LineChart,
    title: "Live market prices",
    body: "Real-time prices from the exchange feed, with charts, watchlists and price alerts.",
  },
  {
    icon: Smartphone,
    title: "One app, every device",
    body: "Trade from your phone or laptop. Install it on your home screen in one tap.",
  },
  {
    icon: Headset,
    title: "Help when you need it",
    body: "A real person to talk to — on call or WhatsApp — from signup to your first trade.",
  },
];

const STEPS = [
  { n: "1", title: "Sign up in a minute", body: "Name, mobile and email. Your demo account opens instantly." },
  { n: "2", title: "Practise on demo", body: "Place trades with virtual money and learn how everything works." },
  { n: "3", title: "Go live when ready", body: "Switch to a real account whenever you choose. No pressure." },
];

const FAQ = [
  {
    q: "Is opening an account free?",
    a: "Yes. Signing up is free and your account opens as a demo account with a virtual balance, so you can practise first.",
  },
  {
    q: "What can I trade on StockEx?",
    a: "Indian stocks and futures on NSE and BSE, F&O, commodities on MCX, Forex and Crypto — all from one app.",
  },
  {
    q: "Do I need to download anything?",
    a: "No. StockEx runs in your browser on any phone or computer, and you can add it to your home screen like an app.",
  },
  {
    q: "Why do you ask for an SMS code?",
    a: "It confirms the number is really yours, so our team calls the right person — and nobody can request calls in your name.",
  },
  {
    q: "What happens after I request a callback?",
    a: "Someone from our team calls you to answer your questions and help you get started. There is no obligation to open an account.",
  },
];

function registerHref(ref?: string) {
  return ref ? `/register?ref=${encodeURIComponent(ref)}` : "/register";
}

export function StartLanding() {
  const tags = useLeadTags();
  const signup = registerHref(tags.ref_code);

  return (
    <div className="sx-start pb-24 md:pb-0">
      {/* ── Header: logo and one action. No menu -- nothing to wander off to. */}
      <header className="sticky top-0 z-30 border-b border-[var(--sx-line)] bg-[#0a1020]/80 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 md:px-6">
          <Link href="/" className="flex items-center gap-2.5" aria-label="StockEx home">
            {/* The logo file is a square: emblem on top, a dark-blue wordmark
                and a black tagline below. Shrunk whole into a header, the
                wordmark is unreadable on navy, so only the emblem is shown
                (cropped from the top of the file) and the name is set as text. */}
            <span className="relative block h-10 w-12 shrink-0 overflow-hidden" aria-hidden="true">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/images/stockexlogoenhanced.png"
                alt=""
                className="absolute left-[-7px] top-[-4px] h-[68px] w-[68px] max-w-none"
              />
            </span>
            <span className="font-display text-xl font-bold tracking-tight text-white">
              Stock<span className="text-[var(--sx-ok)]">Ex</span>
            </span>
          </Link>
          <div className="flex items-center gap-2">
            <Link href="/login" className="hidden px-3 text-sm text-[var(--sx-text-2)] hover:text-white sm:inline">
              Log in
            </Link>
            <Link href={signup} className="sx-btn sx-btn-primary !h-10 !px-4 text-sm">
              Open free account
            </Link>
          </div>
        </div>
      </header>

      {/* ── Hero */}
      <section className="mx-auto grid max-w-6xl gap-10 px-4 pb-14 pt-10 md:grid-cols-[1.1fr_0.9fr] md:px-6 md:pt-16">
        {/* Top-aligned, not centred: the form beside it is taller than the
            viewport, and centring pushed this copy below the fold. Sticky so it
            stays in view while the visitor scrolls through the form. */}
        <div className="flex flex-col md:sticky md:top-24 md:self-start">
          <p className="sx-eyebrow">Stocks · F&amp;O · MCX · Forex · Crypto</p>
          <h1 className="mt-3 font-display text-4xl font-bold leading-[1.08] tracking-tight md:text-6xl">
            Every market you trade, <span className="text-[var(--sx-accent-light)]">in one app.</span>
          </h1>
          <p className="mt-5 max-w-xl text-base text-[var(--sx-text-2)] md:text-lg">
            Practise free on a demo account with a virtual balance, then go live when you&apos;re ready. Live prices,
            fast orders, and a team that picks up the phone.
          </p>
          <div className="mt-7 flex flex-col gap-3 sm:flex-row">
            <Link href={signup} className="sx-btn sx-btn-primary">
              Open free account
            </Link>
            <Link href="/" className="sx-btn sx-btn-ghost">
              Visit site
            </Link>
            {/* Wrapped: `.sx-btn` sets display and would beat `md:hidden`. On
                desktop the form is already beside this, so no button for it. */}
            <div className="flex md:hidden">
              <a href="#callback" className="sx-btn sx-btn-ghost w-full">
                Request a callback
              </a>
            </div>
          </div>
          <ul className="mt-7 flex flex-wrap gap-x-6 gap-y-2 text-sm text-[var(--sx-text-2)]">
            <li className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-[var(--sx-ok)]" /> Free demo account</li>
            <li className="flex items-center gap-2"><Gauge className="h-4 w-4 text-[var(--sx-ok)]" /> Live exchange prices</li>
            <li className="flex items-center gap-2"><Headset className="h-4 w-4 text-[var(--sx-ok)]" /> Call &amp; WhatsApp support</li>
          </ul>
        </div>

        <div id="callback" className="sx-card scroll-mt-24 p-5 md:p-7">
          <LeadForm tags={tags} />
        </div>
      </section>

      <LiveTicker />

      {/* ── Markets */}
      <section className="mx-auto max-w-6xl px-4 py-16 md:px-6">
        <p className="sx-eyebrow text-center">What you can trade</p>
        <h2 className="mt-2 text-center font-display text-3xl font-bold md:text-4xl">Five markets. One login.</h2>
        <div className="mt-10 grid grid-cols-2 gap-3 md:grid-cols-5">
          {MARKETS.map(({ icon: Icon, name, note }) => (
            <div key={name} className="sx-card flex flex-col items-center gap-2 p-5 text-center">
              <Icon className="h-7 w-7 text-[var(--sx-accent-light)]" />
              <p className="font-semibold">{name}</p>
              <p className="text-xs text-[var(--sx-text-3)]">{note}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Why StockEx */}
      <section className="mx-auto max-w-6xl px-4 pb-16 md:px-6">
        <p className="sx-eyebrow text-center">Why StockEx</p>
        <h2 className="mt-2 text-center font-display text-3xl font-bold md:text-4xl">Built for how you actually trade</h2>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {BENEFITS.map(({ icon: Icon, title, body }) => (
            <div key={title} className="sx-card p-6">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[var(--sx-accent)]/15">
                <Icon className="h-5 w-5 text-[var(--sx-accent-light)]" />
              </div>
              <p className="mt-4 font-semibold">{title}</p>
              <p className="mt-2 text-sm leading-relaxed text-[var(--sx-text-2)]">{body}</p>
            </div>
          ))}
        </div>
        <div className="mt-8 flex justify-center">
          <Link href={signup} className="sx-btn sx-btn-primary">Open free account</Link>
        </div>
      </section>

      {/* ── How it works */}
      <section className="border-y border-[var(--sx-line)] bg-[var(--sx-bg-2)]/60">
        <div className="mx-auto max-w-6xl px-4 py-16 md:px-6">
          <p className="sx-eyebrow text-center">How it works</p>
          <h2 className="mt-2 text-center font-display text-3xl font-bold md:text-4xl">Start in three steps</h2>
          <ol className="mt-10 grid gap-4 md:grid-cols-3">
            {STEPS.map((s) => (
              <li key={s.n} className="sx-card p-6">
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[var(--sx-accent)] font-bold text-white">
                  {s.n}
                </span>
                <p className="mt-4 font-semibold">{s.title}</p>
                <p className="mt-2 text-sm text-[var(--sx-text-2)]">{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── FAQ + second form */}
      <section className="mx-auto grid max-w-6xl gap-10 px-4 py-16 md:grid-cols-2 md:px-6">
        <div>
          <p className="sx-eyebrow">Questions</p>
          <h2 className="mt-2 font-display text-3xl font-bold">Frequently asked</h2>
          <div className="mt-6 divide-y divide-[var(--sx-line)] border-y border-[var(--sx-line)]">
            {FAQ.map(({ q, a }) => (
              <details key={q} className="group py-4">
                <summary className="flex items-center justify-between gap-4 font-medium">
                  {q}
                  <Plus className="sx-faq-icon h-4 w-4 shrink-0 text-[var(--sx-text-3)] transition-transform" />
                </summary>
                <p className="mt-2 text-sm leading-relaxed text-[var(--sx-text-2)]">{a}</p>
              </details>
            ))}
          </div>
        </div>
        <div className="sx-card h-fit p-5 md:p-7">
          <p className="text-lg font-semibold">Still have questions?</p>
          <p className="mb-4 text-sm text-[var(--sx-text-2)]">Leave your number and we&apos;ll call you.</p>
          <LeadForm tags={tags} compact />
        </div>
      </section>

      {/* ── Footer: disclaimer and policies */}
      <footer className="border-t border-[var(--sx-line)]">
        <div className="mx-auto max-w-6xl px-4 py-8 text-xs leading-relaxed text-[var(--sx-text-3)] md:px-6">
          <p>
            <strong className="text-[var(--sx-text-2)]">Risk disclosure:</strong> Trading in stocks, derivatives,
            commodities, currencies and crypto involves substantial risk of loss and is not suitable for every
            investor. Past performance is not indicative of future results. Demo trading uses virtual money and does
            not guarantee similar results in live trading.
          </p>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <span>© {new Date().getFullYear()} StockEx</span>
            <nav className="flex gap-4">
              <Link href="/" className="hover:text-white">Home</Link>
              <Link href="/login" className="hover:text-white">Log in</Link>
            </nav>
          </div>
        </div>
      </footer>

      {/* ── Mobile: the two actions are always one tap away. */}
      <div className="fixed inset-x-0 bottom-0 z-40 flex gap-2 border-t border-[var(--sx-line)] bg-[#0a1020]/95 p-3 backdrop-blur md:hidden">
        <a href="#callback" className="sx-btn sx-btn-ghost flex-1 !px-3 text-sm">Request callback</a>
        <Link href={signup} className="sx-btn sx-btn-primary flex-1 !px-3 text-sm">Open free account</Link>
      </div>
    </div>
  );
}
