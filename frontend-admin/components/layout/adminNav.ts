/**
 * Single source of truth for the admin navigation tree.
 *
 * Both the desktop sidebar (`AdminSidebar`) and the mobile drawer
 * (`AdminMobileDrawer`) consume `useAdminNav()` so the two surfaces
 * NEVER drift out of sync — same items, same labels, same permission
 * gates. Critical: a sub-admin who can't see /backup on desktop must
 * also not see it in the mobile drawer.
 */

import {
  Activity,
  Banknote,
  Calendar,
  ClipboardList,
  Cog,
  DatabaseBackup,
  FileText,
  Layers,
  History,
  Home,
  LineChart,
  ListChecks,
  ListOrdered,
  MessageCircle,
  Plug,
  ShieldCheck,
  Users,
  Crown,
  FlaskConical,
  Wallet,
  Handshake,
  BarChart3,
  Gamepad2,
  Landmark,
  HandCoins,
  Coins,
  GitBranch,
  Receipt,
  Clock,
  Ban,
  type LucideIcon,
} from "lucide-react";
import { canSee, isSuperAdmin, type PermissionKey } from "@/lib/permissions";
import { useAdminAuthStore } from "@/stores/authStore";

export type AdminNavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  perm?: PermissionKey;
  brokerPerm?: PermissionKey;
  brokerLabel?: string;
  superOnly?: boolean;
  adminTierOnly?: boolean;
  hideForSuperAdmin?: boolean;
};

export type AdminNavGroup = { title: string; items: AdminNavItem[] };

export const ADMIN_NAV_GROUPS: AdminNavGroup[] = [
  {
    title: "Overview",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: Home },
      { href: "/accounts-dashboard", label: "Accounts", icon: BarChart3 },
    ],
  },
  {
    title: "My Account",
    items: [
      // Self-serve: any admin-tier user sees their OWN balance + held games
      // commission + settlement history. No perm gate — everyone gets it.
      { href: "/my-wallet", label: "My Wallet", icon: Wallet },
      // The house pool overview — super-admin only.
      { href: "/house", label: "House / Games P&L", icon: Landmark, superOnly: true },
    ],
  },
  {
    title: "Users",
    items: [
      { href: "/users", label: "All users", icon: Users, perm: "users" },
    ],
  },
  {
    title: "Payments",
    items: [
      { href: "/payments", label: "Payments", icon: Banknote, perm: "deposits" },
    ],
  },
  {
    title: "Money",
    items: [
      { href: "/money-transactions", label: "Money Transactions", icon: Wallet, perm: "ledger" },
      { href: "/transaction-history", label: "Transaction History", icon: Receipt, perm: "ledger" },
      { href: "/broker-deposits", label: "Broker Deposits", icon: Handshake, perm: "ledger" },
      // Inter-admin fund flow — all admin-tier users (request up / approve down).
      { href: "/fund-requests", label: "Fund Requests", icon: HandCoins },
    ],
  },
  {
    title: "Risk & Settings",
    items: [
      { href: "/risk-management", label: "Risk Management", icon: ShieldCheck, perm: "risk" },
      { href: "/segment-settings", label: "Segment Settings", icon: Layers, perm: "segment_settings" },
      { href: "/market-control", label: "Market Control", icon: Clock, superOnly: true },
      { href: "/ban-security", label: "Ban Security", icon: Ban, superOnly: true },
      { href: "/option-chain", label: "Expiry Settings", icon: Calendar, perm: "segment_settings" },
    ],
  },
  {
    title: "Trading",
    items: [
      { href: "/orders", label: "Orders", icon: ListOrdered, perm: "trading_view" },
      { href: "/positions", label: "Positions", icon: Activity, perm: "trading_view" },
      { href: "/marketwatch", label: "Market Watch", icon: LineChart, perm: "trading_view" },
      { href: "/instruments", label: "Instruments", icon: ListChecks, superOnly: true },
      { href: "/zerodha", label: "Zerodha Connect", icon: Plug, superOnly: true },
    ],
  },
  {
    title: "Reports",
    items: [
      { href: "/accounts-dashboard", label: "Accounts", icon: BarChart3, perm: "reports" },
      { href: "/reports/tradebook", label: "Tradebook PDF", icon: FileText, perm: "reports" },
    ],
  },
  {
    title: "Management",
    items: [
      { href: "/management/sub-admins", label: "Admin Management", icon: Crown, superOnly: true },
      { href: "/demo", label: "Demo", icon: FlaskConical, superOnly: true },
      // Broker Management — sits right under Admin Management. Visible to the
      // SUPER-ADMIN too (they can create brokers directly in the platform pool),
      // to admins (their own brokers), and to brokers (their sub-brokers).
      {
        href: "/management/brokers",
        label: "Broker Management",
        icon: GitBranch,
        perm: "brokers",
        brokerPerm: "sub_brokers",
        brokerLabel: "Sub-brokers",
      },
      { href: "/management/settlements", label: "Settlements", icon: Wallet, superOnly: true },
      { href: "/management/sa-earnings", label: "SA Earnings", icon: Coins, superOnly: true },
      { href: "/management/sa-ledger", label: "SA Ledger", icon: Receipt, superOnly: true },
      { href: "/management/pnl-sharing", label: "P&L Sharing", icon: Handshake },
      { href: "/patti", label: "Patti Sharing", icon: GitBranch, superOnly: true },
    ],
  },
  {
    title: "Games",
    items: [
      { href: "/games/settings", label: "Game Settings", icon: Gamepad2, superOnly: true },
      { href: "/games/manual-entry", label: "Manual Game Entry", icon: FlaskConical, superOnly: true },
      { href: "/games/withdrawals", label: "Games Withdrawals", icon: Wallet, superOnly: true },
      { href: "/games/earnings", label: "Games Earnings", icon: Handshake, superOnly: true },
      { href: "/games/monitor", label: "Live Bets", icon: Activity, superOnly: true },
    ],
  },
  {
    title: "System",
    items: [
      { href: "/settings/platform", label: "Platform settings", icon: Cog },
      { href: "/settings/branding", label: "Branding", icon: Cog, adminTierOnly: true },
      { href: "/holidays", label: "Holiday calendar", icon: Calendar, superOnly: true },
      { href: "/backup", label: "Backup & EOD", icon: DatabaseBackup, superOnly: true },
      { href: "/support", label: "Support", icon: MessageCircle },
      { href: "/audit", label: "Audit logs", icon: History },
      { href: "/admin-actions", label: "Admin Actions", icon: History },
    ],
  },
];

/** Pure helper: filter nav for a given admin (role + permissions). */
export function filterAdminNav(
  admin: ReturnType<typeof useAdminAuthStore.getState>["admin"]
): AdminNavGroup[] {
  return ADMIN_NAV_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((it) => {
      if (it.hideForSuperAdmin && isSuperAdmin(admin)) return false;
      if (it.adminTierOnly) return admin?.role === "ADMIN";
      if (it.superOnly) return isSuperAdmin(admin);
      if (it.perm) {
        const effective =
          admin?.role === "BROKER" && it.brokerPerm ? it.brokerPerm : it.perm;
        return canSee(admin, effective);
      }
      return true;
    }),
  })).filter((g) => g.items.length > 0);
}

/** Hook variant — bound to the auth store. */
export function useAdminNav(): AdminNavGroup[] {
  const admin = useAdminAuthStore((s) => s.admin);
  return filterAdminNav(admin);
}

/** Resolve label for an item given the current admin role. */
export function resolveNavLabel(
  it: AdminNavItem,
  admin: ReturnType<typeof useAdminAuthStore.getState>["admin"]
): string {
  return admin?.role === "BROKER" && it.brokerLabel ? it.brokerLabel : it.label;
}
