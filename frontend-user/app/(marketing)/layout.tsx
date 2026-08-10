import type { Metadata } from "next";
// ONE nav for the whole site. The marketing pages used to render their own
// `MarketingNav` (white pill, green wordmark) while the landing page
// rendered `Navbar` (ink pill, lime accents), so the header visibly
// changed identity the moment you clicked any menu item. Same component
// both places now — MarketingNav is no longer used anywhere.
import { Navbar } from "@/components/landing/navbar";
import { MarketingFooter } from "@/components/marketing/MarketingFooter";

export const metadata: Metadata = {
  title: "StockEx — Trade Equity, F&O, Commodities & IPOs on NSE, BSE & MCX",
  description:
    "A SEBI-registered stock broker for Indian markets. Trade Equity, F&O, Commodities, IPOs and Mutual Funds with transparent pricing and a modern platform.",
};

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // `mp-scope` activates the locked StockEx marketing palette (light
  // default + dark sections) without touching the trading app's tokens.
  return (
    <div className="mp-scope flex min-h-screen flex-col overflow-x-hidden bg-mp-bg text-mp-text">
      <Navbar />
      <main className="flex-1">{children}</main>
      <MarketingFooter />
    </div>
  );
}
