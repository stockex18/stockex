/**
 * Charge + margin math for the public calculator pages.
 *
 * These MIRROR the backend so the marketing calculators can't quote a
 * number the platform then contradicts:
 *
 *   brokerage → backend/app/services/brokerage_calculator.py  (`_brokerage`)
 *   margin    → backend/app/services/netting_service.py       (times / percent / fixed)
 *
 * IMPORTANT — no statutory pass-through. This platform charges BROKERAGE
 * ONLY: no STT, no exchange transaction charge, no SEBI turnover fee, no
 * stamp duty, no GST, no DP charge. That is a deliberate admin policy
 * (see the module docstring on brokerage_calculator.py), so a calculator
 * that itemised those lines would be inventing costs the user is never
 * actually billed. Don't "helpfully" add them back.
 *
 * The backend computes in Decimal and quantises to 2dp at each step;
 * JS numbers are fine at these magnitudes, but we quantise at the same
 * points so the two agree to the paisa.
 */

export type CommissionType = "FLAT" | "PERCENTAGE" | "PER_CRORE" | "PER_LOT";
export type MarginMode = "times" | "percent" | "fixed";

/** 2dp round-half-up, matching `quantize_money`. */
export function money(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.round((n + Number.EPSILON) * 100) / 100;
}

export interface BrokerageInput {
  qty: number;
  price: number;
  lotSize: number;
  type: CommissionType;
  value: number;
  /** Floor applied after the base calc. 0 = no floor. */
  minBrokerage?: number;
  /** Ceiling applied after the floor. 0 = no ceiling (backend treats
   *  max_brokerage <= 0 as "unset", not as "free"). */
  maxBrokerage?: number;
}

/** One leg's brokerage. Same branch order and clamping as `_brokerage`. */
export function brokerageForLeg(i: BrokerageInput): number {
  const qty = Math.max(0, i.qty || 0);
  const price = Math.max(0, i.price || 0);
  const turnover = qty * price;
  const value = i.value || 0;

  let b: number;
  switch (i.type) {
    case "FLAT":
      b = value;
      break;
    case "PERCENTAGE":
      b = (turnover * value) / 100;
      break;
    case "PER_CRORE":
      b = money((turnover * value) / 10_000_000);
      break;
    case "PER_LOT":
    default: {
      // Backend floors the lot count at 0.01 so a sub-lot quantity still
      // attracts a charge rather than rounding to free.
      const lots = Math.max(0.01, qty / Math.max(1, i.lotSize || 1));
      b = value * lots;
      break;
    }
  }

  const min = i.minBrokerage || 0;
  if (min && b < min) b = min;
  const max = i.maxBrokerage || 0;
  if (max > 0 && b > max) b = max;

  return money(b);
}

export interface MarginInput {
  qty: number;
  price: number;
  lotSize: number;
  mode: MarginMode;
  /** times → leverage multiplier; percent → % of notional; fixed → 🪙/lot. */
  value: number;
}

export interface MarginResult {
  notional: number;
  margin: number;
  /** Effective leverage the margin implies (notional ÷ margin). */
  leverage: number;
  lots: number;
}

export function marginRequired(i: MarginInput): MarginResult {
  const qty = Math.max(0, i.qty || 0);
  const price = Math.max(0, i.price || 0);
  const lotSize = Math.max(1, i.lotSize || 1);
  const notional = money(qty * price);
  const lots = qty / lotSize;
  const value = i.value || 0;

  let margin: number;
  if (i.mode === "times") {
    // A Times leverage below 1 is never valid — the backend clamps to 1×.
    const lev = Math.max(1, value);
    margin = notional / lev;
  } else if (i.mode === "percent") {
    margin = (notional * value) / 100;
  } else {
    margin = value * lots;
  }

  margin = money(margin);
  return {
    notional,
    margin,
    leverage: margin > 0 ? notional / margin : 0,
    lots,
  };
}

export interface PnlInput {
  side: "BUY" | "SELL";
  entry: number;
  exit: number;
  qty: number;
  /** Total brokerage across BOTH legs; pass 0 to see gross only. */
  brokerageRoundTrip?: number;
}

export interface PnlResult {
  gross: number;
  brokerage: number;
  net: number;
  /** Exit price at which net P&L is exactly zero. */
  breakeven: number;
  pointMove: number;
}

export function profitAndLoss(i: PnlInput): PnlResult {
  const qty = Math.max(0, i.qty || 0);
  const dir = i.side === "BUY" ? 1 : -1;
  const pointMove = (i.exit || 0) - (i.entry || 0);
  const gross = money(dir * pointMove * qty);
  const brokerage = money(i.brokerageRoundTrip || 0);
  const net = money(gross - brokerage);

  // Breakeven: the exit that makes gross exactly cover the round trip.
  const perUnit = qty > 0 ? brokerage / qty : 0;
  const breakeven = money((i.entry || 0) + dir * perUnit);

  return { gross, brokerage, net, breakeven, pointMove };
}

const inr = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Coin-prefixed amount. The app renders money with 🪙 in games and ₹
 *  elsewhere; marketing pages use the plain Indian-grouped number with a
 *  ₹ so the copy reads naturally to a prospect. */
export function formatMoney(n: number): string {
  return `₹${inr.format(Number.isFinite(n) ? n : 0)}`;
}

export function formatNumber(n: number, dp = 2): string {
  return new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  }).format(Number.isFinite(n) ? n : 0);
}
