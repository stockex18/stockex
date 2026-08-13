import type { Metadata } from "next";
import { ArrowRight } from "lucide-react";
import { MpButton, MpPageHero, MpSection } from "@/components/marketing/mp-ui";
import { MarginCalculator } from "@/components/marketing/tools/MarginCalculator";
import { ToolsNav } from "@/components/marketing/tools/ToolsNav";

export const metadata: Metadata = {
  title: "Margin Calculator — Intraday & Carry-Forward Requirements | StockEx",
  description:
    "Calculate the margin a position blocks on NIFTY, BANKNIFTY, stocks and MCX contracts — leverage, percent-of-notional or fixed-per-lot, intraday and overnight.",
};

export default function MarginCalculatorPage() {
  return (
    <>
      <MpPageHero
        eyebrow="Tools"
        title="Margin calculator"
        lead="See what a position blocks intraday and overnight, whether your balance covers it, and how many lots it really supports."
      >
        <MpButton href="/register" size="lg">
          Open an Account
          <ArrowRight className="size-4" />
        </MpButton>
      </MpPageHero>

      <MpSection>
        <ToolsNav current="/tools/margin-calculator" />
        <div className="mt-8">
          <MarginCalculator />
        </div>
      </MpSection>
    </>
  );
}
