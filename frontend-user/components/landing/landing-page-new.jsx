"use client";

import { Navbar } from "@/components/landing/navbar";
import { HeroSection } from "@/components/landing/hero-section";
import { LiveTicker } from "@/components/landing/live-ticker";
import { MarketAccessSection } from "@/components/landing/market-access-section";
import { PricingTableSection } from "@/components/landing/pricing-table-section";
import { EconomicCalendarSection } from "@/components/landing/economic-calendar-section";
import { TradingToolsSection } from "@/components/landing/trading-tools-section";
import { QuestionnaireSection } from "@/components/landing/questionnaire-section";
import { DemoTradingSection } from "@/components/landing/demo-trading-section";
import { AccountsSection } from "@/components/landing/accounts-section";
import { PlatformSection } from "@/components/landing/platform-section";
import { CapitalSection } from "@/components/landing/capital-section";
import { PartnershipSection } from "@/components/landing/partnership-section";
import { StatisticsSection } from "@/components/landing/statistics-section";
import { SupportSection } from "@/components/landing/support-section";
import { Footer } from "@/components/landing/footer";

export default function LandingPageNew() {
  return (
    // NO top padding. The nav is a floating pill with its own opaque
    // background, so it overlays the hero video rather than being pushed
    // clear of it. Reserving 70px for it left a white band across the full
    // width above the video — visible either side of the pill, since the
    // pill is only `max-w-6xl`. The video now runs edge-to-edge from y=0.
    <main className="stockex-landing min-h-screen bg-white">
      <div className="fixed top-0 left-0 right-0 z-50">
        <Navbar embedded />
      </div>
      <HeroSection />
      {/* Ticker rides directly under the hero video — a dark strip between
          the video and the first light section, rather than a permanently
          pinned bar competing with the nav for the top of the screen. */}
      <LiveTicker />
      <AccountsSection />
      <MarketAccessSection />
      <PricingTableSection />
      <EconomicCalendarSection />
      <TradingToolsSection />
      <QuestionnaireSection />
      <DemoTradingSection />
      <PlatformSection />
      <CapitalSection />
      <PartnershipSection />
      <StatisticsSection />
      <SupportSection />
      <Footer />
    </main>
  );
}
