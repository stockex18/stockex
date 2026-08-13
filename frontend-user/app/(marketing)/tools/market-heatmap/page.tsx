import type { Metadata } from "next";
import { ArrowRight } from "lucide-react";
import { MpButton, MpPageHero, MpSection } from "@/components/marketing/mp-ui";
import { MarketHeatmap } from "@/components/marketing/tools/MarketHeatmap";
import { ToolsNav } from "@/components/marketing/tools/ToolsNav";

export const metadata: Metadata = {
  title: "Market Heatmap — Sector Performance at a Glance | StockEx",
  description:
    "See how the Indian market is moving sector by sector — banking, IT, energy, auto, FMCG, pharma and metals — with gainers and losers ranked across the board.",
};

export default function MarketHeatmapPage() {
  return (
    <>
      <MpPageHero
        eyebrow="Tools"
        title="Market heatmap"
        lead="Where the money went today — every major sector on one board, with the day's biggest moves ranked across the whole market."
      >
        <MpButton href="/register" size="lg">
          Trade the Move
          <ArrowRight className="size-4" />
        </MpButton>
      </MpPageHero>

      <MpSection>
        <ToolsNav current="/tools/market-heatmap" />
        <div className="mt-8">
          <MarketHeatmap />
        </div>
      </MpSection>
    </>
  );
}
