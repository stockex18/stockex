"use client";

import axios, { AxiosError, AxiosRequestConfig, InternalAxiosRequestConfig } from "axios";
import { API_URL, STORAGE_KEYS } from "./constants";
import type { ApiErrorResponse, ApiResponse, TokenPair } from "@/types";

export const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  withCredentials: false,
  timeout: 30_000,
});

// Refresh dedup state. `inFlight` is per-tab; `withRefreshLock` adds a
// cross-tab exclusive lock on top of it so two tabs never hit the
// backend's rotating /refresh endpoint with the same (now-single-use)
// refresh token.
let inFlightRefresh: Promise<string | null> | null = null;
const REFRESH_LOCK = "mp.user.auth.refresh";
// Refresh proactively when the access token has < this many seconds left.
// 120 s is enough headroom for a slow mobile request to land on the
// backend before the JWT actually expires.
const REFRESH_MARGIN_SEC = 120;

function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(STORAGE_KEYS.accessToken);
}
function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(STORAGE_KEYS.refreshToken);
}
export function setTokens(access: string, refresh: string) {
  window.localStorage.setItem(STORAGE_KEYS.accessToken, access);
  window.localStorage.setItem(STORAGE_KEYS.refreshToken, refresh);
}
export function clearTokens() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEYS.accessToken);
  window.localStorage.removeItem(STORAGE_KEYS.refreshToken);
  window.localStorage.removeItem(STORAGE_KEYS.user);
  // ALSO drop the zustand-persist auth blob (nb.auth). Without this
  // the store still rehydrates `user` from localStorage on the next
  // navigation, the dashboard guard sees a "logged in" state, fires
  // an API call, gets 401 (tokens are gone), refresh fails, we land
  // back here, redirect to /login — and /login's "if user, go to
  // /dashboard" effect bounces us back. The screen alternates
  // dashboard ↔ login forever on phones with flaky networks where a
  // single refresh failure trips the chain. User report: "kisi phone
  // me sahi chal raha, kisi me band-chalu jaisa feel a raha".
  // Wiping nb.auth here makes the store's `user` null on next read,
  // so the guards correctly send the user to the login form one
  // time, not in a loop.
  window.localStorage.removeItem("nb.auth");
}

// ── JWT exp decoding (no verification — we only read the public
//    payload to know when to proactively rotate). Returns the unix
//    timestamp in seconds, or null if the token is malformed or has no
//    `exp` claim. Pure client-side; the server is the actual
//    authority on validity.
function jwtExpSec(token: string | null): number | null {
  if (!token || typeof token !== "string") return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    // Base64url → base64 → bytes → utf-8.
    const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
    const json = typeof atob === "function" ? atob(padded) : "";
    const obj = JSON.parse(json);
    return typeof obj?.exp === "number" ? obj.exp : null;
  } catch {
    return null;
  }
}
function isExpiringSoon(token: string | null, marginSec = REFRESH_MARGIN_SEC): boolean {
  const exp = jwtExpSec(token);
  if (exp == null) return false;
  return exp * 1000 - Date.now() < marginSec * 1000;
}
function isExpired(token: string | null): boolean {
  const exp = jwtExpSec(token);
  if (exp == null) return false;
  return exp * 1000 <= Date.now();
}

// Cross-tab exclusive lock. The Web Locks API is the canonical way to
// serialise critical sections across all tabs of an origin — a single
// holder at any moment, queueing for the rest. This prevents the
// "morning logout" race where dashboard + option-chain tabs woke up
// after midnight, both hit a 24-h-stale access token, both fired
// /refresh with the same refresh token, the backend rotated the jti
// for whichever request landed first, and the second one got a 401
// (jti gone) → clearTokens() → bounce to /login. With this lock only
// one tab actually calls /refresh; the others wait, then re-read
// localStorage and inherit the freshly-minted pair without a network
// round trip. Falls back to a same-tab promise on the (rare) browsers
// that don't expose `navigator.locks`.
async function withRefreshLock<T>(fn: () => Promise<T>): Promise<T> {
  if (
    typeof navigator !== "undefined" &&
    typeof (navigator as any).locks?.request === "function"
  ) {
    return (navigator as any).locks.request(REFRESH_LOCK, fn);
  }
  return fn();
}

/**
 * Try to mint a fresh access token from the stored refresh token.
 *
 * Return semantics — three states matter, not two:
 *   - "ok":          got a new access; tokens updated in localStorage.
 *   - "auth_failed": backend explicitly rejected the refresh (401 / 403).
 *                    Tokens MUST be cleared and the user redirected.
 *   - "transient":   network glitch, 5xx, timeout, CORS, anything else.
 *                    DO NOT clear tokens — the refresh token may still be
 *                    valid, the user just temporarily can't reach the
 *                    server. PWA users on flaky mobile networks hit this
 *                    every time the app resumes from background; the old
 *                    code force-cleared tokens here and bounced them to
 *                    /login, which is the "PWA bar bar logout" the user
 *                    reported even with a 30-day refresh TTL.
 */
async function callRefreshEndpoint(): Promise<
  { kind: "ok"; access: string } | { kind: "auth_failed" | "transient" }
> {
  const refresh = getRefreshToken();
  if (!refresh) return { kind: "auth_failed" };
  try {
    const res = await axios.post<ApiResponse<TokenPair>>(
      `${API_URL}/api/v1/user/auth/refresh`,
      { refresh_token: refresh },
      { timeout: 15_000 }
    );
    const pair = res.data.data;
    if (!pair) return { kind: "transient" };
    setTokens(pair.access_token, pair.refresh_token);
    return { kind: "ok", access: pair.access_token };
  } catch (err) {
    const ax = err as AxiosError;
    const status = ax.response?.status;
    // Only treat an explicit auth rejection as a sign-out signal.
    // 401 + 403 from /refresh itself = the refresh token is no longer
    // valid (revoked, rotated by another tab, expired, etc.) → clear
    // and log the user out. Anything else (network down, server 5xx,
    // gateway timeout, CORS preflight failure) is transient — keep the
    // tokens and let the next request retry.
    if (status === 401 || status === 403) {
      clearTokens();
      return { kind: "auth_failed" };
    }
    return { kind: "transient" };
  }
}

/**
 * The single entry point every code path uses to obtain a fresh
 * access token. Deduplicates within a tab via `inFlightRefresh`,
 * across tabs via `withRefreshLock`, and short-circuits if some
 * other tab already wrote a fresh token to localStorage while we
 * were queued behind the lock. Returns `null` only on auth_failed
 * (i.e. the user is genuinely signed out); transient failures
 * preserve the refresh token and surface as `null` too — the caller
 * decides whether to redirect (response interceptor only redirects
 * when the refresh token is GONE, not just on a single failed call).
 */
export async function ensureFreshAccessToken(): Promise<string | null> {
  inFlightRefresh ||= (async () => {
    try {
      return await withRefreshLock(async () => {
        // Re-check after acquiring the lock — a sibling tab may have
        // refreshed while we were queued. If the current token is
        // valid for at least a few seconds, reuse it instead of
        // burning a one-shot refresh token.
        const current = getAccessToken();
        if (current && !isExpiringSoon(current, 30)) return current;
        const r = await callRefreshEndpoint();
        return r.kind === "ok" ? r.access : null;
      });
    } finally {
      inFlightRefresh = null;
    }
  })();
  return inFlightRefresh;
}

api.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  let token = getAccessToken();
  // Proactive refresh: if the access token will expire within the
  // next REFRESH_MARGIN_SEC seconds, rotate it BEFORE this request
  // leaves the client. Eliminates the 401-storm that hits when six
  // dashboard widgets all mount simultaneously the morning after a
  // 24-h-old login.
  if (token && getRefreshToken() && isExpiringSoon(token)) {
    const fresh = await ensureFreshAccessToken();
    if (fresh) token = fresh;
  }
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (resp) => resp,
  async (error: AxiosError<ApiErrorResponse>) => {
    const original = error.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined;
    const status = error.response?.status;

    // Account blocked / deactivated by an admin. The backend re-checks the
    // user on EVERY request and returns 403 (ACCOUNT_BLOCKED / ACCOUNT_INACTIVE)
    // the instant an admin blocks them — and that check runs BEFORE the
    // session-epoch 401, so a blocked user NEVER reaches the 401 refresh path
    // below. It's not a token problem, so refreshing can't help; wipe the
    // creds and send them to /login instead of leaving them staring at an
    // empty ₹0 dashboard. Gate on the error code so ordinary 403s (permission
    // denied, segment-not-allowed) do NOT log the user out.
    if (status === 403) {
      const code = error.response?.data?.error?.code;
      if (
        (code === "ACCOUNT_BLOCKED" || code === "ACCOUNT_INACTIVE") &&
        typeof window !== "undefined"
      ) {
        clearTokens();
        if (!window.location.pathname.startsWith("/login")) {
          window.location.href = "/login";
        }
      }
      return Promise.reject(error);
    }

    if (status === 401 && original && !original._retry) {
      original._retry = true;
      const newToken = await ensureFreshAccessToken();
      if (newToken) {
        original.headers = { ...(original.headers || {}), Authorization: `Bearer ${newToken}` };
        return api.request(original);
      }
      // Only redirect to /login when we KNOW the refresh was rejected
      // (auth_failed → tokens already cleared inside callRefreshEndpoint).
      // For transient failures the tokens are still around — let the next
      // call retry naturally; the user keeps their session.
      const stillHaveRefresh = typeof window !== "undefined" && !!getRefreshToken();
      if (
        !stillHaveRefresh &&
        typeof window !== "undefined" &&
        !window.location.pathname.startsWith("/login")
      ) {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

// Re-export for callers that still want the old name.
export const refreshAccessToken = ensureFreshAccessToken;
export { jwtExpSec, isExpired, isExpiringSoon };

export class ApiError extends Error {
  code: string;
  details?: Record<string, unknown>;
  constructor(message: string, code: string, details?: Record<string, unknown>) {
    super(message);
    this.code = code;
    this.details = details;
    this.name = "ApiError";
  }
}

export async function unwrap<T>(p: Promise<{ data: ApiResponse<T> }>): Promise<T> {
  try {
    const res = await p;
    if (!res.data?.success || res.data.data == null) {
      throw new ApiError(res.data?.message || "Unknown error", "UNKNOWN");
    }
    return res.data.data as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    const ax = err as AxiosError<ApiErrorResponse>;
    const e = ax.response?.data?.error;
    throw new ApiError(e?.message || ax.message || "Network error", e?.code || "NETWORK", e?.details);
  }
}

export async function unwrapPage<T>(
  p: Promise<{ data: ApiResponse<T[]> }>,
): Promise<{ items: T[]; total: number }> {
  try {
    const res = await p;
    if (!res.data?.success || res.data.data == null) {
      throw new ApiError(res.data?.message || "Unknown error", "UNKNOWN");
    }
    return { items: res.data.data as T[], total: res.data.total ?? 0 };
  } catch (err) {
    if (err instanceof ApiError) throw err;
    const ax = err as AxiosError<ApiErrorResponse>;
    const e = ax.response?.data?.error;
    throw new ApiError(e?.message || ax.message || "Network error", e?.code || "NETWORK", e?.details);
  }
}

// ── Auth ─────────────────────────────────────────────────────────────
export const AuthAPI = {
  login: (body: { identifier: string; password: string; two_fa_code?: string }) =>
    unwrap<TokenPair>(api.post("/user/auth/login", body)),
  register: (body: {
    email: string;
    mobile: string;
    password: string;
    full_name: string;
    pan?: string;
    // White-label attribution. When the user landed on /register?ref=<ADM…>
    // (or on a tenant's custom domain), the BrandingProvider plumbs the
    // admin's user_code through here. Backend treats it as the admin's
    // ``user_code`` and stamps ``signup_origin`` accordingly. Optional —
    // omitting it preserves the pre-rollout behaviour (super-admin pool).
    referral_code?: string;
    // The broker the user picked to join under (signup picker). Required
    // EXCEPT on a referral signup, where the referrer's own broker/admin
    // chain is inherited instead.
    broker_id?: string;
  }) => unwrap(api.post("/user/auth/register", body)),
  // Personal demo signup — same fields as register (name/mobile/email/password
  // + chosen broker), but creates the user's OWN demo account pre-funded with
  // virtual money and logs in immediately (returns a full token pair).
  demoRegister: (body: {
    email: string;
    mobile: string;
    password: string;
    full_name: string;
    referral_code?: string;
    broker_id?: string;
  }) => unwrap<TokenPair>(api.post("/user/auth/demo-register", body)),
  logout: (refresh_token?: string) => unwrap(api.post("/user/auth/logout", { refresh_token })),
  refresh: (refresh_token: string) => unwrap<TokenPair>(api.post("/user/auth/refresh", { refresh_token })),
  forgotPassword: (identifier: string) => unwrap(api.post("/user/auth/forgot-password", { identifier })),
  resetPassword: (body: { identifier: string; otp: string; new_password: string }) =>
    unwrap(api.post("/user/auth/reset-password", body)),
  changePassword: (body: { current_password: string; new_password: string }) =>
    unwrap(api.post("/user/auth/change-password", body)),
  twoFASetup: () => unwrap<{ secret: string; provisioning_uri: string }>(api.post("/user/auth/2fa/setup")),
  twoFAEnable: (code: string) => unwrap(api.post("/user/auth/2fa/enable", { code })),
  twoFADisable: (password: string, code: string) => unwrap(api.post("/user/auth/2fa/disable", { password, code })),
  demoLogin: () => unwrap<TokenPair>(api.post("/user/auth/demo")),
};

export const ProfileAPI = {
  me: () => unwrap<any>(api.get("/user/users/me")),
  update: (body: Record<string, unknown>) => unwrap<any>(api.put("/user/users/me", body)),
  changeBroker: (broker_id: string) => unwrap<any>(api.put("/user/users/me/broker", { broker_id })),
  // Convert the logged-in demo account into a fresh real account (wipes demo
  // trades + zeroes balance server-side). Returns the updated `me` object.
  convertToReal: () => unwrap<any>(api.post("/user/users/me/convert-to-real")),
};

// Broker directory for the signup picker + profile broker-switch. PUBLIC (the
// axios `api` instance sends no Authorization header pre-login).
export interface BrokerOption {
  id: string;
  user_code: string;
  full_name: string;
  city: string | null;
  admin_name: string | null;
}
export const BrokerSearchAPI = {
  search: (q?: string, limit = 30) =>
    unwrap<BrokerOption[]>(api.get("/user/auth/brokers", { params: { q: q || undefined, limit } })),
};

// Shape returned by `WalletAPI.wdRules`. Both rules carry the same set of
// fields — backend serialises Decimal128 amounts as strings, weekday list
// as 0=Mon..6=Sun ints, time windows as ISO HH:MM strings.
export interface WdRule {
  min_amount: string | null;
  max_amount: string | null;
  daily_limit: string | null;
  allowed_days: number[] | null;
  allowed_times: { start: string; end: string }[] | null;
  charges_flat: string | null;
  charges_percent: number;
  auto_approve_under: string | null;
  mandatory_remark: boolean;
}

export const WalletAPI = {
  summary: () => unwrap<any>(api.get("/user/wallet/summary")),
  transactions: (limit = 100, skip = 0) =>
    unwrap<any[]>(api.get("/user/wallet/transactions", { params: { limit, skip } })),
  companyBanks: () => unwrap<any[]>(api.get("/user/wallet/company-banks")),
  createDeposit: (body: any) => unwrap<any>(api.post("/user/wallet/deposits", body)),
  myDeposits: () => unwrap<any[]>(api.get("/user/wallet/deposits")),
  createWithdrawal: (body: any) => unwrap<any>(api.post("/user/wallet/withdrawals", body)),
  myWithdrawals: () => unwrap<any[]>(api.get("/user/wallet/withdrawals")),
  // Effective deposit + withdrawal rules for this user — already resolved
  // through the broker → admin → super-admin → global cascade by the
  // backend. Used by the deposit/withdraw dialogs to render the inline
  // info banner ("min ₹100, ₹10k daily, Mon–Fri 10:00–18:00 IST").
  wdRules: () =>
    unwrap<{
      deposit: WdRule;
      withdrawal: WdRule;
    }>(api.get("/user/wallet/wd-rules")),
  myBankAccounts: () => unwrap<any[]>(api.get("/user/wallet/bank-accounts")),
  addBankAccount: (body: any) => unwrap<any>(api.post("/user/wallet/bank-accounts", body)),
  uploadScreenshot: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return unwrap<{ url: string; size: number }>(
      api.post("/user/wallet/upload-screenshot", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      })
    );
  },
};

export const MarketwatchAPI = {
  list: () => unwrap<any[]>(api.get("/user/marketwatch")),
  create: (name: string) => unwrap<any>(api.post("/user/marketwatch", { name })),
  delete: (id: string) => unwrap<any>(api.delete(`/user/marketwatch/${id}`)),
  addItem: (watchlistId: string, token: string) =>
    unwrap<any>(api.post(`/user/marketwatch/${watchlistId}/items`, { token })),
  removeItem: (watchlistId: string, itemId: string) =>
    unwrap<any>(api.delete(`/user/marketwatch/${watchlistId}/items/${itemId}`)),
  quotes: (watchlistId: string) => unwrap<any[]>(api.get(`/user/marketwatch/${watchlistId}/quotes`)),
  // Per-segment managed instrument lists (Indian segments only — NSE_EQ,
  // NSE_FUT, NSE_OPT, BSE_*, MCX_*). User explicitly adds/removes items
  // here; the panel only shows what they've added. Forex / Crypto /
  // Stocks / Indices / Commodities continue to render from the Infoway
  // feed directly without a per-user list.
  segmentItems: (segmentName: string) =>
    unwrap<any[]>(api.get(`/user/marketwatch/segment/${segmentName}/items`)),
  addSegmentItem: (segmentName: string, token: string) =>
    unwrap<any>(
      api.post(`/user/marketwatch/segment/${segmentName}/items`, { token }),
    ),
  removeSegmentItem: (segmentName: string, token: string) =>
    unwrap<any>(api.delete(`/user/marketwatch/segment/${segmentName}/items/${token}`)),
};

export const InstrumentAPI = {
  search: (
    q?: string,
    exchange?: string,
    segment?: string,
    limit = 30,
    instrumentType?: string,
  ) =>
    unwrap<any[]>(
      api.get("/user/instruments/search", {
        params: { q, exchange, segment, instrument_type: instrumentType, limit },
      }),
    ),
  detail: (token: string) => unwrap<any>(api.get(`/user/instruments/${token}`)),
  quote: (token: string) => unwrap<any>(api.get(`/user/instruments/${token}/quote`)),
  quotesBatch: (tokens: string[]) =>
    unwrap<any[]>(api.get("/user/instruments/quotes/batch", { params: { tokens: tokens.join(",") } })),
  history: (token: string, interval = "5minute", days = 5) =>
    unwrap<any[]>(api.get(`/user/instruments/${token}/history`, { params: { interval, days } })),
};

export const SegmentSettingsAPI = {
  effective: (token: string, action: "BUY" | "SELL" = "BUY", product_type: "MIS" | "NRML" | "CNC" = "MIS") =>
    unwrap<any>(
      api.get("/user/segment-settings/effective", {
        params: { token, action, product_type },
      })
    ),
  // Names of admin matrix rows currently flagged isActive=false. The
  // InstrumentsPanel uses this list to hide buckets whose underlying
  // segments are turned off — chip + dropdown entry both disappear.
  inactive: () => unwrap<string[]>(api.get("/user/segment-settings/inactive")),
};

export const OrderAPI = {
  list: (status?: string) => unwrap<any[]>(api.get("/user/orders", { params: { status } })),
  detail: (id: string) => unwrap<any>(api.get(`/user/orders/${id}`)),
  place: (body: any) => unwrap<any>(api.post("/user/orders", body)),
  modify: (id: string, body: any) => unwrap<any>(api.put(`/user/orders/${id}`, body)),
  cancel: (id: string) => unwrap<any>(api.delete(`/user/orders/${id}`)),
};

export const PositionAPI = {
  open: () => unwrap<any[]>(api.get("/user/positions/open")),
  closed: (page = 1, pageSize = 25) =>
    unwrapPage<any>(api.get("/user/positions/closed", { params: { page, page_size: pageSize } })),
  squareoff: (id: string, lots?: number) =>
    unwrap<any>(api.post(`/user/positions/${id}/squareoff`, undefined, { params: lots ? { lots } : {} })),
  squareoffAll: () => unwrap<any>(api.post("/user/positions/squareoff-all")),
  updateSlTp: (id: string, body: { stop_loss?: number | null; target?: number | null }) =>
    unwrap<any>(api.put(`/user/positions/${id}/sl-tp`, body)),
  pnlSummary: () => unwrap<any>(api.get("/user/positions/pnl-summary")),
  activeTrades: () => unwrap<any[]>(api.get("/user/positions/active-trades")),
  closeActiveTrade: (tradeId: string) =>
    unwrap<any>(api.post(`/user/positions/active-trades/${tradeId}/close`)),
  updateActiveTradeSlTp: (tradeId: string, body: { stop_loss?: number | null; target?: number | null }) =>
    unwrap<any>(api.put(`/user/positions/active-trades/${tradeId}/sl-tp`, body)),
};

export const DashboardAPI = {
  summary: () => unwrap<any>(api.get("/user/dashboard/summary")),
};

// ── Referral (user-to-user growth incentive) ─────────────────────────
export const ReferralAPI = {
  stats: () => unwrap<any>(api.get("/user/referral/stats")),
  earnings: (limit = 200) =>
    unwrap<any[]>(api.get("/user/referral/earnings", { params: { limit } })),
};

// ── Multi-wallet accounts (per-segment trading wallets) ──────────────
export const AccountsAPI = {
  list: () => unwrap<any>(api.get("/user/accounts")),
  setPrimary: (kind: string) => unwrap<any>(api.post("/user/accounts/primary", { kind })),
  transfer: (from_kind: string, to_kind: string, amount: number) =>
    unwrap<any>(api.post("/user/accounts/transfer", { from_kind, to_kind, amount })),
};

// ── Games (prediction/betting) subsystem ─────────────────────────────
// `gameId` here is the UI id ("updown", "btcupdown", "niftynumber", …);
// the backend maps it to the GameSettings key. Query keys are namespaced
// under ["games", …] so the UserWsBridge can invalidate precisely and we
// NEVER touch the trades cache (known flicker bug).
export const GamesAPI = {
  settings: () => unwrap<any>(api.get("/user/games/settings")),
  wallet: () => unwrap<any>(api.get("/user/games/wallet")),
  ledger: (p: { gameId?: string; limit?: number; date?: string } = {}) =>
    unwrap<any[]>(api.get("/user/games/wallet/ledger", { params: p })),
  todayNet: () => unwrap<any>(api.get("/user/games/wallet/today-net")),
  transferIn: (amount: number) =>
    unwrap<any>(api.post("/user/games/wallet/transfer-in", { amount })),
  withdraw: (amount: number, remark?: string) =>
    unwrap<any>(api.post("/user/games/wallet/withdraw", { amount, remark })),
  liveActivity: () => unwrap<any>(api.get("/user/games/live-activity")),
  price: () => unwrap<{ nifty: string | null; btc: string | null }>(api.get("/user/games/price")),
  klines: (asset: "btc" | "nifty", interval: string, limit = 200) =>
    unwrap<{ candles: any[]; source: string; interval: string }>(
      api.get("/user/games/klines", { params: { asset, interval, limit } }),
    ),
  recentWinners: (limit = 20) =>
    unwrap<any[]>(api.get("/user/games/recent-winners", { params: { limit } })),
  // Up/Down
  placeBet: (body: { gameId: string; prediction: "UP" | "DOWN"; amount: number; entryPrice: number; windowNumber: number }) =>
    unwrap<any>(api.post("/user/games/bet/place", body)),
  modifyBet: (betId: string, body: { prediction?: "UP" | "DOWN"; amount?: number }) =>
    unwrap<any>(api.patch(`/user/games/bet/${betId}`, body)),
  cancelBet: (betId: string) => unwrap<any>(api.delete(`/user/games/bet/${betId}`)),
  bets: (gameId: string, limit = 50) =>
    unwrap<any[]>(api.get(`/user/games/bets/${gameId}`, { params: { limit } })),
  results: (gameId: string, p: { limit?: number; day?: string } = {}) =>
    unwrap<any[]>(api.get(`/user/games/results/${gameId}`, { params: p })),
  // Number
  numberBet: (body: { gameId: string; selectedNumbers: number[]; quantity: number }) =>
    unwrap<any[]>(api.post("/user/games/number/bet", body)),
  numberModify: (betId: string, body: { selectedNumber?: number; quantity?: number }) =>
    unwrap<any>(api.patch(`/user/games/number/bet/${betId}`, body)),
  numberCancel: (betId: string) => unwrap<any>(api.delete(`/user/games/number/bet/${betId}`)),
  numberToday: (gameId: string) => unwrap<any>(api.get(`/user/games/number/today/${gameId}`)),
  numberResult: (gameId: string, day?: string) =>
    unwrap<any>(api.get(`/user/games/number/daily-result/${gameId}`, { params: { day } })),
  numberLast5: (gameId: string) =>
    unwrap<any[]>(api.get(`/user/games/number/last-5-days/${gameId}`)),
  // Bracket
  bracketTrade: (body: { prediction: "BUY" | "SELL"; amount: number; entryPrice: number }) =>
    unwrap<any>(api.post("/user/games/bracket/trade", body)),
  bracketActive: () => unwrap<any[]>(api.get("/user/games/bracket/active")),
  bracketHistory: (limit = 50) =>
    unwrap<any[]>(api.get("/user/games/bracket/history", { params: { limit } })),
  bracketRecentResults: (limit = 5) =>
    unwrap<any[]>(api.get("/user/games/bracket/recent-results", { params: { limit } })),
  // Jackpot
  jackpotBid: (body: { gameId: string; predictedPrice: number }) =>
    unwrap<any>(api.post("/user/games/jackpot/bid", body)),
  jackpotModify: (bidId: string, body: { predictedPrice: number }) =>
    unwrap<any>(api.patch(`/user/games/jackpot/bid/${bidId}`, body)),
  jackpotToday: (gameId: string) => unwrap<any>(api.get(`/user/games/jackpot/today/${gameId}`)),
  jackpotLeaderboard: (gameId: string, limit = 20) =>
    unwrap<any>(api.get(`/user/games/jackpot/leaderboard/${gameId}`, { params: { limit } })),
  jackpotHistory: (gameId: string, limit = 50) =>
    unwrap<any[]>(api.get(`/user/games/jackpot/history/${gameId}`, { params: { limit } })),
  jackpotLast5: (gameId: string) =>
    unwrap<any[]>(api.get(`/user/games/jackpot/last-5-days/${gameId}`)),
};

export const LedgerAPI = {
  list: (params?: { from_date?: string; to_date?: string; limit?: number }) =>
    unwrap<any>(api.get("/user/ledger", { params })),
};

export const ReportsAPI = {
  pnl: (params?: any) => unwrap<any>(api.get("/user/reports/pnl", { params })),
  tradebook: (params?: any) => unwrap<any[]>(api.get("/user/reports/tradebook", { params })),
  brokerage: (params?: any) => unwrap<any>(api.get("/user/reports/brokerage", { params })),
  tax: () => unwrap<any>(api.get("/user/reports/tax")),
  margin: () => unwrap<any>(api.get("/user/reports/margin")),
};

export const AlertsAPI = {
  list: () => unwrap<any[]>(api.get("/user/alerts")),
  create: (body: any) => unwrap<any>(api.post("/user/alerts", body)),
  delete: (id: string) => unwrap<any>(api.delete(`/user/alerts/${id}`)),
};

export const OptionChainAPI = {
  fetch: (underlying: string, expiry?: string) =>
    unwrap<any>(api.get("/user/option-chain", { params: { underlying, expiry } })),
  config: () => unwrap<any>(api.get("/user/option-chain/config")),
};

export const NotificationsAPI = {
  list: (only_unread = false, limit = 100) =>
    unwrap<any[]>(api.get("/user/notifications", { params: { only_unread, limit } })),
  markRead: (id: string) => unwrap<any>(api.post(`/user/notifications/${id}/read`)),
  markAllRead: () => unwrap<any>(api.post("/user/notifications/mark-all-read")),
  unreadCount: () => unwrap<{ count: number }>(api.get("/user/notifications/unread-count")),
};

/** Web Push subscription endpoints — paired with `notify-sound.ts`'s
 *  subscribeForWebPush helper so the SW (public/sw.js) receives
 *  backend pushes for deposit / withdrawal approvals and admin
 *  Add/Deduct Fund events. */
export const PushAPI = {
  vapidKey: () => unwrap<{ public_key: string }>(api.get("/user/push/vapid-key")),
  subscribe: (body: { endpoint: string; keys: { p256dh: string; auth: string }; label?: string }) =>
    unwrap<{ id: string; created: boolean }>(api.post("/user/push/subscribe", body)),
  unsubscribe: (endpoint: string) =>
    unwrap<{ ok: boolean; found: boolean }>(api.post("/user/push/unsubscribe", { endpoint })),
};

export { getAccessToken, getRefreshToken };
