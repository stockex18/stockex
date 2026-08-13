"use client";

import { useMemo, useState } from "react";
import { MpCard } from "@/components/marketing/mp-ui";
import {
  ResultRow,
  ToolDisclaimer,
  ToolField,
  ToolNumber,
  ToolSelect,
} from "./ToolBits";
import {
  brokerageForLeg,
  formatMoney,
  formatNumber,
  money,
  type CommissionType,
} from "@/lib/tools/charges";

/* Segment presets. Lot sizes are the standard NSE/MCX contract sizes; the
   commission defaults mirror the shipped BrokeragePlan seed shape (a
   per-lot charge on derivatives, a percentage on cash). Every field stays
   editable because the real number is whatever the user's broker has
   configured — the calculator's job is the arithmetic, not the rate card. */
const SEGMENTS = [
  { value: "EQUITY", label: "Equity (NSE / BSE)", lotSize: 1, type: "PERCENTAGE" as CommissionType, rate: 0.03 },
  { value: "FUTURES", label: "Futures (NFO)", lotSize: 75, type: "PER_LOT" as CommissionType, rate: 20 },
  { value: "OPTIONS", label: "Options (NFO)", lotSize: 75, type: "PER_LOT" as CommissionType, rate: 20 },
  { value: "COMMODITY", label: "Commodity (MCX)", lotSize: 100, type: "PER_LOT" as CommissionType, rate: 25 },
  { value: "CURRENCY", label: "Currency (CDS)", lotSize: 1000, type: "PER_LOT" as CommissionType, rate: 15 },
];

const TYPES: { value: CommissionType; label: string }[] = [
  { value: "PER_LOT", label: "Per lot (🪙 per lot)" },
  { value: "PERCENTAGE", label: "Percentage (% of turnover)" },
  { value: "FLAT", label: "Flat (🪙 per order)" },
  { value: "PER_CRORE", label: "Per crore (🪙 per ₹1 crore)" },
];

const RATE_HINT: Record<CommissionType, string> = {
  PER_LOT: "Charge per lot. A part-lot still attracts a minimum of 0.01 lot.",
  PERCENTAGE: "Percent of turnover (qty × price), per leg.",
  FLAT: "One fixed charge per order, whatever the size.",
  PER_CRORE: "Charge per ₹1,00,00,000 of turnover.",
};

export function BrokerageCalculator() {
  const [segment, setSegment] = useState(SEGMENTS[1].value);
  const [qty, setQty] = useState(75);
  const [price, setPrice] = useState(24600);
  const [lotSize, setLotSize] = useState(75);
  const [type, setType] = useState<CommissionType>("PER_LOT");
  const [rate, setRate] = useState(20);
  const [minB, setMinB] = useState(0);
  const [maxB, setMaxB] = useState(0);

  // Switching segment reloads that segment's typical setup, but the user
  // can then override any single field.
  const applySegment = (v: string) => {
    const s = SEGMENTS.find((x) => x.value === v);
    setSegment(v);
    if (s) {
      setLotSize(s.lotSize);
      setType(s.type);
      setRate(s.rate);
    }
  };

  const r = useMemo(() => {
    const input = {
      qty,
      price,
      lotSize,
      type,
      value: rate,
      minBrokerage: minB,
      maxBrokerage: maxB,
    };
    const perLeg = brokerageForLeg(input);
    const roundTrip = money(perLeg * 2);
    const turnover = money(qty * price);
    // What the price has to move, per unit, just to clear the round trip.
    const breakevenPoints = qty > 0 ? roundTrip / qty : 0;
    return {
      perLeg,
      roundTrip,
      turnover,
      breakevenPoints,
      pctOfTurnover: turnover > 0 ? (roundTrip / turnover) * 100 : 0,
      lots: lotSize > 0 ? qty / lotSize : 0,
    };
  }, [qty, price, lotSize, type, rate, minB, maxB]);

  return (
    <div className="grid gap-6 lg:grid-cols-[1.15fr_1fr]">
      {/* Inputs */}
      <MpCard hover={false} className="flex flex-col gap-5">
        <h2 className="font-display text-lg font-semibold text-mp-text">
          Your trade
        </h2>

        <ToolField label="Segment">
          <ToolSelect
            value={segment}
            onChange={applySegment}
            options={SEGMENTS.map((s) => ({ value: s.value, label: s.label }))}
          />
        </ToolField>

        <div className="grid gap-4 sm:grid-cols-2">
          <ToolField label="Quantity">
            <ToolNumber value={qty} onChange={setQty} />
          </ToolField>
          <ToolField label="Price per unit (₹)">
            <ToolNumber value={price} onChange={setPrice} />
          </ToolField>
          <ToolField label="Lot size" hint="1 for cash-segment stocks.">
            <ToolNumber value={lotSize} onChange={setLotSize} min={1} />
          </ToolField>
          <ToolField label="Brokerage type">
            <ToolSelect value={type} onChange={setType} options={TYPES} />
          </ToolField>
        </div>

        <ToolField label="Rate" hint={RATE_HINT[type]}>
          <ToolNumber value={rate} onChange={setRate} />
        </ToolField>

        <div className="grid gap-4 sm:grid-cols-2">
          <ToolField label="Minimum brokerage (₹)" hint="0 = no floor.">
            <ToolNumber value={minB} onChange={setMinB} />
          </ToolField>
          <ToolField label="Maximum brokerage (₹)" hint="0 = no cap.">
            <ToolNumber value={maxB} onChange={setMaxB} />
          </ToolField>
        </div>
      </MpCard>

      {/* Results */}
      <div className="flex flex-col gap-4">
        <MpCard hover={false} className="flex flex-col">
          <h2 className="font-display text-lg font-semibold text-mp-text">
            What you pay
          </h2>
          <div className="mt-3 flex flex-col">
            <ResultRow label="Turnover (one leg)" value={formatMoney(r.turnover)} tone="muted" />
            <ResultRow label="Lots" value={formatNumber(r.lots, 2)} tone="muted" />
            <ResultRow label="Brokerage — buy leg" value={formatMoney(r.perLeg)} />
            <ResultRow label="Brokerage — sell leg" value={formatMoney(r.perLeg)} />
            <ResultRow
              label="Total (round trip)"
              value={formatMoney(r.roundTrip)}
              strong
            />
          </div>
        </MpCard>

        <MpCard hover={false} className="flex flex-col">
          <h3 className="font-display text-base font-semibold text-mp-text">
            What it costs you in the market
          </h3>
          <div className="mt-2 flex flex-col">
            <ResultRow
              label="Break-even move needed"
              value={`${formatNumber(r.breakevenPoints, 4)} pts`}
            />
            <ResultRow
              label="Cost as % of turnover"
              value={`${formatNumber(r.pctOfTurnover, 4)}%`}
              tone="muted"
            />
          </div>
          <p className="mt-3 text-[12px] leading-[1.6] text-mp-text-mut">
            The price has to move that much in your favour before the position
            is even. Anything beyond it is profit.
          </p>
        </MpCard>
      </div>

      <div className="lg:col-span-2">
        <ToolDisclaimer>
          <strong className="text-mp-text">Brokerage is the only charge on this platform.</strong>{" "}
          There is no STT, exchange transaction charge, SEBI turnover fee,
          stamp duty, GST or DP charge added on top — so this figure is the
          whole cost of the trade. Your actual rate is set by your broker and
          can differ per segment; log in and open the order panel to see the
          exact number applied to a live order.
        </ToolDisclaimer>
      </div>
    </div>
  );
}
