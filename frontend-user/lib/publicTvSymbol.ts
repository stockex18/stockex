// Map a StockEx instrument to a FREE TradingView public symbol
// (OANDA / BINANCE / TVC) so the international (Infoway-fed) instruments —
// forex, spot metals, energy, crypto — can render in the free tv.js Advanced
// Chart widget with TradingView's own real data + full features.
//
// Returns `null` for Indian instruments (NSE / BSE / NFO / BFO / MCX) and for
// anything we can't confidently map — those keep the LICENSED chart that runs
// off our own datafeed (exact broker price). Operator decision: free widget
// for international, licensed for Indian.
//
// Caveat (accepted): the free widget shows TradingView's liquidity (OANDA /
// Binance), which is very close to but NOT identical to our Infoway price. The
// BUY/SELL order bar still uses our price.

const INDIAN_EXCH = new Set(["NSE", "BSE", "NFO", "BFO", "MCX"]);

// Crypto bases we serve → Binance USDT pair.
const CRYPTO_BASES = new Set([
  "BTC", "ETH", "LTC", "XRP", "SOL", "BNB", "DOGE", "ADA", "TRX", "LINK",
  "DOT", "AVAX", "MATIC", "ATOM", "NEAR", "ARB", "OP", "APT", "SUI", "PEPE",
  "SHIB", "BCH", "FIL", "TON", "INJ",
]);

// Energy → OANDA CFD names (reliable free TradingView symbols).
const ENERGY: Record<string, string> = {
  USOIL: "OANDA:WTICOUSD",
  WTI: "OANDA:WTICOUSD",
  UKOIL: "OANDA:BCOUSD",
  BRENT: "OANDA:BCOUSD",
  NATGAS: "OANDA:NATGASUSD",
};

export function toPublicTvSymbol(
  symbol?: string | null,
  exchange?: string | null,
  segment?: string | null,
): string | null {
  const s = (symbol ?? "").toUpperCase().replace(/\s+/g, "");
  const ex = (exchange ?? "").toUpperCase();
  const seg = (segment ?? "").toUpperCase();
  if (!s) return null;

  // Indian exchanges → keep the licensed chart (our exact datafeed).
  if (INDIAN_EXCH.has(ex)) return null;

  // ── Crypto option contracts have NO public Binance symbol ───────────
  // e.g. "BTC-260725-62000-C" / "…-P". Binance's free widget only serves
  // spot pairs, so mapping these produces a "symbol doesn't exist" chart.
  // Keep them on the LICENSED chart (our own datafeed = exact option price).
  const isCryptoOption =
    seg.includes("OPTION") || /-[CP]$/.test(s) || /-\d{4,}-[CP]$/.test(s);

  // ── Crypto → Binance pair ──────────────────────────────────────────
  if (!isCryptoOption) {
    if (s.endsWith("USDT") || s.endsWith("USDC")) return `BINANCE:${s}`;
    const base = s.endsWith("USD") ? s.slice(0, -3) : "";
    if (base && CRYPTO_BASES.has(base)) return `BINANCE:${base}USDT`;
    if (ex === "CRYPTO" || seg.includes("CRYPTO")) {
      return `BINANCE:${s.replace(/USD$/, "USDT")}`;
    }
  } else if (ex === "CRYPTO" || seg.includes("CRYPTO")) {
    // Crypto option → licensed chart (our datafeed handles the option token).
    return null;
  }

  // ── Energy CFDs ────────────────────────────────────────────────────
  if (ENERGY[s]) return ENERGY[s];

  // ── Forex + spot metals (EURUSD, XAUUSD, XAGUSD, …) → OANDA CFD ─────
  // OANDA covers the 6-letter FX crosses plus the metals we list — but not
  // the rupee: "OANDA:USDINR" is an invalid symbol (blank chart, 18 Nov).
  // TradingView carries INR pairs on FX_IDC.
  if (/^[A-Z]{3}INR$/.test(s)) return `FX_IDC:${s}`;
  if (/^[A-Z]{6}$/.test(s)) return `OANDA:${s}`;

  // International but unmappable → licensed chart handles it.
  return null;
}
