"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import {
  Bell,
  BellOff,
  Building2,
  CalendarClock,
  Check,
  Coins,
  Loader2,
  Mail,
  MapPin,
  Moon,
  Palette,
  Play,
  Search,
  ShieldCheck,
  Sun,
  User,
  UserX,
  Volume2,
  VolumeX,
} from "lucide-react";
import { toast } from "sonner";
import { useAdminAuthStore } from "@/stores/authStore";
import { SettingsAPI, AdminMeAPI, ManagementAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PortfolioCapCard } from "@/components/admin/PortfolioCapCard";
import { PageHeader } from "@/components/common/PageHeader";
import { cn } from "@/lib/utils";
import { playNotifyPing } from "@/lib/notify-sound";

/**
 * Slimmed-down Platform Settings — operator request was to drop every
 * auto-generated platform.* knob and surface only the three controls
 * an admin actually touches day-to-day:
 *
 *   1. Theme        — light / dark / system, via next-themes
 *   2. Profile      — read-only identity card (name / email / mobile /
 *                     role) pulled from the auth store
 *   3. Notifications — master on/off for the WhatsApp-style live
 *                     toast + ping (deposit / withdrawal request
 *                     events from AdminWsBridge). Persisted in
 *                     localStorage under NOTIFY_KEY so the WsBridge
 *                     can read it without re-mounting.
 *
 * Everything else (platform.name, support_email, currency, …) was
 * noise on a mobile screen and was driving operators away from this
 * page. If those knobs ever need a UI again, give them their own
 * /settings/branding-style page.
 */

const NOTIFY_KEY = "admin.notifications.enabled";

/** Read the persisted notification toggle. Default: ON. Kept local to
 *  the page (not exported) — Next.js App Router only allows the
 *  default page export from a `page.tsx` file. AdminWsBridge defines
 *  its own copy of this helper since it runs even when the settings
 *  page isn't mounted. */
function readNotifyEnabled(): boolean {
  if (typeof window === "undefined") return true;
  const v = window.localStorage.getItem(NOTIFY_KEY);
  return v === null ? true : v === "1";
}

export default function PlatformSettingsPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Platform settings"
        description="Theme, your profile, and live notification preferences."
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <ThemeCard />
        <ProfileCard />
        <NotificationsCard />
        <WeeklySettlementCard />
        <PlatformChargeCard />
        <ZeroBalanceAutocloseCard />
        <PortfolioCapCard />
      </div>

      <BrokerSearchVisibilityCard
        field="hidden_admin_ids"
        title="Signup broker search"
        description={
          <>
            Which admins&apos; brokers appear when a <span className="font-medium text-foreground">user</span>{" "}
            searches at signup. Turn an admin <span className="font-medium text-foreground">OFF</span> to hide
            all their brokers.
          </>
        }
      />

      <BrokerSearchVisibilityCard
        field="hidden_signup_admin_ids"
        title="Broker signup — choose your admin"
        description={
          <>
            Which admins a <span className="font-medium text-foreground">new broker</span> can pick at
            registration. Turn an admin <span className="font-medium text-foreground">OFF</span> and no broker
            can sign up under them. Separate from the list above.
          </>
        }
      />
    </div>
  );
}

/* ── Signup visibility (SUPER_ADMIN) ──────────────────────────────────
   Two lists, same shape, one card: whose BROKERS a user sees at signup,
   and which ADMINS a brand-new broker may sign up under. Kept apart
   deliberately — an admin can be right for one and wrong for the other. */
function BrokerSearchVisibilityCard({
  field,
  title,
  description,
}: {
  field: "hidden_admin_ids" | "hidden_signup_admin_ids";
  title: string;
  description: React.ReactNode;
}) {
  const admin = useAdminAuthStore((s) => s.admin);
  const isSuperAdmin = (admin?.role ?? "") === "SUPER_ADMIN";
  const [admins, setAdmins] = useState<any[]>([]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");

  useEffect(() => {
    if (!isSuperAdmin) return;
    (async () => {
      try {
        const [list, h] = await Promise.all([
          ManagementAPI.listSubAdmins({ page_size: 200 }),
          SettingsAPI.brokerSearchHidden(),
        ]);
        setAdmins((list as any)?.items ?? (Array.isArray(list) ? list : []));
        setHidden(new Set((h as any)?.[field] ?? []));
      } catch {
        /* ignore */
      } finally {
        setLoading(false);
      }
    })();
  }, [isSuperAdmin, field]);

  if (!isSuperAdmin) return null;

  async function toggle(id: string) {
    const prev = hidden;
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    setHidden(next);
    try {
      await SettingsAPI.setBrokerSearchHidden({ [field]: [...next] });
    } catch (e: any) {
      toast.error(e?.message || "Save failed");
      setHidden(prev); // revert
    }
  }

  const needle = q.trim().toLowerCase();
  const filtered = admins.filter(
    (a) =>
      !needle ||
      String(a.full_name || "").toLowerCase().includes(needle) ||
      String(a.user_code || "").toLowerCase().includes(needle),
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Building2 className="size-4 text-primary" /> {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search admins" className="h-9 pl-8" />
        </div>
        {loading ? (
          <div className="py-6 text-center text-sm text-muted-foreground">Loading admins…</div>
        ) : filtered.length === 0 ? (
          <div className="py-6 text-center text-sm text-muted-foreground">No admins found.</div>
        ) : (
          <div className="space-y-1.5">
            {filtered.map((a) => {
              const shown = !hidden.has(a.id);
              return (
                <div key={a.id} className="flex items-center justify-between gap-2 rounded-lg border border-border/60 bg-card p-2.5">
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold">{a.full_name || a.user_code}</span>
                    <span className="block font-mono text-[11px] text-muted-foreground">
                      {a.user_code}
                      {typeof a.broker_count === "number" ? ` · ${a.broker_count} broker${a.broker_count === 1 ? "" : "s"}` : ""}
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className={cn("text-[10px] font-bold uppercase", shown ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground")}>
                      {shown ? "Shown" : "Hidden"}
                    </span>
                    <button
                      type="button"
                      onClick={() => toggle(a.id)}
                      aria-pressed={shown}
                      aria-label={
                        field === "hidden_admin_ids"
                          ? shown
                            ? "Hide this admin's brokers"
                            : "Show this admin's brokers"
                          : shown
                            ? "Hide this admin from broker signup"
                            : "Show this admin in broker signup"
                      }
                      className={cn(
                        "relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full transition-colors",
                        shown ? "bg-emerald-500" : "bg-muted",
                      )}
                    >
                      <span className={cn("inline-block size-5 transform rounded-full bg-white shadow transition-transform", shown ? "translate-x-6" : "translate-x-1")} />
                    </button>
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}


// ── Theme ────────────────────────────────────────────────────────────

function ThemeCard() {
  const { resolvedTheme, setTheme, theme: setting } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const current: "light" | "dark" | "system" = mounted
    ? (setting as any) || "system"
    : "system";
  const effective = mounted ? resolvedTheme : "dark";

  const options: { key: "light" | "dark" | "system"; label: string; Icon: typeof Sun }[] = [
    { key: "light",  label: "Light",  Icon: Sun },
    { key: "dark",   label: "Dark",   Icon: Moon },
    { key: "system", label: "System", Icon: Palette },
  ];

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Palette className="size-4 text-primary" /> Theme
        </CardTitle>
        <CardDescription>
          Currently active: <span className="font-semibold capitalize text-foreground">{effective}</span>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {options.map(({ key, label, Icon }) => {
          const active = current === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setTheme(key)}
              className={cn(
                "flex w-full items-center gap-3 rounded-md border px-3 py-2.5 text-sm transition-colors",
                active
                  ? "border-primary bg-primary/10 text-foreground"
                  : "border-border bg-card text-muted-foreground hover:border-primary/40 hover:text-foreground",
              )}
            >
              <Icon className={cn("size-4", active && "text-primary")} />
              <span className="flex-1 text-left font-medium">{label}</span>
              {active && <Check className="size-4 text-primary" />}
            </button>
          );
        })}
      </CardContent>
    </Card>
  );
}


// ── Profile ─────────────────────────────────────────────────────────

function ProfileCard() {
  const admin = useAdminAuthStore((s) => s.admin);
  if (!admin) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <User className="size-4 text-primary" /> Profile
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Not signed in.</p>
        </CardContent>
      </Card>
    );
  }

  const initials = (admin.full_name || admin.user_code || "?")
    .split(/\s+/)
    .map((s: string) => s[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <User className="size-4 text-primary" /> Profile
        </CardTitle>
        <CardDescription>Signed-in admin identity</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-3 rounded-md border border-border bg-card p-3">
          <div className="grid size-12 place-items-center rounded-full bg-primary/15 text-base font-semibold text-primary">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold">{admin.full_name || "—"}</div>
            <div className="truncate font-mono text-[11px] text-muted-foreground">
              {admin.user_code || "—"}
            </div>
          </div>
          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-primary">
            {admin.role}
          </span>
        </div>

        <ul className="space-y-1.5 text-sm">
          <ProfileRow Icon={Mail} label="Email" value={admin.email || "—"} />
          <ProfileRow
            Icon={ShieldCheck}
            label="Role"
            value={String(admin.role).replace(/_/g, " ")}
          />
        </ul>

        <CityEditor />
      </CardContent>
    </Card>
  );
}

/* Self-service city (place) — a BROKER sets this so they show up in the
   signup broker-search. Visible to every admin-tier user. */
function CityEditor() {
  const [city, setCity] = useState("");
  const [initial, setInitial] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    AdminMeAPI.profile()
      .then((p) => {
        setCity(p?.city || "");
        setInitial(p?.city || "");
      })
      .catch(() => {});
  }, []);

  async function save() {
    setSaving(true);
    try {
      const res = await AdminMeAPI.setProfile({ city });
      setInitial(res?.city || "");
      setCity(res?.city || "");
      toast.success("City saved");
    } catch (e: any) {
      toast.error(e?.message || "Could not save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-md border border-border bg-card p-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
        <MapPin className="size-3.5 text-primary" /> Your city (place)
      </div>
      <p className="mt-0.5 text-[11px] text-muted-foreground">
        Brokers: set your city so clients can find you in the signup broker-search.
      </p>
      <div className="mt-2 flex items-center gap-2">
        <Input
          value={city}
          onChange={(e) => setCity(e.target.value)}
          placeholder="e.g. Mumbai"
          className="h-9"
        />
        <Button size="sm" disabled={saving || city.trim() === initial.trim()} loading={saving} onClick={save}>
          Save
        </Button>
      </div>
    </div>
  );
}

function ProfileRow({
  Icon,
  label,
  value,
}: {
  Icon: typeof User;
  label: string;
  value: string;
}) {
  return (
    <li className="flex items-center gap-3 rounded-md bg-muted/30 px-3 py-2">
      <Icon className="size-4 shrink-0 text-muted-foreground" />
      <div className="flex-1">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="truncate text-sm font-medium">{value}</div>
      </div>
    </li>
  );
}


// ── Notifications ───────────────────────────────────────────────────

function NotificationsCard() {
  const [enabled, setEnabled] = useState<boolean>(() => readNotifyEnabled());
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  function toggle(v: boolean) {
    setEnabled(v);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(NOTIFY_KEY, v ? "1" : "0");
      // Broadcast to any open admin tab/window so they all flip together.
      window.dispatchEvent(new StorageEvent("storage", { key: NOTIFY_KEY, newValue: v ? "1" : "0" }));
    }
  }

  function testPing() {
    if (!enabled) return;
    playNotifyPing();
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {enabled ? (
            <Bell className="size-4 text-emerald-500" />
          ) : (
            <BellOff className="size-4 text-muted-foreground" />
          )}
          Notifications
        </CardTitle>
        <CardDescription>
          Live toast + ping when a user submits a deposit / withdrawal request.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Master switch — large pill row that's easy to tap on phones */}
        <div className="flex items-center justify-between rounded-md border border-border bg-card p-3">
          <div className="min-w-0">
            <div className="text-sm font-semibold">Live alerts</div>
            <div className="text-[11px] text-muted-foreground">
              {enabled ? "On — deposits / withdrawals will ping" : "Off — silent mode"}
            </div>
          </div>
          <button
            type="button"
            onClick={() => toggle(!enabled)}
            aria-pressed={enabled}
            aria-label={enabled ? "Turn notifications off" : "Turn notifications on"}
            className={cn(
              "relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full transition-colors",
              enabled ? "bg-emerald-500" : "bg-muted",
            )}
          >
            <span
              className={cn(
                "inline-block size-5 transform rounded-full bg-white shadow transition-transform",
                enabled ? "translate-x-6" : "translate-x-1",
              )}
            />
          </button>
        </div>

        {/* Test button — proves the sound permission is granted and the
            file is reachable. Disabled while notifications are off so
            the operator can't ping themselves through a silenced state. */}
        <Button
          type="button"
          variant="outline"
          className="w-full justify-center gap-2"
          disabled={!mounted || !enabled}
          onClick={testPing}
        >
          {enabled ? <Volume2 className="size-4" /> : <VolumeX className="size-4" />}
          Test sound
        </Button>

        <ul className="space-y-1 text-[11px] text-muted-foreground">
          <li>· Toast pops top-right with the user name + amount.</li>
          <li>· One short ping plays at the same time.</li>
          <li>· Each toast has a "View" button that opens /payments.</li>
          <li>· Setting is saved to this browser only.</li>
        </ul>
      </CardContent>
    </Card>
  );
}


// ── Weekly settlement ───────────────────────────────────────────────

/**
 * Weekly mark-to-market settlement control. Super-admin only.
 *
 *   • Toggle  — flips the `weekly_settlement.enabled` PlatformSetting via
 *               the backend (kill-switch; default ON).
 *   • Run now — manually triggers the batch for the current ISO week so the
 *               operator can verify it end-to-end before the first scheduled
 *               Saturday. Idempotent on the backend (unique per-week batch).
 *
 * The engine itself runs server-side every Saturday 00:00 IST regardless of
 * this page — this card only exposes the on/off switch + a manual trigger.
 */
const WEEKLY_SETTLEMENT_KEY = "weekly_settlement.enabled";

function WeeklySettlementCard() {
  const admin = useAdminAuthStore((s) => s.admin);
  const [enabled, setEnabled] = useState<boolean>(true);
  const [loaded, setLoaded] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [running, setRunning] = useState(false);

  const role = String(admin?.role || "");
  // Card is visible to ADMIN + SUPER_ADMIN only (brokers / sub-brokers excluded).
  const canSee = role === "SUPER_ADMIN" || role === "ADMIN";
  // The platform-wide auto-run kill-switch is super-admin only; admins get
  // the scoped "Run now" for their own user pool.
  const isSuperAdmin = role === "SUPER_ADMIN";

  useEffect(() => {
    if (!isSuperAdmin) return;
    let alive = true;
    SettingsAPI.platformList("trading")
      .then((rows) => {
        if (!alive) return;
        const row = (rows || []).find((r: any) => r?.key === WEEKLY_SETTLEMENT_KEY);
        // Default ON when the row doesn't exist yet (matches backend default).
        setEnabled(row ? Boolean(row.value) : true);
        setLoaded(true);
      })
      .catch(() => {
        if (alive) setLoaded(true);
      });
    return () => {
      alive = false;
    };
  }, [isSuperAdmin]);

  if (!canSee) return null;

  async function toggle(next: boolean) {
    setToggling(true);
    try {
      await SettingsAPI.setWeeklySettlementEnabled(next);
      setEnabled(next);
      toast.success(next ? "Weekly settlement enabled" : "Weekly settlement disabled");
    } catch (e: any) {
      toast.error(e?.message || "Failed to update setting");
    } finally {
      setToggling(false);
    }
  }

  async function runNow() {
    setRunning(true);
    try {
      const res = await SettingsAPI.weeklySettlementRun();
      if ((res as any)?.skipped_reason || (res as any)?.skipped) {
        toast.message("Settlement not run", {
          description: `Reason: ${(res as any)?.reason || (res as any)?.skipped_reason || "disabled / already done"}`,
        });
      } else {
        toast.success(`Settlement ${res.week_key ?? ""} done`, {
          description: `Settled ${res.settled ?? 0} · skipped ${res.skipped ?? 0} · failed ${res.failed ?? 0} (of ${res.total ?? 0})`,
        });
      }
    } catch (e: any) {
      toast.error(e?.message || "Settlement run failed");
    } finally {
      setRunning(false);
    }
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarClock className="size-4 text-primary" /> Weekly settlement
        </CardTitle>
        <CardDescription>
          Saturday 00:00 IST: books open-position P&amp;L to wallets and re-opens
          each position at the settlement price.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Platform-wide auto-run switch — SUPER_ADMIN only. */}
        {isSuperAdmin ? (
          <div className="flex items-center justify-between rounded-md border border-border bg-card p-3">
            <div className="min-w-0">
              <div className="text-sm font-semibold">Auto-run weekly</div>
              <div className="text-[11px] text-muted-foreground">
                {enabled ? "On — fires every Saturday (all users)" : "Off — engine paused"}
              </div>
            </div>
            <button
              type="button"
              onClick={() => toggle(!enabled)}
              disabled={!loaded || toggling}
              aria-pressed={enabled}
              aria-label={enabled ? "Disable weekly settlement" : "Enable weekly settlement"}
              className={cn(
                "relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full transition-colors disabled:opacity-50",
                enabled ? "bg-emerald-500" : "bg-muted",
              )}
            >
              <span
                className={cn(
                  "inline-block size-5 transform rounded-full bg-white shadow transition-transform",
                  enabled ? "translate-x-6" : "translate-x-1",
                )}
              />
            </button>
          </div>
        ) : (
          <div className="rounded-md border border-border bg-muted/30 p-3 text-[11px] text-muted-foreground">
            Auto-run is managed platform-wide by the super-admin. You can settle
            <span className="font-medium text-foreground"> your own users </span>
            on demand below.
          </div>
        )}

        <Button
          type="button"
          variant="outline"
          className="w-full justify-center gap-2"
          disabled={running}
          onClick={runNow}
        >
          {running ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
          {running ? "Running…" : "Run now (my users)"}
        </Button>

        <ul className="space-y-1 text-[11px] text-muted-foreground">
          <li>· Settles only the users you own ({isSuperAdmin ? "your pool" : "your clients & brokers"}).</li>
          <li>· Profit credited / loss debited to each user's wallet.</li>
          <li>· Same side &amp; lots kept; entry price resets, P&amp;L back to 0.</li>
          <li>· "Run now" is idempotent — safe to test before Saturday.</li>
        </ul>
      </CardContent>
    </Card>
  );
}

/* ── Per-admin DAILY PLATFORM CHARGE (ADMIN / SUPER_ADMIN) ─────────────────
 * Each admin sets a per-user daily fee for THEIR OWN users. Default OFF. When
 * on, the leader sweep debits the amount from each active user's main wallet
 * once/day and credits it to this admin. */
function PlatformChargeCard() {
  const admin = useAdminAuthStore((s) => s.admin);
  const role = String(admin?.role || "");
  const canSee = role === "SUPER_ADMIN" || role === "ADMIN";

  const [enabled, setEnabled] = useState(false);
  const [amount, setAmount] = useState("0");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    if (!canSee) return;
    let alive = true;
    SettingsAPI.platformMaintenance()
      .then((d) => {
        if (!alive) return;
        setEnabled(Boolean(d.platform_charge_enabled));
        setAmount(String(Number(d.platform_charge_amount || 0)));
        setLoaded(true);
      })
      .catch(() => alive && setLoaded(true));
    return () => {
      alive = false;
    };
  }, [canSee]);

  if (!canSee) return null;

  async function toggle(next: boolean) {
    setToggling(true);
    try {
      await SettingsAPI.setPlatformMaintenance({ platform_charge_enabled: next });
      setEnabled(next);
      toast.success(next ? "Platform charge enabled" : "Platform charge disabled");
    } catch (e: any) {
      toast.error(e?.message || "Failed to update");
    } finally {
      setToggling(false);
    }
  }

  async function saveAmount() {
    const amt = Number(amount);
    if (!Number.isFinite(amt) || amt < 0) {
      toast.error("Enter a valid amount");
      return;
    }
    setSaving(true);
    try {
      const d = await SettingsAPI.setPlatformMaintenance({ platform_charge_amount: amt });
      setAmount(String(Number(d.platform_charge_amount || 0)));
      toast.success("Charge amount saved");
    } catch (e: any) {
      toast.error(e?.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Coins className="size-4 text-primary" /> Platform charge (per user / day)
        </CardTitle>
        <CardDescription>
          A daily fee deducted from each of your users' main wallet and credited
          to you. Off by default.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between rounded-md border border-border bg-card p-3">
          <div className="min-w-0">
            <div className="text-sm font-semibold">Daily charge</div>
            <div className="text-[11px] text-muted-foreground">
              {enabled ? "On — charged every day per user" : "Off — no charge"}
            </div>
          </div>
          <button
            type="button"
            onClick={() => toggle(!enabled)}
            disabled={!loaded || toggling}
            aria-pressed={enabled}
            className={cn(
              "relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full transition-colors disabled:opacity-50",
              enabled ? "bg-emerald-500" : "bg-muted",
            )}
          >
            <span
              className={cn(
                "inline-block size-5 transform rounded-full bg-white shadow transition-transform",
                enabled ? "translate-x-6" : "translate-x-1",
              )}
            />
          </button>
        </div>

        <div className="space-y-1.5">
          <label className="text-[11px] font-medium text-muted-foreground">Amount per user / day (🪙)</label>
          <div className="flex gap-2">
            <Input
              value={amount}
              onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))}
              inputMode="decimal"
              placeholder="0.00"
              className="h-9 font-tabular"
              disabled={!loaded}
            />
            <Button type="button" onClick={saveAmount} disabled={saving || !loaded} className="h-9">
              {saving ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
              Save
            </Button>
          </div>
        </div>

        <ul className="space-y-1 text-[11px] text-muted-foreground">
          <li>· Charged once per day, from each active user's main wallet.</li>
          <li>· Users who can't cover it pay only what they have (never negative).</li>
          <li>· Collected amount is credited to your main wallet.</li>
        </ul>
      </CardContent>
    </Card>
  );
}

/* ── Per-admin ZERO-BALANCE AUTO-CLOSE (ADMIN / SUPER_ADMIN) ───────────────
 * When on, a user of this admin whose whole balance has been 🪙0 for ≥7 days
 * (and holds no open position) is soft-closed (status CLOSED, recoverable). */
function ZeroBalanceAutocloseCard() {
  const admin = useAdminAuthStore((s) => s.admin);
  const role = String(admin?.role || "");
  const canSee = role === "SUPER_ADMIN" || role === "ADMIN";

  const [enabled, setEnabled] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    if (!canSee) return;
    let alive = true;
    SettingsAPI.platformMaintenance()
      .then((d) => {
        if (!alive) return;
        setEnabled(Boolean(d.zero_balance_autoclose_enabled));
        setLoaded(true);
      })
      .catch(() => alive && setLoaded(true));
    return () => {
      alive = false;
    };
  }, [canSee]);

  if (!canSee) return null;

  async function toggle(next: boolean) {
    setToggling(true);
    try {
      await SettingsAPI.setPlatformMaintenance({ zero_balance_autoclose_enabled: next });
      setEnabled(next);
      toast.success(next ? "Auto-close enabled" : "Auto-close disabled");
    } catch (e: any) {
      toast.error(e?.message || "Failed to update");
    } finally {
      setToggling(false);
    }
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <UserX className="size-4 text-primary" /> Zero-balance auto-close
        </CardTitle>
        <CardDescription>
          A user with 🪙0 balance for 7 days is automatically closed (blocked,
          recoverable — not deleted). Off by default.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between rounded-md border border-border bg-card p-3">
          <div className="min-w-0">
            <div className="text-sm font-semibold">Auto-close after 7 days</div>
            <div className="text-[11px] text-muted-foreground">
              {enabled ? "On — empty accounts closed after 7 days" : "Off — accounts stay"}
            </div>
          </div>
          <button
            type="button"
            onClick={() => toggle(!enabled)}
            disabled={!loaded || toggling}
            aria-pressed={enabled}
            className={cn(
              "relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full transition-colors disabled:opacity-50",
              enabled ? "bg-emerald-500" : "bg-muted",
            )}
          >
            <span
              className={cn(
                "inline-block size-5 transform rounded-full bg-white shadow transition-transform",
                enabled ? "translate-x-6" : "translate-x-1",
              )}
            />
          </button>
        </div>
        <ul className="space-y-1 text-[11px] text-muted-foreground">
          <li>· "🪙0" = main + all segment wallets empty, no open position.</li>
          <li>· 7-day clock resets the moment any money returns.</li>
          <li>· Closed = login blocked; you can reactivate anytime (data kept).</li>
        </ul>
      </CardContent>
    </Card>
  );
}
