"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { AdminAuthAPI, clearTokens, setTokens } from "@/lib/api";
import { STORAGE_KEYS } from "@/lib/constants";
import { portalForRole, rememberPortal, type Portal } from "@/lib/portal";
import { clearDashboardSnapshot } from "@/lib/dashboardSnapshot";
import type { AdminTokenPair, AdminUser } from "@/types";

interface AdminAuthState {
  admin: AdminUser | null;
  hydrated: boolean;
  loading: boolean;
  setHydrated: (v: boolean) => void;
  setSession: (pair: AdminTokenPair) => void;
  login: (
    identifier: string,
    password: string,
    two_fa_code?: string,
    portal?: Portal,
  ) => Promise<AdminTokenPair>;
  logout: () => Promise<void>;
  // Refresh the persisted `admin` object from GET /admin/auth/me. Run on
  // app boot whenever a valid access token exists in localStorage so the
  // sidebar reflects the latest permissions (e.g. super-admin granted a
  // new perm after the user's last login). Errors are swallowed silently
  // — a 401 means the token is invalid and the next API call will
  // trigger the standard refresh / re-login path.
  refreshMe: () => Promise<void>;
}

export const useAdminAuthStore = create<AdminAuthState>()(
  persist(
    (set, get) => ({
      admin: null,
      hydrated: false,
      loading: false,
      setHydrated: (v) => set({ hydrated: v }),
      setSession: (pair) => {
        setTokens(pair.access_token, pair.refresh_token);
        // Every way into a session (login, broker demo signup) remembers which
        // login page this device belongs to, so sign-out lands on the right one.
        rememberPortal(portalForRole(pair.admin?.role));
        set({ admin: pair.admin });
      },
      login: async (identifier, password, two_fa_code, portal) => {
        set({ loading: true });
        try {
          // `portal` is enforced SERVER-side: the broker login refuses admins
          // and the admin login refuses brokers, before any token is issued.
          const pair = await AdminAuthAPI.login({ identifier, password, two_fa_code, portal });
          get().setSession(pair);
          return pair;
        } finally {
          set({ loading: false });
        }
      },
      refreshMe: async () => {
        if (typeof window === "undefined") return;
        const tok = window.localStorage.getItem(STORAGE_KEYS.accessToken);
        if (!tok) return;
        try {
          const me = await AdminAuthAPI.me();
          // /me returns the AdminUserOut shape — drop it straight into
          // the admin slot. last_login_at is already iso-string here.
          if (me) {
            // Brokers signed in before the login split never went through
            // setSession on the new build — remember their portal here too.
            rememberPortal(portalForRole(me.role));
            set({
              admin: {
                id: me.id,
                user_code: me.user_code,
                email: me.email,
                full_name: me.full_name,
                role: me.role,
                last_login_at: me.last_login_at ?? null,
                is_demo: (me as any).is_demo ?? false,
                admin_permissions: me.admin_permissions ?? null,
                broker_permissions: me.broker_permissions ?? null,
                pnl_share_pct: me.pnl_share_pct ?? null,
                assigned_broker_id: (me as any).assigned_broker_id ?? null,
                brand_name: (me as any).brand_name ?? null,
                logo_url: (me as any).logo_url ?? null,
                custom_domain: (me as any).custom_domain ?? null,
                custom_domain_status: (me as any).custom_domain_status ?? null,
              },
            });
          }
        } catch {
          // Silent — interceptor handles 401s, anything else can wait
          // for the next API call to surface.
        }
      },
      logout: async () => {
        // INSTANT local logout — clear tokens + admin state synchronously
        // so the UI redirects right away. The server-side session
        // invalidation is fired-and-forget so a flaky mobile network
        // never makes the "Sign out" button feel frozen (operator
        // complaint: 3-5 s wait on mobile before the page changed).
        const refresh =
          typeof window !== "undefined"
            ? window.localStorage.getItem(STORAGE_KEYS.refreshToken) ?? undefined
            : undefined;
        clearTokens();
        clearDashboardSnapshot();
        // Wipe the persisted React Query cache (key = ADMIN_RQ_CACHE_KEY in
        // app/providers.tsx) so the next admin on this device doesn't see the
        // previous admin's cached user lists / financials restored on load.
        try {
          if (typeof window !== "undefined")
            window.localStorage.removeItem("mp-admin-rq-cache-v1");
        } catch {
          // ignore — best-effort cleanup
        }
        set({ admin: null });
        // Fire-and-forget — server will also reject the refresh token
        // on its next use thanks to standard rotation, so worst-case
        // we end up with one orphaned refresh row that the cleanup
        // job sweeps away.
        if (refresh) {
          AdminAuthAPI.logout(refresh).catch(() => {
            // Swallow — local logout already completed.
          });
        }
      },
    }),
    {
      name: "nb.admin.auth",
      storage: {
        getItem: (k) => {
          if (typeof window === "undefined") return null;
          const raw = window.localStorage.getItem(k);
          return raw ? JSON.parse(raw) : null;
        },
        setItem: (k, v) => {
          if (typeof window !== "undefined") window.localStorage.setItem(k, JSON.stringify(v));
        },
        removeItem: (k) => {
          if (typeof window !== "undefined") window.localStorage.removeItem(k);
        },
      },
      partialize: (s) => ({ admin: s.admin }) as AdminAuthState,
      onRehydrateStorage: () => (s) => s?.setHydrated(true),
    }
  )
);
