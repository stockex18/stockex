import type { Metadata } from "next";
import { ArrowRight } from "lucide-react";
import {
  MpButton,
  MpPageHero,
  MpSection,
} from "@/components/marketing/mp-ui";
import { BrokerageCalculator } from "@/components/marketing/tools/BrokerageCalculator";
import { ToolsNav } from "@/components/marketing/tools/ToolsNav";

export const metadata: Metadata = {
  title: "Brokerage Calculator — Know Your Exact Trading Cost | StockEx",
  description:
    "Work out the brokerage on any Equity, F&O, Commodity or Currency trade. Per-lot, percentage, flat and per-crore rates, with the break-even move the position needs to clear.",
};

export default function BrokerageCalculatorPage() {
  return (
    <>
      <MpPageHero
        eyebrow="Tools"
        title="Brokerage calculator"
        lead="Enter the trade, see exactly what it costs — both legs, and the move the price has to make before you're even."
      >
        <MpButton href="/register" size="lg">
          Open an Account
          <ArrowRight className="size-4" />
        </MpButton>
      </MpPageHero>

      <MpSection>
        <ToolsNav current="/tools/brokerage-calculator" />
        <div className="mt-8">
          <BrokerageCalculator />
        </div>
      </MpSection>
    </>
  );
}
