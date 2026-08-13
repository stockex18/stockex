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
  formatMoney,
  formatNumber,
  marginRequired,
  money,
  type MarginMode,
} from "@/lib/tools/charges";

/* Mirrors the three margin modes the admin can set per segment
   (netting_service): Times → leverage multiplier, Percent → % of notional,
   Fixed → a flat 🪙 amount per lot. Intraday and carry-forward are separate
   tiers on the same instrument, which is why both are shown side by side —
   a position held past the session rolls onto the overnight number. */

const MODES: { value: MarginMode; label: string }[] = [
  { value: "times", label: "Times (leverage)" },
  { value: "percent", label: "Percent (% notional)" },
  { value: "fixed", label: "Fixed (₹ per lot)" },
];

const PRESETS = [
  { value: "NIFTY", label: "NIFTY Futures", price: 24600, lotSize: 75 },
  { value: "BANKNIFTY", label: "BANKNIFTY Futures", price: 57900, lotSize: 30 },
  { value: "RELIANCE", label: "RELIANCE (cash)", price: 1330, lotSize: 1 },
  { value: "GOLD", label: "GOLD (MCX)", price: 71850, lotSize: 100 },
  { value: "CUSTOM", label: "Custom instrument", price: 0, lotSize: 1 },
];

const VALUE_LABEL: Record<MarginMode, string> = {
  times: "Leverage (×)",
  percent: "Margin (% of notional)",
  fixed: "Margin per lot (₹)",
};

const VALUE_HINT: Record<MarginMode, string> = {
  times: "Margin = notional ÷ leverage. Below 1× is invalid and clamps to 1×.",
  percent: "Margin = notional × this percent.",
  fixed: "Margin = this amount × number of lots.",
};

export function MarginCalculator() {
  const [preset, setPreset] = useState("NIFTY");
  const [price, setPrice] = useState(24600);
  const [lotSize, setLotSize] = useState(75);
  const [lots, setLots] = useState(1);

  const [mode, setMode] = useState<MarginMode>("times");
  const [intraday, setIntraday] = useState(10);
  const [carry, setCarry] = useState(5);

  const [balance, setBalance] = useState(100000);

  const applyPreset = (v: string) => {
    setPreset(v);
    const p = PRESETS.find((x) => x.value === v);
    if (p && v !== "CUSTOM") {
      setPrice(p.price);
      setLotSize(p.lotSize);
    }
  };

  const r = useMemo(() => {
    const qty = Math.max(0, lots) * Math.max(1, lotSize);
    const i = marginRequired({ qty, price, lotSize, mode, value: intraday });
    const c = marginRequired({ qty, price, lotSize, mode, value: carry });
    return {
      qty,
      notional: i.notional,
      intraday: i.margin,
      carry: c.margin,
      intradayLev: i.leverage,
      carryLev: c.leverage,
      // How many lots the stated balance actually supports on each tier.
      maxLotsIntraday: i.margin > 0 ? Math.floor((balance / i.margin) * Math.max(0, lots)) : 0,
      maxLotsCarry: c.margin > 0 ? Math.floor((balance / c.margin) * Math.max(0, lots)) : 0,
      shortfallIntraday: money(Math.max(0, i.margin - balance)),
      shortfallCarry: money(Math.max(0, c.margin - balance)),
    };
  }, [lots, lotSize, price, mode, intraday, carry, balance]);

  return (
    <div className="grid gap-6 lg:grid-cols-[1.15fr_1fr]">
      <MpCard hover={false} className="flex flex-col gap-5">
        <h2 className="font-display text-lg font-semibold text-mp-text">
          Your contract
        </h2>

        <ToolField label="Instrument">
          <ToolSelect
            value={preset}
            onChange={applyPreset}
            options={PRESETS.map((p) => ({ value: p.value, label: p.label }))}
          />
        </ToolField>

        <div className="grid gap-4 sm:grid-cols-3">
          <ToolField label="Price (₹)">
            <ToolNumber value={price} onChange={setPrice} />
          </ToolField>
          <ToolField label="Lot size">
            <ToolNumber value={lotSize} onChange={setLotSize} min={1} />
          </ToolField>
          <ToolField label="Lots">
            <ToolNumber value={lots} onChange={setLots} min={0} step={1} />
          </ToolField>
        </div>

        <ToolField label="How your broker prices margin">
          <ToolToggle value={mode} onChange={setMode} options={MODES} />
        </ToolField>

        <div className="grid gap-4 sm:grid-cols-2">
          <ToolField label={`Intraday — ${VALUE_LABEL[mode]}`} hint={VALUE_HINT[mode]}>
            <ToolNumber value={intraday} onChange={setIntraday} />
          </ToolField>
          <ToolField label={`Carry-forward — ${VALUE_LABEL[mode]}`} hint="Applies once the position is held past the session.">
            <ToolNumber value={carry} onChange={setCarry} />
          </ToolField>
        </div>

        <ToolField label="Your available balance (₹)" hint="Used to check whether the position fits.">
          <ToolNumber value={balance} onChange={setBalance} />
        </ToolField>
      </MpCard>

      <div className="flex flex-col gap-4">
        <MpCard hover={false} className="flex flex-col">
          <h2 className="font-display text-lg font-semibold text-mp-text">
            Margin required
          </h2>
          <div className="mt-3 flex flex-col">
            <ResultRow label="Total quantity" value={formatNumber(r.qty, 0)} tone="muted" />
            <ResultRow label="Notional value" value={formatMoney(r.notional)} tone="muted" />
            <ResultRow
              label={`Intraday (${formatNumber(r.intradayLev, 2)}× effective)`}
              value={formatMoney(r.intraday)}
              strong
            />
            <ResultRow
              label={`Carry-forward (${formatNumber(r.carryLev, 2)}× effective)`}
              value={formatMoney(r.carry)}
            />
          </div>
        </MpCard>

        <MpCard hover={false} className="flex flex-col">
          <h3 className="font-display text-base font-semibold text-mp-text">
            Does it fit your balance?
          </h3>
          <div className="mt-2 flex flex-col">
            <ResultRow
              label="Intraday"
              value={
                r.shortfallIntraday > 0
                  ? `Short by ${formatMoney(r.shortfallIntraday)}`
                  : "Fits"
              }
              tone={r.shortfallIntraday > 0 ? "down" : "up"}
            />
            <ResultRow
              label="Carry-forward"
              value={
                r.shortfallCarry > 0
                  ? `Short by ${formatMoney(r.shortfallCarry)}`
                  : "Fits"
              }
              tone={r.shortfallCarry > 0 ? "down" : "up"}
            />
            <ResultRow
              label="Max lots — intraday"
              value={formatNumber(r.maxLotsIntraday, 0)}
              tone="muted"
            />
            <ResultRow
              label="Max lots — carry-forward"
              value={formatNumber(r.maxLotsCarry, 0)}
              tone="muted"
            />
          </div>
        </MpCard>
      </div>

      <div className="lg:col-span-2">
        <ToolDisclaimer>
          Margin is set per segment by your broker and can be tightened on
          expiry day, so the live order panel is always the authority. A
          position that clears intraday margin can still fall short overnight —
          if the carry-forward requirement isn&apos;t met, risk management may
          square the position off rather than roll it.
        </ToolDisclaimer>
      </div>
    </div>
  );
}
