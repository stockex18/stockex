import type { Metadata } from "next";
import { ArrowRight } from "lucide-react";
import { MpButton, MpPageHero, MpSection } from "@/components/marketing/mp-ui";
import { PnlCalculator } from "@/components/marketing/tools/PnlCalculator";
import { ToolsNav } from "@/components/marketing/tools/ToolsNav";

export const metadata: Metadata = {
  title: "Profit & Loss Calculator — Size a Trade Before You Place It | StockEx",
  description:
    "Estimate gross and net P&L on a long or short position, with brokerage on both legs, margin blocked, return on capital and the break-even exit price.",
};

export default function PnlCalculatorPage() {
  return (
    <>
      <MpPageHero
        eyebrow="Tools"
        title="Profit & loss calculator"
        lead="Run the trade before you place it — net of brokerage on both legs, measured against the capital actually blocked."
      >
        <MpButton href="/register" size="lg">
          Open an Account
          <ArrowRight className="size-4" />
        </MpButton>
      </MpPageHero>

      <MpSection light>
        <ToolsNav current="/tools/profit-loss-calculator" />
        <div className="mt-8">
          <PnlCalculator />
        </div>
      </MpSection>
    </>
  );
}
