"use client";

import axios, { AxiosError, AxiosRequestConfig, InternalAxiosRequestConfig } from "axios";
import { ADMIN_API_KEY, API_URL, STORAGE_KEYS } from "./constants";
import type { AdminTokenPair, ApiResponse } from "@/types";

export const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  withCredentials: false,
  timeout: 30_000,
});

// Refresh dedup state. Per-tab promise + cross-tab Web Locks below.
let inFlightRefresh: Promise<string | null> | null = null;
const REFRESH_LOCK = "mp.admin.auth.refresh";
const REFRESH_MARGIN_SEC = 120;

function getAccessToken() {
  return typeof window !== "undefined" ? window.localStorage.getItem(STORAGE_KEYS.accessToken) : null;
}
function getRefreshToken() {
  return typeof window !== "undefined" ? window.localStorage.getItem(STORAGE_KEYS.refreshToken) : null;
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
}

// ── JWT exp decoder — read-only, no signature check. Used solely to
//    decide whether to rotate the access token *before* sending the
//    next request, so the dashboard never sees a 401 storm on cold
//    open after a 24-h-stale login.
function jwtExpSec(token: string | null): number | null {
  if (!token || typeof token !== "string") return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
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

// Cross-tab exclusive lock: only one admin tab runs the rotating
// /refresh endpoint at a time. Other tabs queue, then re-read
// localStorage and inherit the new pair without burning their own
// refresh token. Prevents the morning-logout race the user reported.
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
 * Three-state refresh outcome — see the user-side api.ts for the full
 * rationale. Short version: a network glitch or 5xx mid-refresh MUST
 * NOT log the admin out, because the refresh token may still be valid;
 * only an explicit 401/403 from the /refresh endpoint counts as a
 * sign-out signal.
 */
async function callRefreshEndpoint(): Promise<
  { kind: "ok"; access: string } | { kind: "auth_failed" | "transient" }
> {
  const refresh = getRefreshToken();
  if (!refresh) return { kind: "auth_failed" };
  try {
    const headers: Record<string, string> = {};
    if (ADMIN_API_KEY) headers["X-Admin-Api-Key"] = ADMIN_API_KEY;
    const r = await axios.post<ApiResponse<AdminTokenPair>>(
      `${API_URL}/api/v1/admin/auth/refresh`,
      { refresh_token: refresh },
      { headers, timeout: 15_000 }
    );
    const pair = r.data.data;
    if (!pair) return { kind: "transient" };
    setTokens(pair.access_token, pair.refresh_token);
    return { kind: "ok", access: pair.access_token };
  } catch (err) {
    const ax = err as AxiosError;
    const status = ax.response?.status;
    if (status === 401 || status === 403) {
      clearTokens();
      return { kind: "auth_failed" };
    }
    return { kind: "transient" };
  }
}

/**
 * Single entry point for getting a fresh admin access token. Dedups
 * within the tab via inFlightRefresh, across tabs via withRefreshLock,
 * and short-circuits if a sibling tab already wrote a fresh pair to
 * localStorage while we were queued.
 */
export async function ensureFreshAccessToken(): Promise<string | null> {
  inFlightRefresh ||= (async () => {
    try {
      return await withRefreshLock(async () => {
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
  if (!config.headers) return config;
  if (ADMIN_API_KEY) config.headers["X-Admin-Api-Key"] = ADMIN_API_KEY;
  let tok = getAccessToken();
  // Proactive rotation — catches the access token before it expires
  // so the rest of the dashboard never sees a 401 cascade.
  if (tok && getRefreshToken() && isExpiringSoon(tok)) {
    const fresh = await ensureFreshAccessToken();
    if (fresh) tok = fresh;
  }
  if (tok) config.headers.Authorization = `Bearer ${tok}`;
  return config;
});

api.interceptors.response.use(
  (resp) => resp,
  async (error: AxiosError) => {
    const original = error.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined;
    const status = error.response?.status;
    if (status === 401 && original && !original._retry) {
      original._retry = true;
      const newToken = await ensureFreshAccessToken();
      if (newToken) {
        original.headers = { ...(original.headers || {}), Authorization: `Bearer ${newToken}` };
        return api.request(original);
      }
      // Only redirect when the refresh path actually cleared the
      // tokens (explicit auth failure). Transient errors keep the
      // refresh around so the next request can retry without making
      // the admin re-enter credentials.
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

// Re-export under the old name so existing imports keep working.
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
    const ax = err as AxiosError<{ error?: { code?: string; message?: string; details?: Record<string, unknown> } }>;
    const e = ax.response?.data?.error;
    throw new ApiError(e?.message || ax.message || "Network error", e?.code || "NETWORK", e?.details);
  }
}

export const AdminAuthAPI = {
  login: (body: { identifier: string; password: string; two_fa_code?: string }) =>
    unwrap<AdminTokenPair>(api.post("/admin/auth/login", body)),
  // Public broker demo signup — creates a personal DEMO BROKER (50L virtual
  // float) and logs into the admin app immediately.
  brokerDemoRegister: (body: {
    full_name: string;
    email: string;
    mobile: string;
    password: string;
  }) => unwrap<AdminTokenPair>(api.post("/admin/auth/broker-demo-register", body)),
  refresh: (refresh_token: string) => unwrap<AdminTokenPair>(api.post("/admin/auth/refresh", { refresh_token })),
  logout: (refresh_token?: string) => unwrap<any>(api.post("/admin/auth/logout", { refresh_token })),
  me: () => unwrap<any>(api.get("/admin/auth/me")),
};

// Super-admin "Demo" section — demo users + demo brokers, converted vs pending.
export const AdminDemoAPI = {
  list: (params: { kind: "users" | "brokers"; status: "pending" | "converted"; q?: string; page?: number; page_size?: number }) =>
    unwrap<any>(api.get("/admin/management/demo", { params })),
};

export const DashboardAPI = {
  stats: () => unwrap<any>(api.get("/admin/dashboard/stats")),
  riskAlerts: () => unwrap<any[]>(api.get("/admin/dashboard/risk-alerts")),
};

// ── Games (SUPER_ADMIN only) ─────────────────────────────────────────
export const AdminGamesAPI = {
  settings: () => unwrap<any>(api.get("/admin/games/settings")),
  liveDetails: () => unwrap<any>(api.get("/admin/games/settings/live-details")),
  updateSettings: (body: any) => unwrap<any>(api.put("/admin/games/settings", body)),
  updateGame: (gameId: string, body: any) =>
    unwrap<any>(api.put(`/admin/games/settings/game/${gameId}`, body)),
  toggleGame: (gameId: string, enabled: boolean) =>
    unwrap<any>(api.patch(`/admin/games/settings/game/${gameId}/toggle`, { enabled })),
  // Manual daily result override (number games)
  manualResult: (gameId: string, day?: string) =>
    unwrap<any>(api.get(`/admin/games/manual-result/${gameId}`, { params: day ? { day } : {} })),
  setManualResult: (
    gameId: string,
    body: { close_price?: string; result_number?: number; day?: string },
  ) => unwrap<any>(api.put(`/admin/games/manual-result/${gameId}`, body)),
  clearManualResult: (gameId: string, day?: string) =>
    unwrap<any>(api.delete(`/admin/games/manual-result/${gameId}`, { params: day ? { day } : {} })),
  toggleAll: (enabled: boolean) =>
    unwrap<any>(api.patch("/admin/games/settings/toggle-all", { enabled })),
  setMaintenance: (body: { maintenance_mode: boolean; maintenance_message?: string }) =>
    unwrap<any>(api.patch("/admin/games/settings/maintenance", body)),
  withdrawals: (status = "PENDING") =>
    unwrap<any[]>(api.get("/admin/games/withdrawals", { params: { status } })),
  approveWithdrawal: (id: string, admin_remark?: string) =>
    unwrap<any>(api.post(`/admin/games/withdrawals/${id}/approve`, { admin_remark })),
  rejectWithdrawal: (id: string, reason?: string) =>
    unwrap<any>(api.post(`/admin/games/withdrawals/${id}/reject`, { reason })),
  hierarchyEarnings: () => unwrap<any[]>(api.get("/admin/games/hierarchy-earnings")),
  releaseHierarchyEarnings: (userId: string, amount: number) =>
    unwrap<any>(api.post(`/admin/games/hierarchy-earnings/${userId}/release`, { amount })),
  // Manual game entry — one NIFTY close drives all 3 nifty games; reverse on
  // a wrong result (claws back payouts + clears declared).
  manualEntry: (day?: string) =>
    unwrap<any>(api.get("/admin/games/manual-entry", { params: day ? { day } : {} })),
  manualEntryDeclare: (body: { day?: string; close_price: string }) =>
    unwrap<any>(api.post("/admin/games/manual-entry/declare", body)),
  manualEntryReverse: (day?: string) =>
    unwrap<any>(api.post("/admin/games/manual-entry/reverse", { day })),
  manualEntryDeclareGame: (body: { day?: string; game_key: string; close_price: string }) =>
    unwrap<any>(api.post("/admin/games/manual-entry/declare-game", body)),
  manualEntryReverseGame: (body: { day?: string; game_key: string }) =>
    unwrap<any>(api.post("/admin/games/manual-entry/reverse-game", body)),
};

export const AdminMeAPI = {
  wallet: () => unwrap<any>(api.get("/admin/me/wallet")),
  houseSummary: () => unwrap<any>(api.get("/admin/me/house-summary")),
  // Self-service profile — a BROKER sets their public `city` (place) so they
  // appear in the signup broker-search.
  profile: () => unwrap<any>(api.get("/admin/me/profile")),
  setProfile: (body: { city?: string; full_name?: string }) =>
    unwrap<any>(api.put("/admin/me/profile", body)),
  // Self-release held games commission (temporary_balance → own main wallet).
  // Omit `amount` (or pass null) to release the full held balance.
  releaseCommission: (amount?: number) =>
    unwrap<any>(api.post("/admin/me/release-commission", { amount: amount ?? null })),
  // Own fund/commission ledger (opening fund = first ADMIN_DEPOSIT row).
  ledger: (limit = 50) =>
    unwrap<any[]>(api.get("/admin/me/ledger", { params: { limit } })),
  // Per-trade earnings that came to THIS node from the trading cascade.
  tradeEarnings: (limit = 100) =>
    unwrap<any[]>(api.get("/admin/me/trade-earnings", { params: { limit } })),
  // Direct fundable downline with balances; optional user_code/full_name search.
  members: (q?: string) =>
    unwrap<any[]>(api.get("/admin/me/members", { params: q ? { q } : undefined })),
  // Full fund lifecycle of ONE direct member (given / deployed / returned +
  // raw ledger) — powers the "how did they use the money" detail dialog.
  memberFundDetail: (memberId: string, limit = 100) =>
    unwrap<any>(api.get(`/admin/me/members/${memberId}/fund-detail`, { params: { limit } })),
  // SUPER_ADMIN games revenue analytics (per_game / per_admin / totals).
  gamesBreakdown: () => unwrap<any>(api.get("/admin/me/games-breakdown")),
  // Convert the logged-in DEMO BROKER into a real broker (zeroes the virtual
  // float, unlocks user-create).
  convertToReal: () => unwrap<any>(api.post("/admin/me/convert-to-real")),
};

export const AdminKuberAPI = {
  get: () => unwrap<any>(api.get("/admin/kuber")),
  bootstrap: () => unwrap<any>(api.post("/admin/kuber/bootstrap", {})),
  transfer: (direction: "to_kuber" | "to_main", amount: number) =>
    unwrap<any>(api.post("/admin/kuber/transfer", { direction, amount })),
};

export const AdminPattiAPI = {
  get: (userId: string) => unwrap<any>(api.get(`/admin/patti/${userId}`)),
  set: (userId: string, body: { enabled?: boolean; segments?: Record<string, { pnl_pct: number; brokerage_pct: number }> }) =>
    unwrap<any>(api.put(`/admin/patti/${userId}`, body)),
};

export const AdminSecurityAPI = {
  list: () => unwrap<any[]>(api.get("/admin/security-money")),
  entries: (adminId?: string, limit = 100) =>
    unwrap<any[]>(api.get("/admin/security-money/entries", { params: { admin_id: adminId, limit } })),
  deposit: (admin_id: string, amount: number, payment_mode?: string, narration?: string) =>
    unwrap<any>(api.post("/admin/security-money/deposit", { admin_id, amount, payment_mode, narration })),
  withdraw: (admin_id: string, amount: number, payment_mode?: string, narration?: string) =>
    unwrap<any>(api.post("/admin/security-money/withdraw", { admin_id, amount, payment_mode, narration })),
  topup: (admin_id: string, amount: number, narration?: string) =>
    unwrap<any>(api.post("/admin/security-money/topup", { admin_id, amount, narration })),
  statement: (adminId: string, start?: string, end?: string) =>
    unwrap<any>(api.get(`/admin/security-money/${adminId}/statement`, { params: { start, end } })),
  pdf: async (adminId: string, start?: string, end?: string): Promise<Blob> => {
    const res = await api.get(`/admin/security-money/${adminId}/pdf`, {
      params: { start, end },
      responseType: "blob",
    });
    return res.data;
  },
};

export const LedgerBooksAPI = {
  list: (includeArchived = false) =>
    unwrap<any[]>(api.get("/admin/ledger-books", { params: { include_archived: includeArchived } })),
  paymentModes: () => unwrap<{ code: string; label: string }[]>(api.get("/admin/ledger-books/payment-modes")),
  create: (body: {
    name: string; is_payment_mode?: boolean; account_type?: string;
    opening_balance?: number; opening_date?: string; note?: string;
  }) => unwrap<any>(api.post("/admin/ledger-books", body)),
  /** One voucher, two or more accounts, debits equal to credits. */
  postVoucher: (body: {
    entry_date: string;
    legs: { book_id: string; debit?: number; credit?: number; particulars?: string }[];
    voucher_type?: string; voucher_no?: string; narration?: string;
  }) => unwrap<any>(api.post("/admin/ledger-books/vouchers", body)),
  trialBalance: (asOf?: string) =>
    unwrap<any>(api.get("/admin/ledger-books/trial-balance", { params: { as_of: asOf } })),
  // The COIN trial balance — a different report from the one above, which
  // totals the cash and bank books. This one totals what was issued against
  // every wallet holding it.
  coinTrialBalance: (asOn?: string) =>
    unwrap<any>(api.get("/admin/ledger-books/coin-trial-balance", { params: { as_on: asOn } })),
  coinTrialBalanceAdmin: (userCode: string) =>
    unwrap<any>(api.get(`/admin/ledger-books/coin-trial-balance/admin/${userCode}`)),
  coinTrialBalancePdf: (asOn?: string) =>
    api
      .get("/admin/ledger-books/coin-trial-balance/pdf", {
        params: { as_on: asOn },
        responseType: "blob",
      })
      .then((r) => r.data as Blob),
  dayBook: (start?: string, end?: string, limit = 500) =>
    unwrap<any[]>(api.get("/admin/ledger-books/day-book", { params: { start, end, limit } })),
  update: (id: string, body: Record<string, unknown>) =>
    unwrap<any>(api.patch(`/admin/ledger-books/${id}`, body)),
  remove: (id: string) => unwrap<any>(api.delete(`/admin/ledger-books/${id}`)),
  statement: (id: string, start?: string, end?: string) =>
    unwrap<any>(api.get(`/admin/ledger-books/${id}/statement`, { params: { start, end } })),
  addEntry: (id: string, body: Record<string, unknown>) =>
    unwrap<any>(api.post(`/admin/ledger-books/${id}/entries`, body)),
  removeEntry: (entryId: string) => unwrap<any>(api.delete(`/admin/ledger-books/entries/${entryId}`)),
  parties: () => unwrap<{ code: string; name: string }[]>(api.get("/admin/ledger-books/parties")),
  partyStatement: (code: string, start?: string, end?: string) =>
    unwrap<any>(api.get(`/admin/ledger-books/parties/${code}/statement`, { params: { start, end } })),
  partyPdf: async (code: string, start?: string, end?: string): Promise<Blob> => {
    const res = await api.get(`/admin/ledger-books/parties/${code}/pdf`, {
      params: { start, end },
      responseType: "blob",
    });
    return res.data;
  },
  getFirm: () => unwrap<any>(api.get("/admin/ledger-books/firm")),
  setFirm: (body: { name?: string; address?: string; statutory?: string }) =>
    unwrap<any>(api.put("/admin/ledger-books/firm", body)),
  pdf: async (id: string, start?: string, end?: string): Promise<Blob> => {
    const res = await api.get(`/admin/ledger-books/${id}/pdf`, {
      params: { start, end },
      responseType: "blob",
    });
    return res.data;
  },
};

export const AdminFundAPI = {
  addToMember: (
    memberId: string, amount: number, description?: string, paymentMode?: string,
    /** SA only — "MAIN" or "KUBER". Unset keeps the per-admin default plan. */
    source?: string,
  ) =>
    unwrap<any>(api.post(`/admin/fund/members/${memberId}/add`, { amount, description, payment_mode: paymentMode, source })),
  coinSummary: () => unwrap<any>(api.get("/admin/fund/coin-summary")),
  deductFromMember: (memberId: string, amount: number, description?: string, paymentMode?: string) =>
    unwrap<any>(api.post(`/admin/fund/members/${memberId}/deduct`, { amount, description, payment_mode: paymentMode })),
  createRequest: (amount: number, reason?: string) =>
    unwrap<any>(api.post("/admin/fund/requests", { amount, reason })),
  transferToAdmin: (target: string, amount: number, description?: string) =>
    unwrap<any>(api.post("/admin/fund/transfer", { target, amount, description })),
  incoming: (status = "PENDING") =>
    unwrap<any[]>(api.get("/admin/fund/requests/incoming", { params: { status } })),
  mine: () => unwrap<any[]>(api.get("/admin/fund/requests/mine")),
  resolve: (reqId: string, approve: boolean, remarks?: string) =>
    unwrap<any>(api.put(`/admin/fund/requests/${reqId}`, { approve, remarks })),
};

export const AdminReferralAPI = {
  eligibility: () => unwrap<any>(api.get("/admin/referral/eligibility")),
  updateEligibility: (body: {
    enabled?: boolean;
    threshold_amount?: number;
    threshold_unit?: string;
  }) => unwrap<any>(api.put("/admin/referral/eligibility", body)),
  userToggles: (userId: string, body: Record<string, boolean>) =>
    unwrap<any>(api.put(`/admin/referral/users/${userId}/toggles`, body)),
};

export const UsersAPI = {
  list: (params?: any) => unwrap<{ items: any[]; meta: any }>(api.get("/admin/users", { params })),
  detail: (id: string) => unwrap<any>(api.get(`/admin/users/${id}`)),
  create: (body: any) => unwrap<any>(api.post("/admin/users", body)),
  update: (id: string, body: any) => unwrap<any>(api.put(`/admin/users/${id}`, body)),
  block: (id: string, reason?: string) => unwrap<any>(api.post(`/admin/users/${id}/block`, { reason })),
  unblock: (id: string) => unwrap<any>(api.post(`/admin/users/${id}/unblock`)),
  // Per-user auto-settlement toggle. ON (default): wallet auto-floors
  // at 0 + books shortfall to settlement_outstanding. OFF: wallet
  // allowed to go negative + a pending SettlementRequest queued for
  // admin approval (Payments → Settlement Requests).
  setAutoSettlement: (id: string, enabled: boolean) =>
    unwrap<any>(api.post(`/admin/users/${id}/auto-settlement`, { enabled })),
  resetPassword: (id: string, new_password: string) =>
    unwrap<any>(api.post(`/admin/users/${id}/reset-password`, { new_password })),
  walletAdjust: (id: string, body: { amount: number; narration: string; transaction_type?: string }) =>
    unwrap<any>(api.post(`/admin/users/${id}/wallet-adjust`, body)),
  creditLimit: (id: string, body: { delta: number; narration: string }) =>
    api.patch(`/admin/users/${id}/credit-limit`, body).then((r) => r.data?.data ?? r.data),
  killSwitch: (id: string, reason?: string) =>
    api.post(`/admin/users/${id}/kill-switch`, { reason }).then((r) => r.data?.data ?? r.data),
  impersonate: (id: string) =>
    api.post(`/admin/users/${id}/impersonate`).then((r) => r.data?.data ?? r.data),
  delete: (id: string) => unwrap<any>(api.delete(`/admin/users/${id}`)),
  liveTradeStats: (id: string) =>
    unwrap<any>(api.get(`/admin/users/${id}/live-trade-stats`)),
  // Aggregated live snapshot of available balance + open P&L + equity
  // (available + open_pnl) across the given users. Polled by the
  // /users table so the OPEN P&L column updates at the same cadence
  // as the customer-side terminal. Pass the IDs visible on the current
  // page; the backend caps to 200 ids per call.
  liveStats: (user_ids?: string[]) =>
    unwrap<{
      items: Array<{
        user_id: string;
        available_balance: string;
        open_pnl: string;
        equity: string;
        used_margin: string;
        credit_limit: string;
      }>;
    }>(
      api.get("/admin/users/live-stats", {
        params: user_ids && user_ids.length > 0
          ? { user_ids: user_ids.join(",") }
          : undefined,
      }),
    ),
};

export const RiskAPI = {
  getGlobal: () => unwrap<any>(api.get("/admin/risk/global")),
  updateGlobal: (patch: any) => unwrap<any>(api.put("/admin/risk/global", { patch })),
  getUser: (userId: string) => unwrap<any>(api.get(`/admin/risk/user/${userId}`)),
  upsertUser: (userId: string, patch: any) =>
    unwrap<any>(api.put(`/admin/risk/user/${userId}`, { patch })),
  deleteUser: (userId: string) => unwrap<any>(api.delete(`/admin/risk/user/${userId}`)),
  copyFromUser: (userId: string, sourceUserId: string) =>
    unwrap<any>(api.post(`/admin/risk/user/${userId}/copy-from/${sourceUserId}`)),
  effective: (userId: string) => unwrap<any>(api.get(`/admin/risk/user/${userId}/effective`)),
  usersWithOverrides: () => unwrap<any[]>(api.get("/admin/risk/users-with-overrides")),
  // Per trading-wallet (multi-wallet) risk overlays.
  getWallets: () => unwrap<any>(api.get("/admin/risk/wallet")),
  upsertWallet: (kind: string, patch: any) =>
    unwrap<any>(api.put(`/admin/risk/wallet/${kind}`, { patch })),
  deleteWallet: (kind: string) => unwrap<any>(api.delete(`/admin/risk/wallet/${kind}`)),
};

export const NettingAPI = {
  segments: () => unwrap<any[]>(api.get("/admin/netting/segments")),
  getSegment: (id: string) => unwrap<any>(api.get(`/admin/netting/segments/${id}`)),
  updateSegment: (id: string, patch: any) =>
    unwrap<any>(api.put(`/admin/netting/segments/${id}`, { patch })),
  // Per-admin segment settings — SUPER-ADMIN sets a SPECIFIC admin's (clamped to
  // the SA ceiling). Powers the sub-admin 3-dot "Segment settings" editor.
  segmentsForSubAdmin: (adminId: string) =>
    unwrap<any[]>(api.get(`/admin/netting/sub-admin/${adminId}/segments`)),
  updateSegmentForSubAdmin: (adminId: string, id: string, patch: any) =>
    unwrap<any>(api.put(`/admin/netting/sub-admin/${adminId}/segments/${id}`, { patch })),
  // Per-broker segment settings — a PARENT (admin, or broker for its sub-broker)
  // sets a CHILD broker's per-segment settings (freezes a fixed-brokerage take).
  segmentsForBroker: (brokerId: string) =>
    unwrap<any[]>(api.get(`/admin/netting/broker/${brokerId}/segments`)),
  updateSegmentForBroker: (brokerId: string, id: string, patch: any) =>
    unwrap<any>(api.put(`/admin/netting/broker/${brokerId}/segments/${id}`, { patch })),
  scripts: (segment?: string) =>
    unwrap<any[]>(api.get("/admin/netting/scripts", { params: segment ? { segment } : {} })),
  createScript: (body: any) => unwrap<any>(api.post("/admin/netting/scripts", body)),
  // Bulk "Select all" — adds one override row per symbol in a single call.
  createScriptsBulk: (body: { segment_id: string; segment_name: string; symbols: string[] }) =>
    unwrap<{ created: number; total: number }>(api.post("/admin/netting/scripts/bulk", body)),
  updateScript: (id: string, patch: any) =>
    unwrap<any>(api.put(`/admin/netting/scripts/${id}`, { patch })),
  deleteScript: (id: string) => unwrap<any>(api.delete(`/admin/netting/scripts/${id}`)),
  userOverrides: (userId: string) => unwrap<any[]>(api.get(`/admin/netting/user/${userId}`)),
  // Per-segment camelCase values the user INHERITS (pool cascade below their
  // own override). Used to fill the User-Overrides cells' placeholder with the
  // currently-effective value instead of the word "inherit".
  userInherited: (userId: string) =>
    unwrap<Record<string, Record<string, any>>>(api.get(`/admin/netting/user/${userId}/effective`)),
  upsertUserOverride: (userId: string, segmentName: string, patch: any, symbol?: string) =>
    unwrap<any>(
      api.put(`/admin/netting/user/${userId}/${segmentName}`, { patch }, { params: symbol ? { symbol } : {} })
    ),
  deleteUserOverride: (userId: string, segmentName: string, symbol?: string) =>
    unwrap<any>(
      api.delete(`/admin/netting/user/${userId}/${segmentName}`, { params: symbol ? { symbol } : {} })
    ),
  /** Wipe ALL UserSegmentOverride rows for this user so they snap back
   *  to the inherited cascade (broker / admin / super-admin / platform
   *  defaults). Returns the count removed. */
  clearAllUserOverrides: (userId: string) =>
    unwrap<{ ok: boolean; deleted: number }>(
      api.delete(`/admin/netting/user/${userId}`),
    ),
  copy: (body: { source_user_id: string; target_user_ids: string[]; overwrite?: boolean }) =>
    unwrap<any>(api.post("/admin/netting/copy", body)),
  usersWithOverrides: () => unwrap<any[]>(api.get("/admin/netting/users-with-overrides")),
};

export const TradingAPI = {
  orders: (params?: any) => unwrap<{ items: any[]; meta: any }>(api.get("/admin/orders", { params })),
  // Today's trading summary (IST day) for the Orders monitor header —
  // executed BUY/SELL fill counts, their total, and the live pending count.
  ordersStats: () =>
    unwrap<{
      date_ist: string;
      total_trades: number;
      buy_trades: number;
      sell_trades: number;
      pending_orders: number;
    }>(api.get("/admin/orders/stats")),
  forceCancel: (id: string) => unwrap<any>(api.delete(`/admin/orders/${id}`)),
  positions: (params?: any) => unwrap<any[]>(api.get("/admin/positions", { params })),
  // Server-side paginated variant — pass `page` to get { rows, total, … }
  // instead of a flat array. Used by the Closed Trades tab so only one
  // page (e.g. 25 rows) is fetched + enriched per request.
  positionsPaged: (params?: any) =>
    unwrap<{ rows: any[]; total: number; page: number; page_size: number; total_pages: number }>(
      api.get("/admin/positions", { params }),
    ),
  // A user's FIFO closed blotter — the SAME per-opening-fill rows the user
  // sees in their own Closed history (one row per opening-fill × closing-fill
  // pairing), not one aggregated row per position. Per-user (`user_id` req).
  closedFifo: (params: { user_id: string; page?: number; page_size?: number }) =>
    unwrap<{ rows: any[]; total: number; page: number; page_size: number }>(
      api.get("/admin/positions/closed-fifo", { params }),
    ),
  orderQuotes: (tokens: string[]) =>
    unwrap<any[]>(api.get("/admin/orders/quotes", { params: { tokens: tokens.join(",") } })),
  squareoff: (id: string) => unwrap<any>(api.post(`/admin/positions/${id}/squareoff`)),
  deletePosition: (id: string) => unwrap<any>(api.delete(`/admin/positions/${id}`)),
  positionNetting: (id: string) =>
    unwrap<any>(api.get(`/admin/positions/${id}/netting`)),
  pnlSummary: (params?: { user_id?: string }) =>
    unwrap<any>(api.get("/admin/positions/pnl-summary", { params })),
  emergencySquareoffAll: () => unwrap<any>(api.post("/admin/positions/emergency-squareoff")),
  editPosition: (
    id: string,
    body: Partial<{
      avg_price: number | string;
      quantity: number;
      opened_at: string;
      stop_loss: number | string | null;
      target: number | string | null;
      // Closed-position only — admin corrections + relabel
      realized_pnl: number | string;
      close_reason: string;
    }>,
  ) => unwrap<any>(api.patch(`/admin/positions/${id}`, body)),
  reopenPosition: (id: string) =>
    unwrap<any>(api.post(`/admin/positions/${id}/reopen`)),
  trades: (params?: any) => unwrap<any[]>(api.get("/admin/trades", { params })),
  holdings: (params?: any) => unwrap<any[]>(api.get("/admin/holdings", { params })),
};

export const MarketControlAPI = {
  list: () =>
    unwrap<{ segment: string; label: string; enabled: boolean; open_time: string; close_time: string }[]>(
      api.get("/admin/market-control"),
    ),
  set: (segment: string, body: { enabled?: boolean; open_time?: string; close_time?: string }) =>
    unwrap<any>(api.put(`/admin/market-control/${segment}`, body)),
};

export const TransactionHistoryAPI = {
  list: (params?: { source?: string; admin_id?: string; limit?: number }) =>
    unwrap<{
      rows: any[];
      admins: { id: string; label: string }[];
      games: { key: string; label: string }[];
      is_super: boolean;
    }>(api.get("/admin/transaction-history", { params })),
  reconciliation: () =>
    unwrap<{ is_super: boolean; rows: any[]; totals: any }>(
      api.get("/admin/transaction-history/reconciliation"),
    ),
};

// Super-admin section-wise ledger (cash / funding / pnl / brokerage / games).
export const SaLedgerAPI = {
  get: () => unwrap<{ cash: any; rows: any[]; totals: any }>(api.get("/admin/sa-ledger")),
  cashTopup: (amount: number) =>
    unwrap<{ sa_cash_balance: string }>(api.post("/admin/sa-ledger/cash-topup", { amount })),
  drill: (adminId: string) =>
    unwrap<{ users: any[]; brokers: any[] }>(api.get(`/admin/sa-ledger/admin/${adminId}/drill`)),
  kuberRecon: () =>
    unwrap<{
      credit: number; baseline_set: boolean; kuber_balance: number; main: number;
      sum_pools: number; unassigned: number; debit: number; delta: number;
      matched: boolean; rows: any[];
    }>(api.get("/admin/sa-ledger/kuber-recon")),
  kuberReconReset: () =>
    unwrap<{ base: number }>(api.post("/admin/sa-ledger/kuber-recon/reset", {})),
};

export const BanSecurityAPI = {
  list: () => unwrap<any[]>(api.get("/admin/ban-security")),
  ban: (body: { token: string; admin_id?: string | null }) =>
    unwrap<any>(api.post("/admin/ban-security", body)),
  unban: (id: string) => unwrap<any>(api.delete(`/admin/ban-security/${id}`)),
};

export const PayinOutAPI = {
  // Deposits / withdrawals are paginated (15 per page by default).
  // Pass `status` empty / undefined to get every status.
  deposits: (params?: { status?: string; page?: number; page_size?: number }) =>
    unwrap<{ items: any[]; meta: { page: number; page_size: number; total: number; total_pages: number } }>(
      api.get("/admin/deposits", { params }),
    ),
  approveDeposit: (id: string, admin_remark?: string) =>
    unwrap<any>(api.post(`/admin/deposits/${id}/approve`, { admin_remark })),
  rejectDeposit: (id: string, admin_remark: string) =>
    unwrap<any>(api.post(`/admin/deposits/${id}/reject`, { admin_remark })),
  // Settlement requests — queued by wallet_service when an auto-OFF
  // user's balance goes negative. Approval triggers the floor-to-0 +
  // settlement booking that auto-mode would have done; rejection
  // leaves the wallet negative (user stays blocked from new opens).
  settlementRequests: (status?: string) =>
    unwrap<any[]>(api.get("/admin/settlement-requests", { params: { status } })),
  approveSettlement: (id: string) =>
    unwrap<any>(api.post(`/admin/settlement-requests/${id}/approve`)),
  rejectSettlement: (id: string, reason: string) =>
    unwrap<any>(api.post(`/admin/settlement-requests/${id}/reject`, { reason })),
  getPoolAutoSettlement: () =>
    unwrap<{ main: boolean; kinds: Record<string, boolean> }>(
      api.get("/admin/pool-auto-settlement"),
    ),
  setPoolAutoSettlement: (enabled: boolean, scope: string = "MAIN") =>
    unwrap<{ scope: string; enabled: boolean; users_updated?: number }>(
      api.post("/admin/pool-auto-settlement", { enabled, scope }),
    ),
  withdrawals: (params?: { status?: string; page?: number; page_size?: number }) =>
    unwrap<{ items: any[]; meta: { page: number; page_size: number; total: number; total_pages: number } }>(
      api.get("/admin/withdrawals", { params }),
    ),
  approveWithdrawal: (id: string, body: any) => unwrap<any>(api.post(`/admin/withdrawals/${id}/approve`, body)),
  rejectWithdrawal: (id: string, rejection_reason: string) =>
    unwrap<any>(api.post(`/admin/withdrawals/${id}/reject`, { rejection_reason })),
  bankAccounts: () => unwrap<any[]>(api.get("/admin/bank-accounts")),
  createBank: (body: any) => unwrap<any>(api.post("/admin/bank-accounts", body)),
  updateBank: (id: string, body: any) => unwrap<any>(api.put(`/admin/bank-accounts/${id}`, body)),
  deleteBank: (id: string) => unwrap<any>(api.delete(`/admin/bank-accounts/${id}`)),
  // Tier-aware: returns the caller's OWN tier override (sparse) plus the
  // fully-resolved effective values + per-field source labels. See the
  // backend `GET /admin/wd-rules` docstring for the response shape.
  wdRules: () =>
    unwrap<{
      tier: "super_admin" | "admin" | "broker";
      owner_id: string;
      rules: Array<{
        rule_type: "DEPOSIT" | "WITHDRAWAL";
        own: Record<string, any>;
        effective: Record<string, any>;
        sources: Record<string, string>;
      }>;
    }>(api.get("/admin/wd-rules")),
  // Sparse PATCH — fields omitted stay as-is, fields sent as `null`
  // explicitly clear the override at this tier (so the field starts
  // inheriting from the layer below). `tier=global` is honoured only
  // when the caller is super-admin.
  updateWdRule: (rule_type: string, body: any, tier?: "global") =>
    unwrap<any>(
      api.put(`/admin/wd-rules/${rule_type}`, body, {
        params: tier ? { tier } : undefined,
      }),
    ),
};

export const InstrumentAdminAPI = {
  list: (params?: any) => unwrap<{ items: any[]; meta: any }>(api.get("/admin/instruments", { params })),
  create: (body: any) => unwrap<any>(api.post("/admin/instruments", body)),
  update: (id: string, body: any) => unwrap<any>(api.put(`/admin/instruments/${id}`, body)),
  halt: (id: string, reason?: string) => unwrap<any>(api.post(`/admin/instruments/${id}/halt`, { reason })),
  resume: (id: string) => unwrap<any>(api.post(`/admin/instruments/${id}/resume`)),
  delete: (id: string) => unwrap<any>(api.delete(`/admin/instruments/${id}`)),
  // Deduped underlyings for the script-override typeahead. Each result
  // is just the underlying name (NIFTY, BANKNIFTY, …); the picker
  // appends `FUT` / `CE` / `PE` to form the pattern that the resolver
  // applies to every contract of that underlying.
  underlyings: (params: { exchange: string; contract_type?: "FUT" | "CE" | "PE"; q?: string; limit?: number }) =>
    unwrap<string[]>(api.get("/admin/instruments/underlyings", { params })),
  // Batch quote feed for the admin Market Watch page. Returns
  // [{token, bid, ask, ltp, change_pct, ...}] in the same shape as
  // useMarketStream's seed. Empty token list → empty result.
  quotesBatch: (tokens: string[]) =>
    unwrap<any[]>(
      api.get("/admin/instruments/quotes/batch", {
        params: { tokens: tokens.join(",") },
      }),
    ),
};

// ── Admin Market Watch ───────────────────────────────────────────────
// Per-segment managed lists + place orders on behalf of users in scope.
// Mirrors the user-side MarketwatchAPI shape so the row renderer can
// be lifted into a shared component later if needed.
export const AdminMarketwatchAPI = {
  segmentItems: (segment: string) =>
    unwrap<any[]>(api.get(`/admin/marketwatch/segment/${segment}/items`)),
  addItem: (segment: string, token: string) =>
    unwrap<any>(api.post(`/admin/marketwatch/segment/${segment}/items`, { token })),
  removeItem: (segment: string, token: string) =>
    unwrap<any>(api.delete(`/admin/marketwatch/segment/${segment}/items/${token}`)),
  quotes: (segment: string) =>
    unwrap<any[]>(api.get(`/admin/marketwatch/segment/${segment}/quotes`)),
  search: (segment: string, q: string, limit = 30) =>
    unwrap<any[]>(
      api.get(`/admin/marketwatch/segment/${segment}/search`, {
        params: { q, limit },
      }),
    ),
  placeOrders: (body: {
    token: string;
    user_ids: string[];
    action: "BUY" | "SELL";
    order_type: "MARKET" | "MANUAL";
    product_type: "MIS" | "NRML" | "CNC";
    lots: number;
    price?: number;
  }) => unwrap<{ placed: any[]; failed: any[] }>(api.post("/admin/marketwatch/place-orders", body)),
};

export const BrokerageAPI = {
  list: () => unwrap<any[]>(api.get("/admin/brokerage/plans")),
  create: (body: any) => unwrap<any>(api.post("/admin/brokerage/plans", body)),
  update: (id: string, body: any) => unwrap<any>(api.put(`/admin/brokerage/plans/${id}`, body)),
  delete: (id: string) => unwrap<any>(api.delete(`/admin/brokerage/plans/${id}`)),
};

export const KycAPI = {
  list: (status?: string) =>
    unwrap<any[]>(api.get("/admin/kyc", { params: status ? { status } : {} })),
  detail: (id: string) => unwrap<any>(api.get(`/admin/kyc/${id}`)),
  approve: (id: string, admin_remark?: string) =>
    unwrap<any>(api.post(`/admin/kyc/${id}/approve`, { admin_remark })),
  reject: (id: string, rejection_reason: string, admin_remark?: string) =>
    unwrap<any>(api.post(`/admin/kyc/${id}/reject`, { rejection_reason, admin_remark })),
};

// Admin notification bell — backed by /admin/notifications endpoints.
// Each row is per-(recipient_admin, event); backend already filters by
// the caller's admin id, so no scope param is needed here.
export const NotificationsAPI = {
  list: (params?: { only_unread?: boolean; limit?: number }) =>
    unwrap<any[]>(api.get("/admin/notifications", { params })),
  unreadCount: () =>
    unwrap<{ count: number }>(api.get("/admin/notifications/unread-count")),
  markRead: (id: string) =>
    unwrap<any>(api.post(`/admin/notifications/${id}/read`)),
  markAllRead: () =>
    unwrap<{ marked: number }>(api.post("/admin/notifications/mark-all-read")),
};

export const SupportAPI = {
  get: () => unwrap<{ whatsapp: string; role: string }>(api.get("/admin/support")),
  set: (whatsapp: string) =>
    unwrap<{ whatsapp: string; role: string }>(api.put("/admin/support", { whatsapp })),
  getTerms: () =>
    unwrap<{ text: string; enabled: boolean; role: string }>(
      api.get("/admin/support/terms"),
    ),
  setTerms: (text: string, enabled: boolean) =>
    unwrap<{ text: string; enabled: boolean; role: string }>(
      api.put("/admin/support/terms", { text, enabled }),
    ),
};

export const LedgerAdminAPI = {
  list: (params?: any) => unwrap<{ items: any[]; meta: any }>(api.get("/admin/ledger", { params })),
  manualEntry: (body: any) => unwrap<any>(api.post("/admin/ledger/manual-entry", body)),
};

export type MoneyFilterParams = { preset?: string; from_date?: string; to_date?: string };
export const MoneyAPI = {
  users: (params?: MoneyFilterParams) =>
    unwrap<{ totals: any; users: any[]; filter: { label: string } }>(
      api.get("/admin/money-transactions/users", { params }),
    ),
  brokers: (params?: MoneyFilterParams) =>
    unwrap<{ totals: any; brokers: any[]; filter: { label: string } }>(
      api.get("/admin/money-transactions/brokers", { params }),
    ),
};

export const ReportsAdminAPI = {
  users: () => unwrap<any>(api.get("/admin/reports/users")),
  financial: () => unwrap<any>(api.get("/admin/reports/financial")),
  trades: () => unwrap<any>(api.get("/admin/reports/trades")),
  compliance: () => unwrap<any>(api.get("/admin/reports/compliance")),
  tradebookPdf: async (
    userId: string,
    fromDate?: string,
    toDate?: string,
  ): Promise<Blob> => {
    const params: Record<string, string> = { user_id: userId };
    if (fromDate) params.from_date = fromDate;
    if (toDate) params.to_date = toDate;
    const res = await api.get("/admin/reports/tradebook/pdf", {
      params,
      responseType: "blob",
    });
    return res.data;
  },
};

export const ZerodhaAPI = {
  status: (account = 0) =>
    api.get("/admin/zerodha/status", { params: { account } }).then((r) => (r.data?.status ?? r.data)),
  settings: (account = 0) =>
    api.get("/admin/zerodha/settings", { params: { account } }).then((r) => (r.data?.settings ?? r.data)),
  saveSettings: (body: any, account = 0) =>
    api.post("/admin/zerodha/settings", body, { params: { account } }).then((r) => r.data),
  loginUrl: (account = 0) =>
    api.get("/admin/zerodha/login-url", { params: { account } }).then((r) => r.data?.loginUrl as string),
  logout: (account = 0) => api.post("/admin/zerodha/logout", null, { params: { account } }).then((r) => r.data),
  connectWs: () => api.post("/admin/zerodha/connect-ws").then((r) => r.data),
  disconnectWs: () => api.post("/admin/zerodha/disconnect-ws").then((r) => r.data),
  // Same effect as a backend systemctl restart for the ticker: stops
  // the existing socket, clears the heal-failure counter (so the
  // self-heal loop drops back to 30 s cadence instead of the 5 min
  // exponential-cap), refreshes the captured event loop, then runs
  // connect_ws(force=True). Lets the operator fix a stuck WS after
  // the daily 08:00 IST token rotation without SSH'ing into the box.
  forceReconnectWs: () =>
    api.post("/admin/zerodha/force-reconnect-ws").then((r) => r.data),
  // Dual-account HA failover: exchange→account routing + live health.
  routing: () => api.get("/admin/zerodha/routing").then((r) => r.data),
  updateRouting: (body: any) =>
    api.put("/admin/zerodha/routing", body).then((r) => r.data),
  failoverTestDisconnect: (account: number) =>
    api
      .post("/admin/zerodha/routing/test-disconnect", null, { params: { account } })
      .then((r) => r.data),
  searchInstruments: (query: string, segment?: string) =>
    api
      .get("/admin/zerodha/instruments/search", { params: { query, segment } })
      .then((r) => (r.data?.instruments ?? []) as any[]),
  subscribe: (instrument: any) =>
    api.post("/admin/zerodha/instruments/subscribe", { instrument }).then((r) => r.data),
  subscribeBulk: (instruments: any[]) =>
    api.post("/admin/zerodha/instruments/subscribe-bulk", { instruments }).then((r) => r.data),
  unsubscribe: (token: number) =>
    api.delete(`/admin/zerodha/instruments/${token}`).then((r) => r.data),
  syncInstruments: () =>
    api.post("/admin/zerodha/instruments/sync").then((r) => r.data),
  clearInstruments: () =>
    api.post("/admin/zerodha/instruments/clear").then((r) => r.data),
  trimInstruments: (keep_count = 700) =>
    api
      .post("/admin/zerodha/instruments/trim", { keep_count })
      .then((r) => r.data as { kept: number; removed: number; must_keep_added: number }),
  listForExchange: (exchange: string) =>
    api
      .get(`/admin/zerodha/instruments/exchange/${encodeURIComponent(exchange)}`)
      .then((r) => (r.data?.instruments ?? []) as any[]),
  listSubscribed: () =>
    api
      .get("/admin/zerodha/instruments/subscribed")
      .then((r) => (r.data?.instruments ?? []) as any[]),
  connectWithToken: (request_token: string, account = 0) =>
    api
      .post("/admin/zerodha/connect-with-token", { request_token }, { params: { account } })
      .then((r) => r.data),
  debugCsv: (exchange = "NFO") =>
    api
      .get("/admin/zerodha/debug-csv", { params: { exchange } })
      .then((r) => r.data),
  diagnose: () =>
    api
      .get("/admin/zerodha/diagnose")
      .then((r) => r.data?.report ?? r.data),
};

// ─────────────────────────────────────────────────────────────────────
// Zerodha auto-login (daily scheduled token refresh via Playwright).
// All endpoints are super-admin gated server-side.
// ─────────────────────────────────────────────────────────────────────

export type ZerodhaAutoLoginStatus = {
  is_configured: boolean;
  is_enabled: boolean;
  schedule_time_ist: string;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_status: "" | "success" | "failed";
  last_error_detail: string | null;
  last_stage: string | null;
  consecutive_failures: number;
  last_duration_ms: number | null;
  username_masked: string;
};

export type ZerodhaAutoLoginTestResult = {
  success: boolean;
  error?: string;
  stage?: string;
  duration_ms?: number;
  access_token_obtained?: boolean;
};

export const ZerodhaAutoLoginAPI = {
  status: (account = 0) =>
    api
      .get("/admin/zerodha/auto-login", { params: { account } })
      .then((r) => r.data?.status as ZerodhaAutoLoginStatus),

  updateCredentials: (
    body: { username: string; password: string; totp_secret: string },
    account = 0,
  ) =>
    api
      .put("/admin/zerodha/auto-login/credentials", body, { params: { account } })
      .then((r) => r.data?.status as ZerodhaAutoLoginStatus),

  toggle: (enabled: boolean, account = 0) =>
    api
      .post("/admin/zerodha/auto-login/toggle", { enabled }, { params: { account } })
      .then((r) => r.data?.status as ZerodhaAutoLoginStatus),

  setSchedule: (schedule_time_ist: string, account = 0) =>
    api
      .put("/admin/zerodha/auto-login/schedule", { schedule_time_ist }, { params: { account } })
      .then((r) => r.data?.status as ZerodhaAutoLoginStatus),

  testNow: (account = 0) =>
    api.post("/admin/zerodha/auto-login/test", null, { params: { account } }).then(
      (r) =>
        r.data as {
          result: ZerodhaAutoLoginTestResult;
          status: ZerodhaAutoLoginStatus;
        },
    ),

  resetLock: (account = 0) =>
    api
      .post("/admin/zerodha/auto-login/reset-lock", null, { params: { account } })
      .then((r) => r.data?.status as ZerodhaAutoLoginStatus),
};

export const BrokerMgmtAPI = {
  // Cap — drives the create/edit form so OFF/VIEW/EDIT radio options
  // above the actor's own level are greyed out.
  maxGrantable: () =>
    unwrap<{ cap: Record<string, "OFF" | "VIEW" | "EDIT"> }>(
      api.get("/admin/management/brokers/max-grantable"),
    ),

  // Broker CRUD (admin/super-admin creates; broker can create sub-broker
  // when broker_permissions.sub_brokers == EDIT)
  list: (params?: { q?: string; status?: string; page?: number; page_size?: number; include_sub?: boolean }) =>
    unwrap<{ items: any[]; meta: any }>(api.get("/admin/management/brokers", { params })),
  get: (id: string) => unwrap<any>(api.get(`/admin/management/brokers/${id}`)),
  create: (body: {
    full_name: string;
    email: string;
    mobile: string;
    password: string;
    permissions: Record<string, "OFF" | "VIEW" | "EDIT">;
    pnl_share_pct: number | string;
    brokerage_share_pct?: number | string;
    opening_fund?: number;
    assigned_admin_id?: string;
    is_fixed_brokerage?: boolean;
    fixed_brokerage_unit?: string;
    fixed_brokerage_rate?: number | string;
  }) => unwrap<any>(api.post("/admin/management/brokers", body)),
  update: (id: string, body: { full_name?: string }) =>
    unwrap<any>(api.put(`/admin/management/brokers/${id}`, body)),
  updatePermissions: (id: string, permissions: Record<string, "OFF" | "VIEW" | "EDIT">) =>
    unwrap<{ broker: any; cascaded_changes: any[] }>(
      api.put(`/admin/management/brokers/${id}/permissions`, { permissions }),
    ),
  updatePnlShare: (id: string, pct: number | string, brokerage_pct?: number | string) =>
    unwrap<any>(api.put(`/admin/management/brokers/${id}/pnl-share`, { pct, brokerage_pct })),
  updateFixedBrokerage: (
    id: string,
    body: { is_fixed_brokerage: boolean; fixed_brokerage_unit?: string; fixed_brokerage_rate?: number | string },
  ) => unwrap<any>(api.put(`/admin/management/brokers/${id}/fixed-brokerage`, body)),
  block: (id: string) => unwrap<any>(api.post(`/admin/management/brokers/${id}/block`)),
  unblock: (id: string) => unwrap<any>(api.post(`/admin/management/brokers/${id}/unblock`)),
  // 409 while the broker still has live clients / sub-brokers / wallet funds —
  // the message names what to clear first, so surface it verbatim.
  remove: (id: string) => unwrap<any>(api.delete(`/admin/management/brokers/${id}`)),
  resetPassword: (id: string, new_password: string) =>
    unwrap<any>(
      api.post(`/admin/management/brokers/${id}/reset-password`, { new_password }),
    ),

  // Subtree clients (every CLIENT/DEALER/MASTER under this broker)
  listSubtreeUsers: (id: string, params?: { page?: number; page_size?: number }) =>
    unwrap<{ items: any[]; meta: any }>(
      api.get(`/admin/management/brokers/${id}/users`, { params }),
    ),

  // Reassignment
  assignUser: (userId: string, broker_id: string | null) =>
    unwrap<any>(api.post(`/admin/management/users/${userId}/assign-to-broker`, { broker_id })),
  bulkAssign: (user_ids: string[], broker_id: string | null) =>
    unwrap<any>(api.post("/admin/management/users/bulk-assign-to-broker", { user_ids, broker_id })),

  // Detail-page aggregator
  report: (id: string) =>
    unwrap<any>(api.get(`/admin/management/brokers/${id}/report`)),

  // Login-as — same shape as ManagementAPI.impersonateSubAdmin
  impersonate: (id: string) =>
    api
      .post(`/admin/management/brokers/${id}/impersonate`)
      .then((r) => r.data?.data ?? r.data),

  // Settlements (admin reconciliation surface — broker doesn't see this)
  listSettlements: (week_start?: string) =>
    unwrap<{
      period_start: string;
      period_end: string;
      items: any[];
      totals: { user_count: number; net_house_pnl_inr: string; broker_share_inr: string };
    }>(api.get("/admin/management/broker-settlements", { params: week_start ? { week_start } : {} })),
  historyForBroker: (id: string, params?: { from_date?: string; to_date?: string }) =>
    unwrap<{ broker: any; items: any[] }>(
      api.get(`/admin/management/broker-settlements/broker/${id}`, { params }),
    ),
  recomputeSettlements: (body: { week_start: string; broker_id?: string }) =>
    unwrap<{ items: any[]; frozen_skipped: number }>(
      api.post("/admin/management/broker-settlements/recompute", body),
    ),
  finalizeSettlement: (id: string) =>
    unwrap<any>(api.post(`/admin/management/broker-settlements/${id}/finalize`)),
  markPaid: (id: string, notes?: string) =>
    unwrap<any>(api.post(`/admin/management/broker-settlements/${id}/mark-paid`, { notes })),
};

export const ManagementAPI = {
  // Sub-admins
  listSubAdmins: (params?: { q?: string; status?: string; page?: number; page_size?: number }) =>
    unwrap<{ items: any[]; meta: any }>(api.get("/admin/management/sub-admins", { params })),
  getSubAdmin: (id: string) => unwrap<any>(api.get(`/admin/management/sub-admins/${id}`)),
  createSubAdmin: (body: {
    full_name: string;
    email: string;
    mobile: string;
    password: string;
    permissions: Record<string, boolean>;
    pnl_share_pct: number | string;
    brokerage_share_pct?: number | string;
    opening_fund?: number;
    is_fixed_brokerage?: boolean;
    fixed_brokerage_unit?: string;
    fixed_brokerage_rate?: number | string;
    no_self_brokerage?: boolean;
  }) => unwrap<any>(api.post("/admin/management/sub-admins", body)),
  updateFixedBrokerage: (
    id: string,
    body: { is_fixed_brokerage: boolean; fixed_brokerage_unit?: string; fixed_brokerage_rate?: number | string },
  ) => unwrap<any>(api.put(`/admin/management/sub-admins/${id}/fixed-brokerage`, body)),
  setExpiryEditAllowed: (id: string, allowed: boolean) =>
    unwrap<any>(api.put(`/admin/management/sub-admins/${id}/expiry-edit-allowed`, { allowed })),

  setTradingReferralEnabled: (id: string, enabled: boolean) =>
    unwrap<any>(
      api.put(`/admin/management/sub-admins/${id}/trading-referral-enabled`, { enabled })
    ),
  updateSubAdmin: (id: string, body: { full_name?: string }) =>
    unwrap<any>(api.put(`/admin/management/sub-admins/${id}`, body)),
  updatePermissions: (id: string, permissions: Record<string, boolean>) =>
    unwrap<any>(api.put(`/admin/management/sub-admins/${id}/permissions`, { permissions })),
  updatePnlShare: (id: string, pct: number | string, brokerage_share_pct?: number | string) =>
    unwrap<any>(
      api.put(`/admin/management/sub-admins/${id}/pnl-share`, {
        pct,
        ...(brokerage_share_pct !== undefined ? { brokerage_share_pct } : {}),
      }),
    ),
  blockSubAdmin: (id: string) =>
    unwrap<any>(api.post(`/admin/management/sub-admins/${id}/block`)),
  unblockSubAdmin: (id: string) =>
    unwrap<any>(api.post(`/admin/management/sub-admins/${id}/unblock`)),
  deleteSubAdmin: (id: string) =>
    unwrap<any>(api.delete(`/admin/management/sub-admins/${id}`)),
  resetSubAdminPassword: (id: string, new_password: string) =>
    unwrap<any>(api.post(`/admin/management/sub-admins/${id}/reset-password`, { new_password })),
  listAssignedUsers: (id: string, params?: { page?: number; page_size?: number }) =>
    unwrap<{ items: any[]; meta: any }>(
      api.get(`/admin/management/sub-admins/${id}/users`, { params })
    ),
  // User reassignment
  assignUser: (userId: string, sub_admin_id: string | null) =>
    unwrap<any>(api.post(`/admin/management/users/${userId}/assign`, { sub_admin_id })),
  bulkAssign: (user_ids: string[], sub_admin_id: string | null) =>
    unwrap<any>(api.post("/admin/management/users/bulk-assign", { user_ids, sub_admin_id })),
  // Settlements
  listSettlements: (week_start?: string) =>
    unwrap<{
      period_start: string;
      period_end: string;
      items: any[];
      totals: { user_count: number; net_house_pnl_inr: string; sub_admin_share_inr: string };
    }>(api.get("/admin/management/settlements", { params: week_start ? { week_start } : {} })),
  historyForSubAdmin: (id: string, params?: { from_date?: string; to_date?: string }) =>
    unwrap<{ sub_admin: any; items: any[] }>(
      api.get(`/admin/management/settlements/sub-admin/${id}`, { params })
    ),
  recomputeSettlements: (body: { week_start: string; sub_admin_id?: string }) =>
    unwrap<{ items: any[]; frozen_skipped: number }>(
      api.post("/admin/management/settlements/recompute", body)
    ),
  finalizeSettlement: (id: string) =>
    unwrap<any>(api.post(`/admin/management/settlements/${id}/finalize`)),
  markPaid: (id: string, notes?: string) =>
    unwrap<any>(api.post(`/admin/management/settlements/${id}/mark-paid`, { notes })),
  // Detail-page aggregator: user count, wallet, pnl windows, trade counts,
  // recent trades, weekly deposit/withdrawal flow.
  subAdminReport: (id: string) =>
    unwrap<any>(api.get(`/admin/management/sub-admins/${id}/report`)),
  // Login-as: returns admin-side tokens for the target sub-admin so the
  // frontend can drop them into the auth store and load that sub-admin's
  // dashboard view. Raw call (no unwrap) so we can read admin_app_url
  // alongside the token pair.
  impersonateSubAdmin: (id: string) =>
    api
      .post(`/admin/management/sub-admins/${id}/impersonate`)
      .then((r) => r.data?.data ?? r.data),
};

export const SettingsAPI = {
  platformList: (category?: string) => unwrap<any[]>(api.get("/admin/settings/platform", { params: { category } })),
  // Generic upsert — the backend creates the key if it does not exist and
  // files it under the dotted prefix as its category.
  platformSet: (key: string, value: unknown) =>
    unwrap<any>(api.put(`/admin/settings/platform/${key}`, { setting_value: value })),
  updatePlatform: (key: string, setting_value: any) =>
    unwrap<any>(api.put(`/admin/settings/platform/${encodeURIComponent(key)}`, { setting_value })),
  // Weekly mark-to-market settlement engine (super-admin only).
  weeklySettlementRun: () =>
    unwrap<{ week_key?: string; batch_id?: string; total?: number; settled?: number; skipped?: number; failed?: number; skipped_reason?: string }>(
      api.post("/admin/settings/weekly-settlement/run", null, { params: { force: true } }),
    ),
  setWeeklySettlementEnabled: (enabled: boolean) =>
    unwrap<{ enabled: boolean }>(api.put("/admin/settings/weekly-settlement/enabled", { setting_value: enabled })),
  // Admin fund-cap (float) kill-switch (super-admin only).
  adminFloatEnabled: () => unwrap<{ enabled: boolean }>(api.get("/admin/settings/admin-float")),
  setAdminFloatEnabled: (enabled: boolean) =>
    unwrap<{ enabled: boolean }>(api.put("/admin/settings/admin-float/enabled", { setting_value: enabled })),
  // Admin-book model (per-trade SA↔admin real-money settlement) kill-switch.
  adminBookEnabled: () => unwrap<{ enabled: boolean }>(api.get("/admin/settings/admin-book")),
  setAdminBookEnabled: (enabled: boolean) =>
    unwrap<{ enabled: boolean }>(api.put("/admin/settings/admin-book/enabled", { setting_value: enabled })),
  // Per-admin platform maintenance — each admin's own daily per-user charge +
  // zero-balance 7-day auto-close config (stored on the admin's own record).
  platformMaintenance: () =>
    unwrap<{ platform_charge_enabled: boolean; platform_charge_amount: string; zero_balance_autoclose_enabled: boolean }>(
      api.get("/admin/settings/platform-maintenance"),
    ),
  setPlatformMaintenance: (body: {
    platform_charge_enabled?: boolean;
    platform_charge_amount?: number;
    zero_balance_autoclose_enabled?: boolean;
  }) =>
    unwrap<{ platform_charge_enabled: boolean; platform_charge_amount: string; zero_balance_autoclose_enabled: boolean }>(
      api.put("/admin/settings/platform-maintenance", body),
    ),
  // Signup broker-search visibility — admin ids HIDDEN from the search (super-admin only).
  brokerSearchHidden: () => unwrap<{ hidden_admin_ids: string[] }>(api.get("/admin/settings/broker-search")),
  setBrokerSearchHidden: (hidden_admin_ids: string[]) =>
    unwrap<{ hidden_admin_ids: string[] }>(api.put("/admin/settings/broker-search", { hidden_admin_ids })),
  holidays: (year?: number) => unwrap<any[]>(api.get("/admin/holidays", { params: { year } })),
  createHoliday: (body: any) => unwrap<any>(api.post("/admin/holidays", body)),
  deleteHoliday: (id: string) => unwrap<any>(api.delete(`/admin/holidays/${id}`)),
  audit: (params?: any) => unwrap<{ items: any[]; meta: any }>(api.get("/admin/audit/logs", { params })),
  backupList: () => unwrap<any[]>(api.get("/admin/backup/list")),
  runBackup: () => unwrap<any>(api.post("/admin/backup/run")),
  eodReset: () => unwrap<any>(api.post("/admin/backup/eod-reset")),
};

// Admin-book SA earnings drill-down (per-trade SA↔admin share ledger).
export const AdminBookAPI = {
  report: (params?: { from_?: string; to?: string }) =>
    unwrap<any[]>(api.get("/admin/admin-book/report", { params })),
  users: (adminId: string, params?: { from_?: string; to?: string }) =>
    unwrap<any[]>(api.get(`/admin/admin-book/admin/${adminId}/users`, { params })),
  trades: (adminId: string, userId: string, params?: { from_?: string; to?: string }) =>
    unwrap<any[]>(api.get(`/admin/admin-book/admin/${adminId}/user/${userId}/trades`, { params })),
  transactions: (params?: { from_?: string; to?: string; limit?: number }) =>
    unwrap<any[]>(api.get("/admin/admin-book/transactions", { params })),
};

// Per-actor Expiry-Settings override (USER / BROKER / ADMIN tiers on top
// of the global PlatformSetting option_chain.* keys).
export const ExpiryOverridesAPI = {
  get: (actor_kind: "USER" | "BROKER" | "ADMIN", actor_id: string) =>
    unwrap<{
      id: string | null;
      actor_kind: string;
      actor_id: string;
      underlyings: any[] | null;
      max_expiries_fallback: number | null;
      max_expiries_by_exchange: Record<string, number> | null;
      exists: boolean;
    }>(api.get(`/admin/expiry-overrides/${actor_kind}/${actor_id}`)),
  upsert: (
    actor_kind: "USER" | "BROKER" | "ADMIN",
    actor_id: string,
    body: {
      underlyings: any[] | null;
      max_expiries_fallback: number | null;
      max_expiries_by_exchange?: Record<string, number> | null;
    },
  ) => unwrap<any>(api.put(`/admin/expiry-overrides/${actor_kind}/${actor_id}`, body)),
  remove: (actor_kind: "USER" | "BROKER" | "ADMIN", actor_id: string) =>
    unwrap<any>(api.delete(`/admin/expiry-overrides/${actor_kind}/${actor_id}`)),
  effective: (user_id: string) =>
    unwrap<{ underlyings: any[]; max_expiries: number }>(
      api.get(`/admin/expiry-overrides/effective/${user_id}`),
    ),
};

// White-label branding — admin self-service (logo, brand name, custom
// domain + auto-SSL). Every endpoint 503s when the backend feature
// flag `BRANDING_ENABLED` is off, so the UI gracefully shows
// "feature not enabled" rather than crashing.
export type BrandingPayload = {
  admin_id: string;
  user_code: string;
  brand_name: string | null;
  logo_url: string | null;
  custom_domain: string | null;
  custom_domain_status: string | null;
  // Surfaced by the admin /me endpoint so the UI can render the FAILED
  // panel inline without a second /domain/status call. May be null at
  // any other status.
  custom_domain_last_error: string | null;
};

export type DomainStatus = {
  custom_domain: string | null;
  custom_domain_status: string | null;
  custom_domain_last_error: string | null;
  custom_domain_verified_at: string | null;
};

export type DnsRecordCheck = {
  current: string[];
  ok: boolean;
  error: string | null;
};
export type DnsPreview = {
  expected_ip: string | null;
  apex: DnsRecordCheck;
  www: DnsRecordCheck;
};

/**
 * Web Push subscriptions for the admin app. Used by `notify-sound.ts`
 * → `ensureNotificationPermission()` once permission is granted, so the
 * SW (public/sw.js) receives backend-sent pushes for deposit /
 * withdrawal events even when the PWA is force-stopped or the phone is
 * locked.
 */
export const PushAPI = {
  vapidKey: () => unwrap<{ public_key: string }>(api.get("/admin/push/vapid-key")),
  subscribe: (body: { endpoint: string; keys: { p256dh: string; auth: string }; label?: string }) =>
    unwrap<{ id: string; created: boolean }>(api.post("/admin/push/subscribe", body)),
  unsubscribe: (endpoint: string) =>
    unwrap<{ ok: boolean; found: boolean }>(api.post("/admin/push/unsubscribe", { endpoint })),
};

export const BrandingAPI = {
  me: () => unwrap<BrandingPayload>(api.get("/admin/branding/me")),
  update: (body: {
    brand_name?: string | null;
    custom_domain?: string | null;
    clear_custom_domain?: boolean;
  }) => unwrap<BrandingPayload>(api.put("/admin/branding", body)),
  uploadLogo: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return unwrap<BrandingPayload>(
      api.post("/admin/branding/logo", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      }),
    );
  },
  verifyDomain: () =>
    unwrap<DomainStatus>(api.post("/admin/branding/domain/verify")),
  domainStatus: () =>
    unwrap<DomainStatus>(api.get("/admin/branding/domain/status")),
  // Side-by-side current-vs-expected DNS record preview. The admin UI
  // calls this on Step 2 (and after a Refresh button) so the user sees
  // exactly which records they need to change at the registrar.
  dnsPreview: () =>
    unwrap<DnsPreview>(api.get("/admin/branding/domain/dns-preview")),
  disconnectDomain: () =>
    unwrap<BrandingPayload>(api.post("/admin/branding/domain/disconnect")),
};

// ── Accounts Dashboard ──────────────────────────────────────────

export type AccountEntity = {
  id: string;
  name: string;
  user_code?: string;
  role: string;
  broker_count?: number;
  deposits: number;
  withdrawals: number;
  net_deposit: number;
  realized_pnl: number;
  unrealized_pnl: number;
  net_pnl: number;
  brokerage: number;
  total_trades: number;
  profit_trades: number;
  loss_trades: number;
  win_rate: number;
  volume: number;
  balance: number;
  equity: number;
  open_positions: number;
  settlement_outstanding: number;
  user_count: number;
};

export type AccountsSummary = {
  entities: AccountEntity[];
  grand_total: AccountEntity;
  filter: {
    from_date: string | null;
    to_date: string | null;
    preset: string | null;
    is_lifetime: boolean;
  };
};

export type WeekOption = {
  label: string;
  start: string;
  end: string;
};

export type BrokerTotals = {
  net_client_pnl: string;
  net_client_bkg: string;
  total_of_both: string;
  settlement: string;
  actual_pnl: string;
  sharing_pnl: string;
  sharing_bkg: string;
  total_deposits: string;
  total_withdrawals: string;
  share_pct: string;
  agreement_type: string | null;
  client_count: number;
};

export type EntityUserRow = {
  user_id: string;
  user_code: string;
  username: string;
  owner_kind?: string;
  owner_name?: string;
  net_pnl: string;
  net_bkg: string;
  total_pnl: string;
  settlement: string;
  pnl_minus_settlement: string;
};

export type EntityUsersResponse = {
  items: EntityUserRow[];
  meta: { page: number; page_size: number; total: number; total_pages: number };
};

type DateParams = { from_date?: string; to_date?: string; preset?: string };

export const AccountsAPI = {
  summary: (params?: {
    scope?: string;
    from_date?: string;
    to_date?: string;
    preset?: string;
  }) =>
    unwrap<AccountsSummary>(
      api.get("/admin/accounts/summary", { params }),
    ),

  weeks: (numWeeks?: number) =>
    unwrap<WeekOption[]>(
      api.get("/admin/accounts/weeks", { params: numWeeks ? { num_weeks: numWeeks } : undefined }),
    ),

  // Account 2 — fixed-brokerage report (per direct fixed-brokerage child).
  account2: (params?: { from_date?: string; to_date?: string; preset?: string }) =>
    unwrap<any>(api.get("/admin/accounts/account2", { params })),

  brokerTotals: (entityId: string, params?: DateParams) =>
    unwrap<BrokerTotals>(
      api.get(`/admin/accounts/broker-totals/${entityId}`, { params }),
    ),

  entityUsers: (
    entityId: string,
    params?: DateParams & { page?: number; page_size?: number; search?: string },
  ) =>
    unwrap<EntityUsersResponse>(
      api.get(`/admin/accounts/entity-users/${entityId}`, { params }),
    ),

  exportEntityUsersExcel: async (entityId: string, params?: DateParams): Promise<Blob> => {
    const res = await api.get(`/admin/accounts/entity-users/${entityId}/export/excel`, {
      params,
      responseType: "blob",
    });
    return res.data;
  },

  exportEntityUsersPdf: async (entityId: string, params?: DateParams): Promise<Blob> => {
    const res = await api.get(`/admin/accounts/entity-users/${entityId}/export/pdf`, {
      params,
      responseType: "blob",
    });
    return res.data;
  },

  exportBrokerTotalsExcel: async (entityId: string, params?: DateParams): Promise<Blob> => {
    const res = await api.get(`/admin/accounts/broker-totals/${entityId}/export/excel`, {
      params,
      responseType: "blob",
    });
    return res.data;
  },

  exportBrokerTotalsPdf: async (entityId: string, params?: DateParams): Promise<Blob> => {
    const res = await api.get(`/admin/accounts/broker-totals/${entityId}/export/pdf`, {
      params,
      responseType: "blob",
    });
    return res.data;
  },
};
