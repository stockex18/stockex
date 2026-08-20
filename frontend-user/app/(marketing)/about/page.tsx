import type { Metadata } from "next";
import { ArrowRight } from "lucide-react";
import {
  MpButton,
  MpCard,
  MpHeading,
  MpPageHero,
  MpProse,
  MpSection,
  MpImagePlaceholder,
} from "@/components/marketing/mp-ui";

export const metadata: Metadata = {
  title: "About StockEx — A Transparent Stock Broker, Built in India",
  description:
    "StockEx is a stock broker built in India to give every investor professional-grade tools and honest, transparent pricing.",
};

const BELIEFS = [
  "Investing should be simple. Clear pricing, plain language, no fine-print surprises.",
  "Every charge stated up front, in Stock Coins.",
  "Technology should help, not get in the way. Fast execution and tools that work when it matters.",
  "We earn your trust on every order and every settlement, not just on day one.",
];

export default function AboutPage() {
  return (
    <>
      <MpPageHero
        eyebrow="About"
        title="A transparent stock broker, built in India."
        lead="We're a team of traders and engineers in India who believe investing should be simple, transparent and fair. We built StockEx to give every Indian investor professional-grade tools and honest pricing across NSE, BSE & MCX."
        media={null}
      >
        <MpButton href="/register" size="lg">
          Open Account
          <ArrowRight className="size-4" />
        </MpButton>
        <MpButton href="/contact" variant="secondary" size="lg" className="border-mp-border text-mp-text">
          Talk to us
        </MpButton>
      </MpPageHero>

      {/* Our story */}
      <MpSection>
        <MpHeading eyebrow="Our story" title="Why we built this" />
        <div className="mt-8 flex flex-col gap-6">
          <MpProse>
            Most of us traded and invested in Indian markets for years before
            this. We were tired of platforms with hidden charges, confusing
            interfaces and support that never replied. When we sat down to build
            StockEx, the goal was simple: build the broker we always wished
            we had.
          </MpProse>
          <MpProse>
            So we priced everything transparently in Stock Coins with instant
            funding, put the full Indian market — Equity, F&O, Commodities, IPOs
            and Mutual Funds — into one account, and built fast, reliable tools
            on top. We earn your trust on every order and every settlement.
          </MpProse>

          {/* Reserved for the team / office photo. Uses the same
              MpImagePlaceholder the hero already uses, so an unfilled slot
              looks deliberate. It holds its final size via aspect-ratio —
              dropping the picture in later shifts nothing below it. Swap
              this element for:
                <img src="/images/about-story.jpg" alt="…"
                     className="w-full rounded-2xl object-cover aspect-[16/9]" /> */}
          <MpImagePlaceholder ratio="16/9" label="About / team photo" />
        </div>
      </MpSection>

      {/* What we believe */}
      <MpSection light>
        <MpHeading eyebrow="What we believe" title="What we stand for" />
        <div className="mt-10 grid gap-5 sm:grid-cols-2">
          {BELIEFS.map((b) => (
            <MpCard key={b} className="flex flex-col gap-2">
              <p className="text-base leading-[1.6] text-mp-text">{b}</p>
            </MpCard>
          ))}
        </div>
      </MpSection>

      {/* Where we are */}
      <MpSection>
        <MpHeading eyebrow="Where we are" title="Where we're based" />
        <MpProse className="mt-6">
          Based in India, with support during IST hours in English and Hindi.
          Built for traders here, open to traders everywhere.
        </MpProse>
        <div className="mt-8 flex flex-col gap-3 sm:flex-row">
          <MpButton href="/register">
            Open Account
            <ArrowRight className="size-4" />
          </MpButton>
          <MpButton href="/contact" variant="secondary">
            Talk to us
          </MpButton>
        </div>
      </MpSection>
    </>
  );
}
