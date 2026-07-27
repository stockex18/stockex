"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Plus,
  ShieldOff,
  ShieldCheck,
  Pencil,
  LogIn,
  MoreVertical,
  Eye,
  EyeOff,
  KeyRound,
  Layers,
  Trash2,
  Percent,
  DollarSign,
  Gift,
  Ban,
} from "lucide-react";
import { SubAdminSegmentDialog } from "@/components/admin/netting/SubAdminSegmentDialog";

import { BrokerMgmtAPI, ManagementAPI, SettingsAPI, setTokens } from "@/lib/api";
import { useAdminAuthStore } from "@/stores/authStore";
import { STORAGE_KEYS } from "@/lib/constants";
import type { AdminUser, BrokerPermissions, PermissionLevel } from "@/types";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { PageHeader } from "@/components/common/PageHeader";
import { DataTable, type Column } from "@/components/common/DataTable";
import type { AdminPermissions } from "@/types";

const PERMISSION_LABELS: Array<{ key: keyof AdminPermissions; label: string }> = [
  { key: "users", label: "Users" },
  { key: "kyc", label: "KYC review" },
  { key: "deposits", label: "Deposits" },
  { key: "withdrawals", label: "Withdrawals" },
  { key: "banks", label: "Bank accounts" },
  { key: "segment_settings", label: "Segment settings" },
  { key: "risk", label: "Risk management" },
  { key: "netting", label: "Netting overrides" },
  { key: "trading_view", label: "Trading view" },
  { key: "ledger", label: "Ledger" },
  { key: "reports", label: "Reports" },
  { key: "brokerage", label: "Brokerage" },
  { key: "brokers", label: "Brokers (sub-admin can mint brokers)" },
];

const ALL_OFF: AdminPermissions = {
  users: false,
  kyc: false,
  deposits: false,
  withdrawals: false,
  banks: false,
  segment_settings: false,
  risk: false,
  netting: false,
  trading_view: false,
  ledger: false,
  reports: false,
  brokers: false,
  brokerage: false,
};

// New admins start with EVERY permission ON by default (operator can uncheck
// what they don't want) — a fresh admin is typically given full access.
const ALL_ON: AdminPermissions = {
  users: true,
  kyc: true,
  deposits: true,
  withdrawals: true,
  banks: true,
  segment_settings: true,
  risk: true,
  netting: true,
  trading_view: true,
  ledger: true,
  reports: true,
  brokers: true,
  brokerage: true,
};

export default function SubAdminsPage() {
  const qc = useQueryClient();
  const router = useRouter();
  const admin = useAdminAuthStore((s) => s.admin);
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  const [loginAsId, setLoginAsId] = useState<string | null>(null);
  const [resetPwTarget, setResetPwTarget] = useState<{ id: string; label: string } | null>(null);
  const [newPw, setNewPw] = useState("");
  // Eye-toggle for the reset-password dialog input, matching the
  // create-sub-admin form's password field UX so super-admins get a
  // consistent experience across both flows.
  const [showNewPw, setShowNewPw] = useState(false);
  const [createBrokerForAdmin, setCreateBrokerForAdmin] = useState<{id: string; name: string} | null>(null);
  const [segSettingsFor, setSegSettingsFor] = useState<{ id: string; name: string } | null>(null);

  // Same-origin localStorage means we can't keep both super-admin and sub-admin
  // sessions live in different tabs (both live under localhost:3001). So
  // "Login as" swaps the active session in this tab; we stash the prior
  // super-admin tokens under a dedicated key so a future "switch back" UI
  // can recover them. Until then the super-admin can just log out + log
  // back in to return to their own session. No confirm popup — super-admin
  // explicitly clicked the menu item, that's the confirmation.
  async function loginAs(sub: any) {
    setLoginAsId(sub.id);
    try {
      const r = await ManagementAPI.impersonateSubAdmin(sub.id);
      try {
        const prevAccess = window.localStorage.getItem(STORAGE_KEYS.accessToken);
        const prevRefresh = window.localStorage.getItem(STORAGE_KEYS.refreshToken);
        const prevAdmin = window.localStorage.getItem("nb.admin.auth");
        if (prevAccess && prevRefresh) {
          window.localStorage.setItem(
            "nb.admin.impersonatorSession",
            JSON.stringify({
              access: prevAccess,
              refresh: prevRefresh,
              admin: prevAdmin,
              ts: Date.now(),
            }),
          );
        }
      } catch {
        /* ignore */
      }
      setTokens(r.access_token, r.refresh_token);
      const next: AdminUser = {
        id: r.admin.id,
        user_code: r.admin.user_code,
        email: r.admin.email,
        full_name: r.admin.full_name,
        role: r.admin.role,
        last_login_at: null,
        admin_permissions: r.admin.admin_permissions ?? null,
        pnl_share_pct: r.admin.pnl_share_pct ?? null,
      };
      useAdminAuthStore.setState({ admin: next });
      window.localStorage.setItem(
        "nb.admin.auth",
        JSON.stringify({ state: { admin: next }, version: 0 }),
      );
      qc.clear();
      toast.success(`Logged in as ${r.admin.user_code}`);
      router.push("/dashboard");
    } catch (e: any) {
      toast.error(e?.response?.data?.error?.message || e.message || "Failed");
    } finally {
      setLoginAsId(null);
    }
  }

  const { data, isFetching } = useQuery({
    queryKey: ["admin", "sub-admins", q],
    queryFn: () => ManagementAPI.listSubAdmins({ q: q || undefined, page: 1, page_size: 100 }),
    enabled: admin?.role === "SUPER_ADMIN",
  });

  // ── Admin fund-cap (float) kill-switch — super-admin only, live toggle ──
  const { data: floatCfg } = useQuery({
    queryKey: ["admin", "admin-float"],
    queryFn: () => SettingsAPI.adminFloatEnabled(),
    enabled: admin?.role === "SUPER_ADMIN",
  });
  const floatMut = useMutation({
    mutationFn: (enabled: boolean) => SettingsAPI.setAdminFloatEnabled(enabled),
    onSuccess: (r) => {
      toast.success(`Fund-cap ${r.enabled ? "ON" : "OFF"}`);
      qc.invalidateQueries({ queryKey: ["admin", "admin-float"] });
    },
    onError: (e: any) => toast.error(e?.response?.data?.error?.message || e.message || "Failed"),
  });
  const floatOn = !!floatCfg?.enabled;

  // ── Admin-book model (per-trade SA↔admin real-money) kill-switch ──
  const { data: adminBookCfg } = useQuery({
    queryKey: ["admin", "admin-book"],
    queryFn: () => SettingsAPI.adminBookEnabled(),
    enabled: admin?.role === "SUPER_ADMIN",
  });
  const adminBookMut = useMutation({
    mutationFn: (enabled: boolean) => SettingsAPI.setAdminBookEnabled(enabled),
    onSuccess: (r) => {
      toast.success(`Admin-book ${r.enabled ? "ON — per-trade SA share LIVE" : "OFF"}`);
      qc.invalidateQueries({ queryKey: ["admin", "admin-book"] });
    },
    onError: (e: any) => toast.error(e?.response?.data?.error?.message || e.message || "Failed"),
  });
  const adminBookOn = !!adminBookCfg?.enabled;

  const blockMut = useMutation({
    mutationFn: (id: string) => ManagementAPI.blockSubAdmin(id),
    onSuccess: () => {
      toast.success("Sub-admin blocked");
      qc.invalidateQueries({ queryKey: ["admin", "sub-admins"] });
    },
    onError: (e: any) => toast.error(e.message),
  });
  const unblockMut = useMutation({
    mutationFn: (id: string) => ManagementAPI.unblockSubAdmin(id),
    onSuccess: () => {
      toast.success("Sub-admin unblocked");
      qc.invalidateQueries({ queryKey: ["admin", "sub-admins"] });
    },
    onError: (e: any) => toast.error(e.message),
  });
  const expiryEditMut = useMutation({
    mutationFn: ({ id, allowed }: { id: string; allowed: boolean }) =>
      ManagementAPI.setExpiryEditAllowed(id, allowed),
    onSuccess: (_d, v) => {
      toast.success(v.allowed ? "Expiry edit allowed for this admin" : "Expiry edit locked");
      qc.invalidateQueries({ queryKey: ["admin", "sub-admins"] });
    },
    onError: (e: any) => toast.error(e.message),
  });
  const tradingReferralMut = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      ManagementAPI.setTradingReferralEnabled(id, enabled),
    onSuccess: (_d, v) => {
      toast.success(
        v.enabled
          ? "Trading referral ON for this admin's clients"
          : "Trading referral OFF — no client under this admin earns it"
      );
      qc.invalidateQueries({ queryKey: ["admin", "sub-admins"] });
    },
    onError: (e: any) => toast.error(e.message),
  });
  const resetPwMut = useMutation({
    mutationFn: ({ id, pw }: { id: string; pw: string }) =>
      ManagementAPI.resetSubAdminPassword(id, pw),
    onSuccess: () => {
      toast.success("Password reset");
      setResetPwTarget(null);
      setNewPw("");
      setShowNewPw(false);
    },
    onError: (e: any) =>
      toast.error(e?.response?.data?.detail ?? e?.message ?? "Reset failed"),
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => ManagementAPI.deleteSubAdmin(id),
    onSuccess: () => {
      toast.success("Sub-admin deleted");
      qc.invalidateQueries({ queryKey: ["admin", "sub-admins"] });
    },
    onError: (e: any) =>
      toast.error(e?.response?.data?.detail ?? e?.message ?? "Delete failed"),
  });

  if (admin?.role !== "SUPER_ADMIN") {
    return (
      <div className="rounded-md border border-border bg-card p-6 text-sm text-muted-foreground">
        Only the super admin can manage sub-admins.
      </div>
    );
  }

  const cols: Column<any>[] = [
    { key: "user_code", header: "Code" },
    { key: "full_name", header: "Name" },
    { key: "email", header: "Email" },
    { key: "mobile", header: "Mobile" },
    {
      key: "pnl_share_pct",
      header: "PNL share %",
      render: (r) => `${r.pnl_share_pct ?? "0"}%`,
    },
    {
      key: "brokerage_share_pct",
      header: "Brokerage %",
      // Fixed-brokerage admins take a per-segment fixed rate (set in Segment
      // settings → Brokerage), NOT a % — so show "Fixed" instead of wrongly
      // inheriting the PNL share %. Otherwise: the admin's own brokerage %, or
      // fall back to the PNL share % (legacy admins with no split).
      render: (r) =>
        r.is_fixed_brokerage
          ? "Fixed"
          : r.brokerage_share_pct != null
            ? `${r.brokerage_share_pct}%`
            : `${r.pnl_share_pct ?? "0"}%`,
    },
    { key: "user_count", header: "Users", render: (r) => r.user_count ?? 0 },
    { key: "broker_count", header: "Brokers", render: (r) => r.broker_count ?? 0 },
    {
      key: "status",
      header: "Status",
      render: (r) => (
        <span
          className={
            r.status === "ACTIVE"
              ? "rounded bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-500"
              : "rounded bg-red-500/10 px-2 py-0.5 text-xs text-red-500"
          }
        >
          {r.status}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (r) => (
        // Stop row-click navigation when the menu trigger is clicked —
        // otherwise tapping the dots would also open the detail page.
        <div
          className="flex justify-end"
          onClick={(e) => e.stopPropagation()}
        >
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Open actions"
                disabled={loginAsId === r.id}
              >
                <MoreVertical className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setCreateBrokerForAdmin({ id: r.id, name: r.full_name || r.user_code })}>
                <Plus className="size-4 text-primary" />
                Create Broker
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => loginAs(r)}>
                <LogIn className="size-4 text-primary" />
                Login
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() => router.push(`/management/sub-admins/${r.id}`)}
              >
                <Eye className="size-4" />
                View admin profile
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setEditing(r)}>
                <Pencil className="size-4" />
                Edit permissions
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setSegSettingsFor({ id: r.id, name: r.full_name || r.user_code })}>
                <Layers className="size-4 text-primary" />
                Segment settings
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() =>
                  expiryEditMut.mutate({ id: r.id, allowed: !r.can_edit_expiry_settings })
                }
              >
                {r.can_edit_expiry_settings ? (
                  <ShieldCheck className="size-4 text-emerald-500" />
                ) : (
                  <ShieldOff className="size-4 text-muted-foreground" />
                )}
                Expiry edit · {r.can_edit_expiry_settings ? "ON" : "OFF"}
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() =>
                  tradingReferralMut.mutate({
                    id: r.id,
                    enabled: r.trading_referral_enabled === false,
                  })
                }
              >
                {r.trading_referral_enabled === false ? (
                  <Gift className="size-4 text-muted-foreground" />
                ) : (
                  <Gift className="size-4 text-emerald-500" />
                )}
                Trading referral · {r.trading_referral_enabled === false ? "OFF" : "ON"}
              </DropdownMenuItem>
              {r.status === "ACTIVE" ? (
                <DropdownMenuItem onSelect={() => blockMut.mutate(r.id)}>
                  <ShieldOff className="size-4 text-red-500" />
                  Block
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem onSelect={() => unblockMut.mutate(r.id)}>
                  <ShieldCheck className="size-4 text-emerald-500" />
                  Unblock
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                onSelect={() =>
                  setResetPwTarget({
                    id: r.id,
                    label: r.full_name || r.user_code || "admin",
                  })
                }
              >
                <KeyRound className="size-4" />
                Reset Password
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() => {
                  if (
                    confirm(
                      `Permanently delete ${r.user_code}? Their users will be reassigned to the platform pool.`,
                    )
                  ) {
                    deleteMut.mutate(r.id);
                  }
                }}
                className="text-red-500"
              >
                <Trash2 className="size-4 text-red-500" />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Sub-admins"
        actions={
          <Button onClick={() => setCreating(true)} className="w-full sm:w-auto">
            <Plus className="size-4" /> New sub-admin
          </Button>
        }
      />

      {/* Admin fund-cap (float) — global ON/OFF, super-admin only. When ON,
          an admin can only fund users up to their SA-given float. Lives here
          so the super-admin can flip it right on the admin page (live, no
          restart). */}
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">Admin fund-cap (float)</span>
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                floatOn ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"
              }`}
            >
              {floatOn ? "ON" : "OFF"}
            </span>
          </div>
          <p className="max-w-2xl text-xs text-muted-foreground">
            When ON, an admin / broker can only deposit / add funds to their users up to the float
            the super-admin gave them; withdrawals return to that float. Super-admin stays unlimited.{" "}
            <span className="font-medium text-amber-500">
              Turn ON only after each admin has a float (set an Opening fund at create, or fund them
              via Fund Requests) — else they can’t fund anyone.
            </span>
          </p>
        </div>
        <Button
          variant={floatOn ? "destructive" : "default"}
          onClick={() => floatMut.mutate(!floatOn)}
          loading={floatMut.isPending}
          className="w-full sm:w-auto"
        >
          {floatOn ? "Turn OFF" : "Turn ON"}
        </Button>
      </div>

      {/* Admin-book model (per-trade SA↔admin) — global ON/OFF, super-admin only.
          When ON, every closing trade books the house result + brokerage to the
          owning admin and the SA skims its PnL% + brokerage%. Real money moves
          per trade — see it in Management → SA Earnings. */}
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">Per-trade admin-book (SA↔admin)</span>
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                adminBookOn ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"
              }`}
            >
              {adminBookOn ? "ON" : "OFF"}
            </span>
          </div>
          <p className="max-w-2xl text-xs text-muted-foreground">
            When ON, every closing trade books the user&apos;s house result (+ brokerage) to the
            owning admin&apos;s wallet, then the super-admin skims its PnL share % + brokerage share %
            — <span className="font-medium">real money moves per trade</span>. See the split per
            admin / user / trade in <span className="font-medium">SA Earnings</span>.{" "}
            <span className="font-medium text-amber-500">
              This changes live money movement — turn ON only when you&apos;re ready.
            </span>
          </p>
        </div>
        <Button
          variant={adminBookOn ? "destructive" : "default"}
          onClick={() => adminBookMut.mutate(!adminBookOn)}
          loading={adminBookMut.isPending}
          className="w-full sm:w-auto"
        >
          {adminBookOn ? "Turn OFF" : "Turn ON"}
        </Button>
      </div>

      {/* Search box — full-width on mobile so the input is actually
          usable on a phone (was cramped inside the PageHeader actions
          row at 224 px). Sits above the data, never gets clipped. */}
      <Input
        placeholder="Search sub-admins…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="h-10 w-full"
      />

      {/* Desktop table — hidden under md. */}
      <div className="hidden md:block">
        <DataTable
          columns={cols}
          rows={data?.items}
          keyExtractor={(r) => r.id}
          loading={isFetching && !data}
          onRowClick={(r) => router.push(`/management/sub-admins/${r.id}`)}
        />
      </div>

      {/* Mobile card list — shown under md. Same data, same actions,
          but no horizontal scroll and no clipped columns. */}
      <div className="md:hidden">
        {isFetching && !data ? (
          <div className="rounded-lg border border-border bg-card p-6 text-center text-sm text-muted-foreground">
            Loading…
          </div>
        ) : (data?.items ?? []).length === 0 ? (
          <div className="rounded-lg border border-border bg-card p-6 text-center text-sm text-muted-foreground">
            No sub-admins found.
          </div>
        ) : (
          <ul className="space-y-2.5">
            {(data?.items ?? []).map((r: any) => (
              <SubAdminMobileCard
                key={r.id}
                row={r}
                onOpen={() => router.push(`/management/sub-admins/${r.id}`)}
                onCreateBroker={() =>
                  setCreateBrokerForAdmin({ id: r.id, name: r.full_name || r.user_code })
                }
                onLoginAs={() => loginAs(r)}
                onEdit={() => setEditing(r)}
                onBlock={() => blockMut.mutate(r.id)}
                onUnblock={() => unblockMut.mutate(r.id)}
                onResetPw={() =>
                  setResetPwTarget({
                    id: r.id,
                    label: r.full_name || r.user_code || "admin",
                  })
                }
                onDelete={() => {
                  if (
                    confirm(
                      `Permanently delete ${r.user_code}? Their users will be reassigned to the platform pool.`,
                    )
                  ) {
                    deleteMut.mutate(r.id);
                  }
                }}
                loginAsBusy={loginAsId === r.id}
              />
            ))}
          </ul>
        )}
      </div>

      <CreateSubAdminDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(created) => {
          qc.invalidateQueries({ queryKey: ["admin", "sub-admins"] });
          // Open this admin's segment settings right after create so the SA
          // can set them at "create time" (the admin already inherited the SA
          // ceiling as a baseline; here the SA tightens/customizes per admin).
          if (created?.id) setSegSettingsFor({ id: created.id, name: created.full_name || created.user_code });
        }}
      />
      {editing && (
        <EditSubAdminDialog
          subAdmin={editing}
          onClose={() => setEditing(null)}
          onSaved={() => qc.invalidateQueries({ queryKey: ["admin", "sub-admins"] })}
        />
      )}

      <Dialog
        open={!!resetPwTarget}
        onOpenChange={(o) => {
          if (!o) {
            setResetPwTarget(null);
            setNewPw("");
            setShowNewPw(false);
          }
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Reset password</DialogTitle>
          </DialogHeader>
          {resetPwTarget && (
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">
                You're resetting the password for{" "}
                <span className="font-semibold text-foreground">
                  {resetPwTarget.label}
                </span>
                . They'll be able to sign in immediately with the new value.
              </p>
              <div className="space-y-1.5">
                <Label>New password (min 8 chars)</Label>
                <div className="relative">
                  <Input
                    type={showNewPw ? "text" : "password"}
                    value={newPw}
                    onChange={(e) => setNewPw(e.target.value)}
                    autoFocus
                    className="pr-9"
                  />
                  <button
                    type="button"
                    onClick={() => setShowNewPw((v) => !v)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    aria-label={showNewPw ? "Hide password" : "Show password"}
                  >
                    {showNewPw ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                  </button>
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setResetPwTarget(null);
                setNewPw("");
                setShowNewPw(false);
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (newPw.length < 8) {
                  toast.error("Password must be at least 8 characters");
                  return;
                }
                if (resetPwTarget) {
                  resetPwMut.mutate({ id: resetPwTarget.id, pw: newPw });
                }
              }}
              disabled={resetPwMut.isPending}
            >
              {resetPwMut.isPending ? "Resetting…" : "Reset password"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <CreateBrokerForAdminDialog
        open={!!createBrokerForAdmin}
        admin={createBrokerForAdmin}
        onClose={() => setCreateBrokerForAdmin(null)}
      />

      <SubAdminSegmentDialog
        open={!!segSettingsFor}
        onOpenChange={(v) => !v && setSegSettingsFor(null)}
        adminId={segSettingsFor?.id ?? null}
        adminName={segSettingsFor?.name}
      />
    </div>
  );
}

// ── Mobile card row ───────────────────────────────────────────────────
/**
 * One sub-admin rendered as a phone-friendly card. Replaces the
 * horizontally-clipping desktop table on screens narrower than `md`.
 * Identity header on top + a 2×2 metric grid + a kebab actions menu.
 */
function SubAdminMobileCard({
  row,
  onOpen,
  onCreateBroker,
  onLoginAs,
  onEdit,
  onBlock,
  onUnblock,
  onResetPw,
  onDelete,
  loginAsBusy,
}: {
  row: any;
  onOpen: () => void;
  onCreateBroker: () => void;
  onLoginAs: () => void;
  onEdit: () => void;
  onBlock: () => void;
  onUnblock: () => void;
  onResetPw: () => void;
  onDelete: () => void;
  loginAsBusy: boolean;
}) {
  const initials = (row.full_name || row.user_code || "?")
    .split(/\s+/)
    .map((s: string) => s[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
  const isActive = row.status === "ACTIVE";
  return (
    <li
      onClick={onOpen}
      className="cursor-pointer rounded-lg border border-border bg-card p-3 transition-colors hover:bg-accent/30 active:bg-accent/40"
    >
      {/* Identity header — avatar circle + name/code + status + kebab */}
      <div className="flex items-start gap-3">
        <div className="grid size-10 shrink-0 place-items-center rounded-full bg-primary/15 text-xs font-bold text-primary">
          {initials}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">
            {row.full_name || row.user_code || "—"}
          </div>
          <div className="truncate font-mono text-[10px] text-muted-foreground">
            {row.user_code || "—"}
          </div>
        </div>
        <span
          className={
            "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider " +
            (isActive
              ? "bg-emerald-500/10 text-emerald-500 ring-1 ring-inset ring-emerald-500/30"
              : "bg-red-500/10 text-red-500 ring-1 ring-inset ring-red-500/30")
          }
        >
          {row.status || "—"}
        </span>
        <div onClick={(e) => e.stopPropagation()}>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Open actions"
                disabled={loginAsBusy}
                className="-mr-1 size-8"
              >
                <MoreVertical className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={onCreateBroker}>
                <Plus className="size-4 text-primary" />
                Create Broker
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={onLoginAs}>
                <LogIn className="size-4 text-primary" />
                Login
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={onOpen}>
                <Eye className="size-4" />
                View admin profile
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={onEdit}>
                <Pencil className="size-4" />
                Edit permissions
              </DropdownMenuItem>
              {isActive ? (
                <DropdownMenuItem onSelect={onBlock}>
                  <ShieldOff className="size-4 text-red-500" />
                  Block
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem onSelect={onUnblock}>
                  <ShieldCheck className="size-4 text-emerald-500" />
                  Unblock
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onSelect={onResetPw}>
                <KeyRound className="size-4" />
                Reset Password
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={onDelete} className="text-red-500">
                <Trash2 className="size-4 text-red-500" />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Contact rows — email + mobile, each on its own line with a
          subtle icon column so the eye finds them fast. */}
      <div className="mt-3 space-y-1 text-xs">
        <div className="flex items-center gap-2 text-muted-foreground">
          <span className="w-12 text-[10px] uppercase tracking-wider">Email</span>
          <span className="truncate text-foreground">{row.email || "—"}</span>
        </div>
        <div className="flex items-center gap-2 text-muted-foreground">
          <span className="w-12 text-[10px] uppercase tracking-wider">Mobile</span>
          <span className="truncate text-foreground">{row.mobile || "—"}</span>
        </div>
      </div>

      {/* Metric tiles — Users (clients) + Brokers + PNL share % in a
          3-col grid. Users and Brokers are kept separate so the count
          isn't inflated by broker/sub-broker login accounts. */}
      <div className="mt-3 grid grid-cols-3 gap-2 rounded-md bg-muted/30 p-2">
        <div className="text-center">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Users
          </div>
          <div className="mt-0.5 text-sm font-semibold tabular-nums">
            {row.user_count ?? 0}
          </div>
        </div>
        <div className="text-center">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Brokers
          </div>
          <div className="mt-0.5 text-sm font-semibold tabular-nums">
            {row.broker_count ?? 0}
          </div>
        </div>
        <div className="text-center">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            PNL Share
          </div>
          <div className="mt-0.5 text-sm font-semibold tabular-nums">
            {row.pnl_share_pct ?? "0"}%
          </div>
        </div>
      </div>
    </li>
  );
}


// ── Create dialog ─────────────────────────────────────────────────────
function CreateSubAdminDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreated: (created?: any) => void;
}) {
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    mobile: "",
    password: "",
    confirm_password: "",
    pnl_share_pct: "0",
    brokerage_share_pct: "",
    opening_fund: "0",
    is_fixed_brokerage: false,
    fixed_brokerage_unit: "per_crore",
    fixed_brokerage_rate: "",
  });
  const [perms, setPerms] = useState<AdminPermissions>({ ...ALL_ON });
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  // Step 1 is a TYPE CHOOSER: pick "normal" (% PNL + % brokerage), "fixed"
  // (Account 2 per-segment fixed brokerage), or "nobrokerage" (% PNL only, the
  // super-admin takes ZERO brokerage from this admin). null = still on chooser.
  const [mode, setMode] = useState<"normal" | "fixed" | "nobrokerage" | null>(null);
  // Reset to the chooser + all-perms-on every time the dialog is (re)opened.
  useEffect(() => {
    if (open) {
      setMode(null);
      setPerms({ ...ALL_ON });
    }
  }, [open]);
  const isFixed = mode === "fixed";
  const isNoBrokerage = mode === "nobrokerage";
  // Both fixed AND no-brokerage hide the "Brokerage share %" input — fixed uses
  // the per-segment rate, no-brokerage forces it to 0.
  const hideBrokerageShare = isFixed || isNoBrokerage;

  async function submit() {
    if (form.password.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }
    if (form.password !== form.confirm_password) {
      toast.error("Passwords do not match");
      return;
    }
    setLoading(true);
    try {
      const created = await ManagementAPI.createSubAdmin({
        full_name: form.full_name,
        email: form.email,
        mobile: form.mobile,
        password: form.password,
        permissions: perms as unknown as Record<string, boolean>,
        pnl_share_pct: form.pnl_share_pct,
        // No-brokerage admin → force brokerage share to an explicit 0 (super-admin
        // takes NO brokerage cut). Fixed → per-segment rate handles it later
        // (send undefined). Normal → the typed %, or undefined when blank.
        brokerage_share_pct: isNoBrokerage
          ? "0"
          : isFixed
            ? undefined
            : (form.brokerage_share_pct ?? "").trim() === ""
              ? undefined
              : form.brokerage_share_pct,
        opening_fund: Number(form.opening_fund) || 0,
        // Type chosen on the chooser step; the per-segment fixed rate is set
        // (and frozen) later in the admin's Segment settings → Brokerage.
        is_fixed_brokerage: isFixed,
      });
      toast.success("Sub-admin created");
      onOpenChange(false);
      setForm({ full_name: "", email: "", mobile: "", password: "", confirm_password: "", pnl_share_pct: "0", brokerage_share_pct: "", opening_fund: "0", is_fixed_brokerage: false, fixed_brokerage_unit: "per_crore", fixed_brokerage_rate: "" });
      setPerms({ ...ALL_OFF });
      onCreated(created);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {mode === null
              ? "New admin — choose type"
              : isFixed
                ? "New fixed-brokerage admin"
                : isNoBrokerage
                  ? "New no-brokerage admin"
                  : "New PNL (%) admin"}
          </DialogTitle>
        </DialogHeader>

        {/* ── Step 1: TYPE CHOOSER ─────────────────────────────────── */}
        {mode === null ? (
          <div className="grid gap-3 sm:grid-cols-3">
            <button
              type="button"
              onClick={() => setMode("normal")}
              className="group flex flex-col items-start gap-2 rounded-xl border-2 border-border bg-card/40 p-4 text-left transition hover:border-primary hover:bg-primary/5"
            >
              <div className="flex size-9 items-center justify-center rounded-lg bg-primary/15 text-primary">
                <Percent className="size-5" />
              </div>
              <div className="text-base font-semibold">Normal PNL admin</div>
              <p className="text-[12px] leading-relaxed text-muted-foreground">
                You take a <b>% share</b> of this admin&apos;s PNL and brokerage. The classic
                sharing flow — set PNL share % and Brokerage share %.
              </p>
            </button>
            <button
              type="button"
              onClick={() => setMode("fixed")}
              className="group flex flex-col items-start gap-2 rounded-xl border-2 border-border bg-card/40 p-4 text-left transition hover:border-primary hover:bg-primary/5"
            >
              <div className="flex size-9 items-center justify-center rounded-lg bg-primary/15 text-primary">
                <DollarSign className="size-5" />
              </div>
              <div className="text-base font-semibold">Fixed-brokerage admin (Account 2)</div>
              <p className="text-[12px] leading-relaxed text-muted-foreground">
                You take a <b>FIXED per-segment brokerage</b> from this admin&apos;s volume
                (NSE/MCX/crypto/forex — each its own per-lot / per-crore rate), regardless of
                what they charge their users. Shows up in Account 2.
              </p>
            </button>
            <button
              type="button"
              onClick={() => setMode("nobrokerage")}
              className="group flex flex-col items-start gap-2 rounded-xl border-2 border-border bg-card/40 p-4 text-left transition hover:border-primary hover:bg-primary/5"
            >
              <div className="flex size-9 items-center justify-center rounded-lg bg-primary/15 text-primary">
                <Ban className="size-5" />
              </div>
              <div className="text-base font-semibold">No-brokerage admin</div>
              <p className="text-[12px] leading-relaxed text-muted-foreground">
                You take a <b>% share of PNL only</b> — <b>NO brokerage</b> cut from this admin
                (brokerage share fixed at 0%). Set just the PNL share %.
              </p>
            </button>
          </div>
        ) : (
        <>
        {/* Chosen-type banner + change-type back link */}
        <div className="mb-3 flex items-center justify-between rounded-lg border border-primary/40 bg-primary/5 px-3 py-2">
          <div className="flex items-center gap-2 text-sm font-medium">
            {isFixed ? (
              <DollarSign className="size-4 text-primary" />
            ) : isNoBrokerage ? (
              <Ban className="size-4 text-primary" />
            ) : (
              <Percent className="size-4 text-primary" />
            )}
            {isFixed
              ? "Fixed-brokerage admin (Account 2)"
              : isNoBrokerage
                ? "No-brokerage admin (PNL % only)"
                : "Normal PNL (%) admin"}
          </div>
          <button
            type="button"
            onClick={() => setMode(null)}
            className="text-xs font-medium text-primary hover:underline"
          >
            ← Change type
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label>Full name</Label>
            <Input value={form.full_name} onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} />
          </div>
          <div className="space-y-1.5">
            <Label>Email</Label>
            <Input type="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
          </div>
          <div className="space-y-1.5">
            <Label>Mobile (10-digit)</Label>
            <Input value={form.mobile} onChange={(e) => setForm((f) => ({ ...f, mobile: e.target.value }))} />
          </div>
          <div className="space-y-1.5">
            <Label>Password</Label>
            <div className="relative">
              <Input
                type={showPassword ? "text" : "password"}
                className="pr-10"
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
              />
              <button
                type="button"
                onClick={() => setShowPassword((s) => !s)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                className="absolute inset-y-0 right-0 grid w-10 place-items-center text-muted-foreground hover:text-foreground"
              >
                {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Confirm password</Label>
            <Input
              type={showPassword ? "text" : "password"}
              value={form.confirm_password}
              onChange={(e) => setForm((f) => ({ ...f, confirm_password: e.target.value }))}
            />
            {form.confirm_password.length > 0 && form.password !== form.confirm_password ? (
              <p className="text-xs text-destructive">Passwords do not match</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label>PNL share %</Label>
            <Input
              type="number"
              min={0}
              max={100}
              step="0.01"
              value={form.pnl_share_pct}
              onChange={(e) => setForm((f) => ({ ...f, pnl_share_pct: e.target.value }))}
            />
          </div>
          {/* Brokerage share % only applies to the % (normal) flow — a
              fixed-brokerage admin's brokerage is the per-segment fixed rate, and
              a no-brokerage admin's is pinned to 0. */}
          {!hideBrokerageShare && (
            <div className="space-y-1.5">
              <Label>Brokerage share %</Label>
              <Input
                type="number"
                min={0}
                max={100}
                step="0.01"
                placeholder="= PNL share"
                value={form.brokerage_share_pct}
                onChange={(e) => setForm((f) => ({ ...f, brokerage_share_pct: e.target.value }))}
              />
              <p className="text-xs text-muted-foreground">
                How much of this admin&apos;s brokerage you take (blank = same as PNL share)
              </p>
            </div>
          )}
          <div className="space-y-1.5">
            <Label>Opening fund (🪙)</Label>
            <Input
              type="number"
              min={0}
              step="0.01"
              value={form.opening_fund}
              onChange={(e) => setForm((f) => ({ ...f, opening_fund: e.target.value }))}
            />
            <p className="text-xs text-muted-foreground">
              Float the sub-admin can dispense to users (0 = none)
            </p>
          </div>
        </div>

        {/* Fixed-brokerage note (only for the fixed type). */}
        {isFixed && (
          <div className="mt-4 rounded-lg border border-primary/40 bg-primary/5 p-3">
            <p className="text-[12px] text-foreground/80">
              You set the fixed rate <b>per segment</b> in this admin&apos;s{" "}
              <b>Segment settings → Brokerage</b> (NSE fut/opt, MCX, crypto, forex… each its
              own per-lot / per-crore rate). That&apos;s what Account 2 charges the admin,
              regardless of what they charge their own users. Opens right after you create
              them (or via the 3-dot menu anytime).
            </p>
          </div>
        )}

        {/* No-brokerage note. */}
        {isNoBrokerage && (
          <div className="mt-4 rounded-lg border border-primary/40 bg-primary/5 p-3">
            <p className="text-[12px] text-foreground/80">
              This admin&apos;s <b>brokerage share is fixed at 0%</b> — you take <b>none</b> of
              their brokerage, only the <b>PNL share %</b> above. The admin still charges their
              own users whatever their segment settings say; you just don&apos;t take a
              brokerage cut. You can change it later from the 3-dot menu.
            </p>
          </div>
        )}

        <div className="mt-4 space-y-2">
          <div className="text-sm font-medium">Permissions</div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {PERMISSION_LABELS.map((p) => (
              <label key={p.key} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  checked={!!perms[p.key]}
                  onChange={(e) =>
                    setPerms((cur) => ({ ...cur, [p.key]: e.target.checked }))
                  }
                />
                {p.label}
              </label>
            ))}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={loading}>
            Create {isFixed ? "fixed-brokerage admin" : isNoBrokerage ? "no-brokerage admin" : "PNL admin"}
          </Button>
        </DialogFooter>
        </>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ── Edit dialog ────────────────────────────────────────────────────────
function EditSubAdminDialog({
  subAdmin,
  onClose,
  onSaved,
}: {
  subAdmin: any;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [perms, setPerms] = useState<AdminPermissions>({
    ...ALL_OFF,
    ...(subAdmin.permissions || {}),
  });
  const [pnlPct, setPnlPct] = useState<string>(String(subAdmin.pnl_share_pct ?? "0"));
  const [bkgPct, setBkgPct] = useState<string>(
    subAdmin.brokerage_share_pct != null ? String(subAdmin.brokerage_share_pct) : "",
  );
  const [isFixed, setIsFixed] = useState<boolean>(!!subAdmin.is_fixed_brokerage);
  const [loading, setLoading] = useState(false);

  async function save() {
    setLoading(true);
    try {
      await ManagementAPI.updatePermissions(subAdmin.id, perms as unknown as Record<string, boolean>);
      await ManagementAPI.updatePnlShare(
        subAdmin.id, pnlPct, bkgPct.trim() === "" ? undefined : bkgPct,
      );
      await ManagementAPI.updateFixedBrokerage(subAdmin.id, {
        is_fixed_brokerage: isFixed,
      });
      toast.success("Sub-admin updated");
      onSaved();
      onClose();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {subAdmin.full_name}{" "}
            <span className="text-xs text-muted-foreground">{subAdmin.user_code}</span>
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>PNL share %</Label>
              <Input
                type="number"
                min={0}
                max={100}
                step="0.01"
                value={pnlPct}
                onChange={(e) => setPnlPct(e.target.value)}
              />
            </div>
            {!isFixed && (
              <div className="space-y-1.5">
                <Label>Brokerage share %</Label>
                <Input
                  type="number"
                  min={0}
                  max={100}
                  step="0.01"
                  placeholder="= PNL share"
                  value={bkgPct}
                  onChange={(e) => setBkgPct(e.target.value)}
                />
              </div>
            )}
          </div>
          {/* Admin TYPE switch — flip between % (Normal) and fixed (Account 2). */}
          <div className="space-y-2 rounded-lg border border-border/70 bg-muted/20 p-3">
            <div className="text-sm font-medium">Admin type</div>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setIsFixed(false)}
                className={`flex items-center gap-2 rounded-lg border-2 px-3 py-2 text-sm font-medium transition ${
                  !isFixed ? "border-primary bg-primary/10 text-foreground" : "border-border text-muted-foreground hover:border-primary/50"
                }`}
              >
                <Percent className="size-4" /> Normal PNL (%)
              </button>
              <button
                type="button"
                onClick={() => setIsFixed(true)}
                className={`flex items-center gap-2 rounded-lg border-2 px-3 py-2 text-sm font-medium transition ${
                  isFixed ? "border-primary bg-primary/10 text-foreground" : "border-border text-muted-foreground hover:border-primary/50"
                }`}
              >
                <DollarSign className="size-4" /> Fixed brokerage
              </button>
            </div>
            {isFixed && (
              <p className="rounded-md bg-primary/10 px-2.5 py-2 text-[11px] text-foreground/80">
                Fixed rate is set <b>per segment</b> in this admin&apos;s{" "}
                <b>Segment settings → Brokerage</b> (3-dot menu). Account 2 charges the
                admin that frozen rate; whatever they later charge their own users
                doesn&apos;t change it.
              </p>
            )}
          </div>
          <div className="space-y-2">
            <div className="text-sm font-medium">Permissions</div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {PERMISSION_LABELS.map((p) => (
                <label key={p.key} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4 accent-primary"
                    checked={!!perms[p.key]}
                    onChange={(e) =>
                      setPerms((cur) => ({ ...cur, [p.key]: e.target.checked }))
                    }
                  />
                  {p.label}
                </label>
              ))}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} disabled={loading}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Create Broker for Admin dialog ────────────────────────────────────
const BROKER_PERMS_ALL_OFF: BrokerPermissions = {
  users: "OFF",
  kyc: "OFF",
  deposits: "OFF",
  withdrawals: "OFF",
  segment_settings: "OFF",
  risk: "OFF",
  netting: "OFF",
  trading_view: "OFF",
  ledger: "OFF",
  reports: "OFF",
  brokerage: "OFF",
  sub_brokers: "OFF",
  banks: "OFF",
};

function CreateBrokerForAdminDialog({
  open,
  admin,
  onClose,
}: {
  open: boolean;
  admin: { id: string; name: string } | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    mobile: "",
    password: "",
    confirm_password: "",
    pnl_share_pct: "0",
  });
  const [perms, setPerms] = useState<BrokerPermissions>({ ...BROKER_PERMS_ALL_OFF });
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  async function submit() {
    if (form.password.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }
    if (form.password !== form.confirm_password) {
      toast.error("Passwords do not match");
      return;
    }
    setLoading(true);
    try {
      await BrokerMgmtAPI.create({
        full_name: form.full_name,
        email: form.email,
        mobile: form.mobile,
        password: form.password,
        permissions: perms as unknown as Record<string, "OFF" | "VIEW" | "EDIT">,
        pnl_share_pct: form.pnl_share_pct,
        assigned_admin_id: admin?.id,
      });
      toast.success("Broker created");
      onClose();
      setForm({ full_name: "", email: "", mobile: "", password: "", confirm_password: "", pnl_share_pct: "0" });
      setPerms({ ...BROKER_PERMS_ALL_OFF });
      qc.invalidateQueries({ queryKey: ["admin", "brokers"] });
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Create Broker under {admin?.name}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Full name</Label>
              <Input value={form.full_name} onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} />
            </div>
            <div className="space-y-1.5">
              <Label>Email</Label>
              <Input type="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
            </div>
            <div className="space-y-1.5">
              <Label>Mobile (10-digit)</Label>
              <Input value={form.mobile} onChange={(e) => setForm((f) => ({ ...f, mobile: e.target.value }))} />
            </div>
            <div className="space-y-1.5">
              <Label>Password</Label>
              <div className="relative">
                <Input
                  type={showPassword ? "text" : "password"}
                  className="pr-10"
                  value={form.password}
                  onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((s) => !s)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute inset-y-0 right-0 grid w-10 place-items-center text-muted-foreground hover:text-foreground"
                >
                  {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>Confirm password</Label>
              <Input
                type={showPassword ? "text" : "password"}
                value={form.confirm_password}
                onChange={(e) => setForm((f) => ({ ...f, confirm_password: e.target.value }))}
              />
              {form.confirm_password.length > 0 && form.password !== form.confirm_password ? (
                <p className="text-xs text-destructive">Passwords do not match</p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label>PNL share %</Label>
              <Input
                type="number"
                min={0}
                max={100}
                step="0.01"
                value={form.pnl_share_pct}
                onChange={(e) => setForm((f) => ({ ...f, pnl_share_pct: e.target.value }))}
              />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={loading}>
            Create Broker
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
