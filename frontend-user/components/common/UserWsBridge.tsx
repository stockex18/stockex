"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuthStore } from "@/stores/authStore";
import { STORAGE_KEYS, WS_URL } from "@/lib/constants";
import {
  ensureNotificationPermission,
  playNotifyPing,
  showNativeNotification,
  subscribeForWebPush,
  userNotificationsEnabled,
} from "@/lib/notify-sound";

/** Format an INR amount string ("1500.00" → "🪙1,500.00"). Defensive
 *  against junk values — falls back to the raw string if Number() can't
 *  parse it. */
function fmtINR(raw: string | number | undefined | null): string {
  if (raw === undefined || raw === null || raw === "") return "";
  const n = Number(raw);
  if (!Number.isFinite(n)) return String(raw);
  return `🪙${Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** Translate a wallet-event `reason` + signed amount into a toast title +
 *  body. Returns null when this kind of wallet move shouldn't ping the
 *  user (intra-trade brokerage, margin lock/release, etc.). */
function walletReasonToToast(
  reason: string | undefined,
  amount: string | undefined,
): { kind: "in" | "out"; title: string; body: string } | null {
  const r = String(reason || "").toUpperCase();
  const n = Number(amount ?? 0);
  const credit = Number.isFinite(n) ? n > 0 : true;
  switch (r) {
    case "DEPOSIT":
      return {
        kind: "in",
        title: "✅ Deposit approved",
        body: `${fmtINR(amount)} added to your wallet`,
      };
    case "WITHDRAWAL":
      return {
        kind: "out",
        title: "✅ Withdrawal processed",
        body: `${fmtINR(amount)} sent to your bank`,
      };
    case "ADJUSTMENT":
      // Admin manual Add / Deduct Fund — sign tells us which way.
      return credit
        ? {
            kind: "in",
            title: "💰 Funds added by admin",
            body: `${fmtINR(amount)} credited to your wallet`,
          }
        : {
            kind: "out",
            title: "⚠️ Funds deducted by admin",
            body: `${fmtINR(amount)} debited from your wallet`,
          };
    default:
      // Brokerage / margin / settlement / P&L bookings — silent. The
      // wallet card still refreshes via the query invalidate below;
      // we just don't pop a toast for every trade fill.
      return null;
  }
}

/**
 * Live updates from the backend's per-user pub/sub channels.
 *
 * Opens a single WebSocket to `/ws/user?token=…` (auth via JWT in query
 * because browsers don't allow custom headers on WS handshakes). Whenever
 * the server pushes a `position_update`, `order_update`, `trade_update` or
 * `wallet_update`, we invalidate the matching React Query keys so the
 * affected pages re-render without a manual refresh.
 *
 * Drop this component once near the top of the dashboard tree (e.g. in
 * `app/(dashboard)/layout.tsx`); it renders nothing.
 */
export function UserWsBridge() {
  const qc = useQueryClient();
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    if (!user) return;
    const access =
      typeof window !== "undefined"
        ? window.localStorage.getItem(STORAGE_KEYS.accessToken)
        : null;
    if (!access) return;
    // Request OS notification permission once per session so the wallet
    // toasts below can surface in the Android tray / desktop banner
    // when the PWA is backgrounded. After permission lands, subscribe
    // for Web Push so the backend can wake the phone even when the PWA
    // is force-stopped (the WebSocket above is dead in that case).
    void (async () => {
      const ok = await ensureNotificationPermission();
      if (ok) await subscribeForWebPush();
    })();

    let stopped = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    function connect() {
      if (stopped) return;
      // Read the access token fresh on every connect attempt. The token
      // captured at mount becomes stale after the 15-min expiry — the
      // axios interceptor rotates it in localStorage but the closure
      // here would still carry the old value, causing an endless 403
      // loop (backend rejects the expired JWT before the WS upgrade).
      const freshToken =
        typeof window !== "undefined"
          ? window.localStorage.getItem(STORAGE_KEYS.accessToken)
          : null;
      if (!freshToken) return;
      const url = `${WS_URL.replace(/\/$/, "")}/ws/user?token=${encodeURIComponent(freshToken)}`;
      ws = new WebSocket(url);

      // 25 s heartbeat — mirrors AdminWsBridge. Stops corporate / mobile
      // proxies and Android battery savers from idling out the WS while
      // the PWA sits in the background.
      let pingTimer: ReturnType<typeof setInterval> | null = null;
      ws.onopen = () => {
        attempt = 0;
        if (pingTimer) clearInterval(pingTimer);
        pingTimer = setInterval(() => {
          try {
            if (ws && ws.readyState === WebSocket.OPEN) ws.send("ping");
          } catch {}
        }, 25_000);
      };

      ws.onmessage = (ev) => {
        let msg: any;
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        switch (msg?.type) {
          case "position_update":
            qc.invalidateQueries({ queryKey: ["positions"] });
            qc.invalidateQueries({ queryKey: ["positions", "open"] });
            qc.invalidateQueries({ queryKey: ["wallet"] });
            break;
          case "order_update":
            qc.invalidateQueries({ queryKey: ["orders"] });
            qc.invalidateQueries({ queryKey: ["orders", "recent"] });
            break;
          case "trade_update":
            qc.invalidateQueries({ queryKey: ["trades"] });
            break;
          case "wallet_update":
            qc.invalidateQueries({ queryKey: ["wallet"] });
            break;
          case "wallet":
            // Backend `_publish_wallet_event` uses type="wallet" (not
            // "wallet_update") and ships a {reason, amount, balance_after}
            // payload. Refresh the wallet cache AND show a WhatsApp-style
            // toast + ping when the move is operator-facing — deposit
            // approval, withdrawal payout, admin Add/Deduct Fund.
            qc.invalidateQueries({ queryKey: ["wallet"] });
            qc.invalidateQueries({ queryKey: ["ledger"] });
            {
              const p = (msg as any).payload || {};
              const t = walletReasonToToast(p.reason, p.amount);
              if (t && userNotificationsEnabled()) {
                if (t.kind === "in") {
                  toast.success(t.title, { description: t.body, duration: 7000 });
                } else {
                  toast.warning(t.title, { description: t.body, duration: 7000 });
                }
                playNotifyPing();
                // Unique tag per event so successive admin Add Fund /
                // deposit approvals each show as their own tray row
                // instead of collapsing onto the first one.
                showNativeNotification(t.title, t.body, {
                  tag: `mp-wallet-${Date.now()}`,
                });
              }
            }
            break;
          case "games_balance_changed":
            // Games wallet moved (transfer / stake / payout). Refresh the
            // games wallet + ledger caches only — never touch trades.
            qc.invalidateQueries({ queryKey: ["games", "wallet"] });
            qc.invalidateQueries({ queryKey: ["games", "ledger"] });
            break;
          case "bet_placed":
            qc.invalidateQueries({ queryKey: ["games", "wallet"] });
            qc.invalidateQueries({ queryKey: ["games", "bets"] });
            break;
          case "bet_result": {
            qc.invalidateQueries({ queryKey: ["games", "wallet"] });
            qc.invalidateQueries({ queryKey: ["games", "results"] });
            qc.invalidateQueries({ queryKey: ["games", "bets"] });
            qc.invalidateQueries({ queryKey: ["games", "leaderboard"] });
            const gp = (msg as any).payload || {};
            if (userNotificationsEnabled()) {
              if (gp.won) {
                toast.success("🎉 You won!", {
                  description: `${fmtINR(gp.payout)} credited to your games wallet`,
                  duration: 7000,
                });
                playNotifyPing();
              } else {
                toast.warning("Result declared", {
                  description: "Better luck next round.",
                  duration: 5000,
                });
              }
            }
            break;
          }
          case "stop_out_warning":
          case "stop_out_triggered": {
            // Risk alerts from the backend risk-enforcer. Refresh the
            // notification bell + positions/wallet, and pop a prominent
            // toast + OS notification + ping so the user actually notices
            // (these used to be silently dropped by the WS hub).
            qc.invalidateQueries({ queryKey: ["notifications"] });
            qc.invalidateQueries({ queryKey: ["positions"] });
            qc.invalidateQueries({ queryKey: ["positions", "open"] });
            qc.invalidateQueries({ queryKey: ["wallet"] });
            {
              const rp = (msg as any) || {};
              const title = rp.title || (msg.type === "stop_out_triggered" ? "🛑 Stop-out" : "⚠️ Margin warning");
              const body =
                rp.message ||
                (rp.loss_pct != null ? `Loss at ${Number(rp.loss_pct).toFixed(1)}% of balance` : "");
              if (userNotificationsEnabled()) {
                if (msg.type === "stop_out_triggered") {
                  toast.error(title, { description: body, duration: 12000 });
                } else {
                  toast.warning(title, { description: body, duration: 10000 });
                }
                playNotifyPing();
                showNativeNotification(title, body, { tag: `mp-risk-${Date.now()}` });
              }
            }
            break;
          }
          case "price_alert": {
            // Price alert fired (backend price_alert_service). The phone tray
            // row normally comes from Web Push; it is also shown here with the
            // SAME tag, so with both arriving the tray keeps one row, and with
            // push not set up an open app still reaches the tray.
            qc.invalidateQueries({ queryKey: ["alerts"] });
            qc.invalidateQueries({ queryKey: ["notifications"] });
            const ap = (msg as any) || {};
            const title = ap.title || "🔔 Price alert";
            const body = ap.message || "";
            if (userNotificationsEnabled()) {
              toast.success(title, { description: body, duration: 12000 });
              playNotifyPing();
              showNativeNotification(title, body, {
                tag: ap.alert_id ? `price-alert-${ap.alert_id}` : `price-alert-${Date.now()}`,
                url: "/alerts",
              });
            }
            break;
          }
          case "marketwatch":
            // Cross-tab / cross-device sync: when this user adds /
            // removes an instrument on web, the apk (or another web
            // tab) repaints within ~1 s instead of waiting for the
            // next REST poll. `segment-items` is keyed by segment
            // name, so we don't have the name in scope — broad
            // invalidate the whole prefix.
            qc.invalidateQueries({ queryKey: ["watchlists"] });
            qc.invalidateQueries({ queryKey: ["watchlist-quotes"] });
            qc.invalidateQueries({ queryKey: ["segment-items"] });
            break;
          // hello / heartbeat — ignore
        }
      };

      ws.onclose = () => {
        if (pingTimer) {
          clearInterval(pingTimer);
          pingTimer = null;
        }
        if (stopped) return;
        attempt += 1;
        const delay = Math.min(15_000, 1_000 * 2 ** Math.min(attempt, 4));
        reconnectTimer = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        // Let onclose handle reconnect cadence.
        ws?.close();
      };
    }

    // Reconnect when the PWA comes back from background. Browsers
    // (especially Android) kill idle WS in hidden tabs to save battery;
    // without this nudge the user would have to sit and wait for the
    // exponential-backoff retry to climb back down to a fresh open.
    const onVisible = () => {
      if (document.visibilityState === "visible" && (!ws || ws.readyState >= 2)) {
        if (reconnectTimer) {
          clearTimeout(reconnectTimer);
          reconnectTimer = null;
        }
        attempt = 0;
        connect();
      }
    };
    document.addEventListener("visibilitychange", onVisible);

    connect();

    return () => {
      stopped = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      document.removeEventListener("visibilitychange", onVisible);
      ws?.close();
    };
  }, [qc, user?.id]);

  return null;
}
