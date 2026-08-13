"use client";

import { useMemo, useState } from "react";
import { MpCard } from "@/components/marketing/mp-ui";
import {
  ResultRow,
  ToolDisclaimer,
  ToolField,
  ToolNumber,
  ToolSelect,
  ToolToggle,
} from "./ToolBits";
import {
  brokerageForLeg,
  formatMoney,
  formatNumber,
  marginRequired,
  money,
  profitAndLoss,
  type CommissionType,
  type MarginMode,
} from "@/lib/tools/charges";

const TYPES: { value: CommissionType; label: string }[] = [
  { value: "PER_LOT", label: "Per lot" },
  { value: "PERCENTAGE", label: "Percentage" },
  { value: "FLAT", label: "Flat" },
  { value: "PER_CRORE", label: "Per crore" },
];

const MARGIN_MODES: { value: MarginMode; label: string }[] = [
  { value: "times", label: "Leverage (×)" },
  { value: "percent", label: "% of notional" },
  { value: "fixed", label: "🪙 per lot" },
];

export function PnlCalculator() {
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [entry, setEntry] = useState(24600);
  const [exit, setExit] = useState(24750);
  const [qty, setQty] = useState(75);
  const [lotSize, setLotSize] = useState(75);

  const [type, setType] = useState<CommissionType>("PER_LOT");
  const [rate, setRate] = useState(20);

  const [marginMode, setMarginMode] = useState<MarginMode>("times");
  const [marginValue, setMarginValue] = useState(10);

  const r = useMemo(() => {
    // Brokerage is charged per FILL, so a round trip is entry + exit. Each
    // leg is priced at its own traded price, exactly as the matching engine
    // charges it — not both legs at the entry price.
    const openLeg = brokerageForLeg({ qty, price: entry, lotSize, type, value: rate });
    const closeLeg = brokerageForLeg({ qty, price: exit, lotSize, type, value: rate });
    const roundTrip = money(openLeg + closeLeg);

    const pnl = profitAndLoss({ side, entry, exit, qty, brokerageRoundTrip: roundTrip });
    const m = marginRequired({ qty, price: entry, lotSize, mode: marginMode, value: marginValue });

    return {
      ...pnl,
      openLeg,
      closeLeg,
      margin: m.margin,
      notional: m.notional,
      // Return is measured against the capital actually blocked (margin),
      // which is what the trader put at risk — not the full notional.
      returnOnMargin: m.margin > 0 ? (pnl.net / m.margin) * 100 : 0,
      returnOnNotional: m.notional > 0 ? (pnl.net / m.notional) * 100 : 0,
    };
  }, [side, entry, exit, qty, lotSize, type, rate, marginMode, marginValue]);

  const win = r.net >= 0;

  return (
    <div className="grid gap-6 lg:grid-cols-[1.15fr_1fr]">
      <MpCard hover={false} className="flex flex-col gap-5">
        <h2 className="font-display text-lg font-semibold text-mp-text">
          Your position
        </h2>

        <ToolField label="Direction">
          <ToolToggle
            value={side}
            onChange={setSide}
            options={[
              { value: "BUY", label: "Buy / Long" },
              { value: "SELL", label: "Sell / Short" },
            ]}
          />
        </ToolField>

        <div className="grid gap-4 sm:grid-cols-2">
          <ToolField label="Entry price (₹)">
            <ToolNumber value={entry} onChange={setEntry} />
          </ToolField>
          <ToolField label="Exit price (₹)">
            <ToolNumber value={exit} onChange={setExit} />
          </ToolField>
          <ToolField label="Quantity">
            <ToolNumber value={qty} onChange={setQty} />
          </ToolField>
          <ToolField label="Lot size" hint="1 for cash-segment stocks.">
            <ToolNumber value={lotSize} onChange={setLotSize} min={1} />
          </ToolField>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <ToolField label="Brokerage type">
            <ToolSelect value={type} onChange={setType} options={TYPES} />
          </ToolField>
          <ToolField label="Rate">
            <ToolNumber value={rate} onChange={setRate} />
          </ToolField>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <ToolField label="Margin basis">
            <ToolSelect value={marginMode} onChange={setMarginMode} options={MARGIN_MODES} />
          </ToolField>
          <ToolField
            label={marginMode === "times" ? "Leverage (×)" : marginMode === "percent" ? "Margin %" : "Margin per lot (₹)"}
          >
            <ToolNumber value={marginValue} onChange={setMarginValue} />
          </ToolField>
        </div>
      </MpCard>

      <div className="flex flex-col gap-4">
        <MpCard hover={false} className="flex flex-col">
          <h2 className="font-display text-lg font-semibold text-mp-text">
            Result
          </h2>
          <div className="mt-3 flex flex-col">
            <ResultRow
              label="Price move"
              value={`${r.pointMove >= 0 ? "+" : ""}${formatNumber(r.pointMove, 2)} pts`}
              tone="muted"
            />
            <ResultRow
              label="Gross P&L"
              value={formatMoney(r.gross)}
              tone={r.gross >= 0 ? "up" : "down"}
            />
            <ResultRow label="Brokerage — entry" value={`− ${formatMoney(r.openLeg)}`} tone="muted" />
            <ResultRow label="Brokerage — exit" value={`− ${formatMoney(r.closeLeg)}`} tone="muted" />
            <ResultRow
              label="Net P&L"
              value={formatMoney(r.net)}
              tone={win ? "up" : "down"}
              strong
            />
          </div>
        </MpCard>

        <MpCard hover={false} className="flex flex-col">
          <h3 className="font-display text-base font-semibold text-mp-text">
            Against your capital
          </h3>
          <div className="mt-2 flex flex-col">
            <ResultRow label="Notional value" value={formatMoney(r.notional)} tone="muted" />
            <ResultRow label="Margin blocked" value={formatMoney(r.margin)} />
            <ResultRow
              label="Return on margin"
              value={`${r.returnOnMargin >= 0 ? "+" : ""}${formatNumber(r.returnOnMargin, 2)}%`}
              tone={r.returnOnMargin >= 0 ? "up" : "down"}
            />
            <ResultRow
              label="Return on notional"
              value={`${r.returnOnNotional >= 0 ? "+" : ""}${formatNumber(r.returnOnNotional, 2)}%`}
              tone="muted"
            />
            <ResultRow
              label="Break-even exit"
              value={formatMoney(r.breakeven)}
              tone="muted"
            />
          </div>
        </MpCard>
      </div>

      <div className="lg:col-span-2">
        <ToolDisclaimer>
          Brokerage is charged on <strong className="text-mp-text">both</strong>{" "}
          legs, each at its own traded price — the same way the matching engine
          bills a fill. Leverage cuts both ways: the return-on-margin figure is
          large precisely because the capital blocked is small, and a move
          against you scales identically. This platform charges brokerage only —
          no STT, GST or stamp duty is added.
        </ToolDisclaimer>
      </div>
    </div>
  );
}
