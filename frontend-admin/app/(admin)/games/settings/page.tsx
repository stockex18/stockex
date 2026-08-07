"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Gamepad2, GitBranch, Power, Save, Wrench, Zap, Pencil, CheckCircle2, Lock } from "lucide-react";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AdminGamesAPI, AdminReferralAPI } from "@/lib/api";
import { cn } from "@/lib/utils";

const GAME_LABELS: Record<string, string> = {
  niftyUpDown: "Nifty Up/Down",
  btcUpDown: "BTC Up/Down",
  niftyNumber: "Nifty Number",
  btcNumber: "BTC Number",
  niftyBracket: "Nifty Bracket",
  niftyJackpot: "Nifty Jackpot",
  btcJackpot: "BTC Jackpot",
};

// Field group keys — used purely to organise the inputs into headed sections
// inside a GameCard. The save mutation still iterates the flat GAME_FIELDS.
type GroupKey = "core" | "commission";

// The levers we surface for editing per game (the rest stay at their defaults
// and can be added later). Numbers are edited as strings then coerced on save.
const GAME_FIELDS: { key: string; label: string; group: GroupKey; type?: "bool" }[] = [
  { key: "win_multiplier", label: "Win multiplier", group: "core" },
  { key: "ticket_price", label: "Ticket price (🪙)", group: "core" },
  { key: "min_tickets", label: "Min tickets", group: "core" },
  { key: "max_tickets", label: "Max tickets", group: "core" },
  { key: "fixed_profit", label: "Winning amount (🪙, number games)", group: "core" },
  { key: "top_winners", label: "Top winners (jackpot)", group: "core" },
  // Number-game per-user limits (super-admin controls how much a user can play).
  { key: "bets_per_day", label: "Numbers a user can play / day (number game)", group: "core" },
  { key: "max_tickets_per_number", label: "Max tickets per number (number game)", group: "core" },
  // Up/Down uses start/end_time; Number/Bracket/Jackpot use bidding_* + result.
  { key: "start_time", label: "Betting start — up/down (HH:MM:SS)", group: "core" },
  { key: "end_time", label: "Betting end — up/down (HH:MM:SS)", group: "core" },
  { key: "bidding_start_time", label: "Bidding start — number/bracket/jackpot", group: "core" },
  { key: "bidding_end_time", label: "Bidding end — number/bracket/jackpot", group: "core" },
  { key: "result_time", label: "Result time (HH:MM:SS)", group: "core" },
  // ── Commission & referral — flat % of the gross WINNING amount ───────
  { key: "admin_profit_pct", label: "Admin %  (of winning amount)", group: "commission" },
  { key: "broker_profit_pct", label: "Broker %  (of winning amount)", group: "commission" },
  { key: "sub_broker_profit_pct", label: "Sub-broker %  (of winning amount)", group: "commission" },
  { key: "referrer_profit_pct", label: "Referrer %  (client who shared the code)", group: "commission" },
  { key: "referrer_first_win_only", label: "Referrer paid once per game?", group: "commission", type: "bool" },
];

// Presentation-only grouping metadata: heading, help line and icon per section.
const FIELD_GROUPS: { key: GroupKey; title: string; hint: string; icon: typeof Gamepad2 }[] = [
  {
    key: "core",
    title: "Core",
    hint: "Win / ticket economics, tail limits and the daily timing windows.",
    icon: Gamepad2,
  },
  {
    key: "commission",
    title: "Commission & referral — % of winning amount",
    hint: "On every win, each level gets its % of the FULL winning amount (payout/prize — NOT win − stake), funded from the house. e.g. 🪙600 ticket → 🪙1000 win → Sub-broker gets [Sub-broker%] of 🪙1000, Admin gets [Admin%] of 🪙1000, referral [Referrer%] of 🪙1000.",
    icon: GitBranch,
  },
];

function GameCard({ gameKey, cfg }: { gameKey: string; cfg: any }) {
  const qc = useQueryClient();
  const isJackpot = gameKey === "niftyJackpot" || gameKey === "btcJackpot";
  const [form, setForm] = useState<Record<string, string>>({});
  // Jackpot prize ladder — rank(1..20) → % of the pool. Super-admin sets each.
  const [prizes, setPrizes] = useState<Record<string, string>>({});
  useEffect(() => {
    const f: Record<string, string> = {};
    for (const { key } of GAME_FIELDS) f[key] = String(cfg?.[key] ?? "");
    setForm(f);
    const pp = cfg?.prize_percentages || {};
    const p: Record<string, string> = {};
    for (let r = 1; r <= 20; r++) p[String(r)] = pp[String(r)] != null ? String(pp[String(r)]) : "";
    setPrizes(p);
  }, [cfg]);

  const prizeSum = Array.from({ length: 20 }, (_, i) => Number(prizes[String(i + 1)] || 0)).reduce(
    (a, b) => a + b,
    0,
  );

  const save = useMutation({
    mutationFn: () => {
      const body: any = {};
      for (const { key, type } of GAME_FIELDS) {
        const raw = form[key];
        if (raw === "" || raw == null) continue;
        // Bool → true/false; time fields stay strings; everything else numeric.
        body[key] = type === "bool" ? raw === "true" : key.endsWith("_time") ? raw : Number(raw);
      }
      if (isJackpot) {
        const pp: Record<string, number> = {};
        for (let r = 1; r <= 20; r++) {
          const raw = prizes[String(r)];
          if (raw !== "" && raw != null && isFinite(Number(raw))) pp[String(r)] = Number(raw);
        }
        body.prize_percentages = pp;
      }
      return AdminGamesAPI.updateGame(gameKey, body);
    },
    onSuccess: () => {
      toast.success(`${GAME_LABELS[gameKey]} updated`);
      qc.invalidateQueries({ queryKey: ["admin", "games", "settings"] });
    },
    onError: (e: any) => toast.error(e?.message || "Save failed"),
  });

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => AdminGamesAPI.toggleGame(gameKey, enabled),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "games", "settings"] });
    },
  });

  const disabled = cfg?.enabled === false;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2">
            <Gamepad2 className="size-4 shrink-0 text-primary" />
            <span className="truncate">{GAME_LABELS[gameKey] || gameKey}</span>
          </CardTitle>
          <CardDescription className="flex items-center gap-1.5">
            <span
              className={cn(
                "inline-block size-1.5 rounded-full",
                disabled ? "bg-muted-foreground" : "bg-primary"
              )}
            />
            {disabled ? "Disabled" : "Enabled"}
          </CardDescription>
        </div>
        <Button
          variant={disabled ? "outline" : "destructive"}
          size="sm"
          loading={toggle.isPending}
          onClick={() => toggle.mutate(disabled)}
        >
          <Power className="size-4" />
          {disabled ? "Enable" : "Disable"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-5">
        {FIELD_GROUPS.map(({ key: groupKey, title, hint, icon: Icon }) => {
          // Jackpot uses the rank prize-ladder below, not a single win multiplier
          // or a fixed winning amount — hide those two to avoid confusion.
          const _hide = isJackpot ? ["win_multiplier", "fixed_profit"] : [];
          const fields = GAME_FIELDS.filter(
            (f) => f.group === groupKey && !_hide.includes(f.key),
          );
          if (fields.length === 0) return null;
          return (
            <section key={groupKey} className="space-y-3">
              <div className="space-y-0.5 border-b border-border pb-2">
                <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-foreground">
                  <Icon className="size-3.5 text-primary" />
                  {title}
                </h4>
                <p className="text-[11px] text-muted-foreground">{hint}</p>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {fields.map(({ key, label, type }) => (
                  <div key={key} className="space-y-1">
                    <Label className="text-xs text-muted-foreground">{label}</Label>
                    {type === "bool" ? (
                      <select
                        value={form[key] === "false" ? "false" : "true"}
                        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                        className="flex h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                      >
                        <option value="true">Once per game (first win)</option>
                        <option value="false">Every win</option>
                      </select>
                    ) : (
                      <Input
                        value={form[key] ?? ""}
                        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                      />
                    )}
                  </div>
                ))}
              </div>
            </section>
          );
        })}
        {isJackpot && (
          <section className="space-y-3">
            <div className="space-y-0.5 border-b border-border pb-2">
              <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-foreground">
                🏆 Prize ladder — % of the pool per rank
              </h4>
              <p className="text-[11px] text-muted-foreground">
                The closest {form.top_winners || 20} predictions to the locked close share the pool
                (total tickets collected). Each rank gets its % below. Ties split their combined
                ranks equally.{" "}
                <span
                  className={cn(
                    "font-semibold",
                    prizeSum > 100.01 ? "text-red-600" : "text-emerald-600",
                  )}
                >
                  Total: {prizeSum.toFixed(2)}%
                </span>
                {prizeSum > 100.01
                  ? " ⚠ exceeds 100% — payouts would be MORE than the pool (house loss)."
                  : prizeSum < 99.99
                    ? ` — house keeps ${(100 - prizeSum).toFixed(2)}%.`
                    : " — full pool paid out."}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-5">
              {Array.from({ length: 20 }, (_, i) => i + 1).map((r) => (
                <div key={r} className="flex items-center gap-1.5">
                  <span className="w-7 shrink-0 text-right text-xs font-semibold text-muted-foreground">
                    #{r}
                  </span>
                  <Input
                    inputMode="decimal"
                    value={prizes[String(r)] ?? ""}
                    onChange={(e) => setPrizes((p) => ({ ...p, [String(r)]: e.target.value }))}
                    className="h-8"
                    placeholder="0"
                  />
                  <span className="text-xs text-muted-foreground">%</span>
                </div>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground">
              Broker / hierarchy prize is set separately in the Commission section below (a % of each
              client&apos;s winning amount).
            </p>
          </section>
        )}
        {(gameKey === "niftyNumber" || gameKey === "btcNumber") && (
          <ResultControl gameKey={gameKey} autoResult={cfg?.auto_result !== false} />
        )}
        <div className="flex justify-end pt-1">
          <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>
            <Save className="size-4" />
            Save {GAME_LABELS[gameKey]}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/** Derive the winning two-digit number from a typed closing price, the same
 *  way the backend does: NIFTY → the two fractional digits (24072.75 → 75);
 *  BTC → the integer part's last two digits (75242.89 → 42). */
function deriveNumber(gameKey: string, priceStr: string): number | null {
  const p = Number(priceStr);
  if (!priceStr || !isFinite(p) || p <= 0) return null;
  if (gameKey === "btcNumber") return Math.floor(p) % 100;
  return Math.floor((p - Math.floor(p)) * 100 + 1e-6) % 100;
}

/** Per-game "Result Control" — the auto(Zerodha) ↔ manual switch plus the
 *  admin-typed daily result, the live auto preview and the declared state.
 *  Self-contained: owns its own query + mutations so a save here doesn't
 *  disturb the rest of the game card. */
function ResultControl({ gameKey, autoResult }: { gameKey: string; autoResult: boolean }) {
  const qc = useQueryClient();
  const label = GAME_LABELS[gameKey] || gameKey;
  const { data } = useQuery({
    queryKey: ["admin", "games", "manual-result", gameKey],
    queryFn: () => AdminGamesAPI.manualResult(gameKey),
    refetchInterval: 15000,
  });

  const [price, setPrice] = useState("");
  useEffect(() => {
    setPrice(data?.manual?.close_price ?? "");
  }, [data?.manual?.close_price]);

  const declared = data?.declared ?? null;
  const auto = data?.auto_preview ?? null;
  const derived = deriveNumber(gameKey, price);

  const toggleAuto = useMutation({
    mutationFn: (nextAuto: boolean) => AdminGamesAPI.updateGame(gameKey, { auto_result: nextAuto }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "games", "settings"] });
      qc.invalidateQueries({ queryKey: ["admin", "games", "manual-result", gameKey] });
    },
    onError: (e: any) => toast.error(e?.message || "Could not switch"),
  });

  const saveManual = useMutation({
    mutationFn: () => AdminGamesAPI.setManualResult(gameKey, { close_price: price }),
    onSuccess: (r: any) => {
      toast.success(
        r?.settled_now > 0
          ? `Result #${r.result_number} saved — settled ${r.settled_now} bet(s)`
          : `Result #${r?.result_number} saved`,
      );
      qc.invalidateQueries({ queryKey: ["admin", "games", "manual-result", gameKey] });
    },
    onError: (e: any) => toast.error(e?.message || "Save failed"),
  });

  const clearManual = useMutation({
    mutationFn: () => AdminGamesAPI.clearManualResult(gameKey),
    onSuccess: () => {
      setPrice("");
      qc.invalidateQueries({ queryKey: ["admin", "games", "manual-result", gameKey] });
    },
    onError: (e: any) => toast.error(e?.message || "Could not clear"),
  });

  return (
    <section className="space-y-3 rounded-lg border border-atm/25 bg-atm/[0.03] p-3">
      <div className="flex flex-col gap-2 border-b border-border pb-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-0.5">
          <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-foreground">
            <Zap className="size-3.5 text-atm" />
            Result Control · {data?.result_time ?? "15:45:00"}
          </h4>
          <p className="text-[11px] text-muted-foreground">
            ON = result comes automatically from the Zerodha close. OFF = you type the day&apos;s
            result and it shows to users at result time.
          </p>
        </div>
        {/* Auto (Zerodha) switch */}
        <button
          type="button"
          disabled={toggleAuto.isPending}
          onClick={() => toggleAuto.mutate(!autoResult)}
          className={cn(
            "inline-flex shrink-0 items-center gap-2 rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-colors",
            autoResult
              ? "border-primary/40 bg-primary/10 text-primary"
              : "border-atm/40 bg-atm/10 text-atm",
          )}
        >
          <span className={cn("relative h-4 w-7 rounded-full transition-colors", autoResult ? "bg-primary" : "bg-atm")}>
            <span className={cn("absolute top-0.5 size-3 rounded-full bg-white transition-all", autoResult ? "left-[14px]" : "left-0.5")} />
          </span>
          {autoResult ? "Auto (Zerodha)" : "Manual"}
        </button>
      </div>

      {/* Live auto preview — always visible so the admin sees the Zerodha value */}
      <div className="flex items-center justify-between rounded-md border border-border bg-background/60 px-2.5 py-1.5">
        <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Zap className="size-3 text-primary" /> Zerodha now
        </span>
        <span className="font-mono text-xs font-semibold">
          {auto?.close_price ? `${auto.close_price} → #${auto.result_number}` : "—"}
        </span>
      </div>

      {declared ? (
        <div className="flex items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-2.5 py-2 text-xs">
          <CheckCircle2 className="size-4 shrink-0 text-primary" />
          <span>
            Declared today: <span className="font-bold">#{declared.result_number}</span>
            {declared.close_price && declared.close_price !== "0" ? ` @ ${declared.close_price}` : ""}
            <span className="ml-1 rounded bg-muted px-1 py-0.5 text-[9px] uppercase tracking-wide text-muted-foreground">
              {declared.source === "manual" ? "manual" : "auto"}
            </span>
          </span>
          <Lock className="ml-auto size-3.5 shrink-0 text-muted-foreground" />
        </div>
      ) : autoResult ? (
        <p className="text-[11px] text-muted-foreground">
          Auto mode — the winning number will be taken from the Zerodha close at result time. Switch
          to <span className="font-semibold text-atm">Manual</span> to type it yourself.
        </p>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <div className="flex-1 space-y-1">
              <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Pencil className="size-3" /> Closing price {gameKey === "niftyNumber" ? "(e.g. 24072.75)" : "(e.g. 65432.89)"}
              </Label>
              <Input
                inputMode="decimal"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder={gameKey === "niftyNumber" ? "24072.75" : "65432.89"}
              />
            </div>
            <div className="rounded-md border border-atm/30 bg-atm/10 px-3 py-2 text-center">
              <div className="text-[9px] uppercase tracking-wide text-muted-foreground">Winning #</div>
              <div className="font-mono text-lg font-bold leading-none text-atm">
                {derived !== null ? String(derived).padStart(2, "0") : "—"}
              </div>
            </div>
          </div>
          <div className="flex items-center justify-end gap-2">
            {data?.manual && (
              <Button size="sm" variant="outline" loading={clearManual.isPending} onClick={() => clearManual.mutate()}>
                Clear
              </Button>
            )}
            <Button size="sm" loading={saveManual.isPending} disabled={derived === null} onClick={() => saveManual.mutate()}>
              <Save className="size-4" /> Save result
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}

export default function GameSettingsPage() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["admin", "games", "settings"],
    queryFn: () => AdminGamesAPI.settings(),
  });

  const toggleAll = useMutation({
    mutationFn: (enabled: boolean) => AdminGamesAPI.toggleAll(enabled),
    onSuccess: () => {
      toast.success("Updated");
      qc.invalidateQueries({ queryKey: ["admin", "games", "settings"] });
    },
  });
  const maintenance = useMutation({
    mutationFn: (on: boolean) => AdminGamesAPI.setMaintenance({ maintenance_mode: on }),
    onSuccess: () => {
      toast.success("Updated");
      qc.invalidateQueries({ queryKey: ["admin", "games", "settings"] });
    },
  });

  const games = data?.games || {};

  return (
    <div className="space-y-6">
      <PageHeader
        title="Game Settings"
        description="Configure the prediction games — multipliers, ticket prices, limits and timing windows."
        actions={
          <>
            <Button
              variant="outline"
              loading={toggleAll.isPending}
              onClick={() => toggleAll.mutate(!(data?.games_enabled))}
            >
              <Power className="size-4" />
              {data?.games_enabled ? "Disable all games" : "Enable all games"}
            </Button>
            <Button
              variant={data?.maintenance_mode ? "default" : "outline"}
              loading={maintenance.isPending}
              onClick={() => maintenance.mutate(!data?.maintenance_mode)}
            >
              <Wrench className="size-4" />
              {data?.maintenance_mode ? "Exit maintenance" : "Maintenance mode"}
            </Button>
          </>
        }
      />

      <ReferralEligibilityCard />

      <div className="grid gap-4">
        {Object.keys(GAME_LABELS).map((k) => (
          <GameCard key={k} gameKey={k} cfg={games[k]} />
        ))}
      </div>
    </div>
  );
}

/** SUPER_ADMIN sets the referral payout threshold gate (shared by games +
 *  trading referral). A referral only pays once the referred user's subtree
 *  has earned the house at least this much. */
function ReferralEligibilityCard() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["admin", "referral", "eligibility"],
    queryFn: () => AdminReferralAPI.eligibility(),
  });
  const [form, setForm] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!data) return;
    setForm({
      enabled: data.enabled ? "1" : "0",
      threshold_amount: String(data.threshold_amount ?? ""),
      threshold_unit: data.threshold_unit ?? "PER_CRORE",
    });
  }, [data]);

  const save = useMutation({
    mutationFn: () =>
      AdminReferralAPI.updateEligibility({
        enabled: form.enabled === "1",
        threshold_amount: Number(form.threshold_amount),
        threshold_unit: form.threshold_unit,
      }),
    onSuccess: () => {
      toast.success("Referral eligibility updated");
      qc.invalidateQueries({ queryKey: ["admin", "referral", "eligibility"] });
    },
    onError: (e: any) => toast.error(e?.message || "Save failed"),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GitBranch className="size-4 text-primary" />
          Referral payout gate
        </CardTitle>
        <CardDescription>
          A referral reward is only paid once the referred user&apos;s subtree has earned the house
          at least the threshold. Applies to games + trading referral.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">Enabled (1/0)</Label>
            <Input
              value={form.enabled ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.value }))}
            />
            <p className="text-[11px] text-muted-foreground">Set 1 to enforce the gate, 0 to pay referrals immediately.</p>
          </div>
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">Threshold amount</Label>
            <Input
              value={form.threshold_amount ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, threshold_amount: e.target.value }))}
            />
            <p className="text-[11px] text-muted-foreground">House earnings the subtree must clear first.</p>
          </div>
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">Unit (PER_CRORE / ABSOLUTE)</Label>
            <Input
              value={form.threshold_unit ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, threshold_unit: e.target.value }))}
            />
            <p className="text-[11px] text-muted-foreground">How the threshold amount is measured.</p>
          </div>
        </div>
        <div className="flex justify-end border-t border-border pt-3">
          <Button onClick={() => save.mutate()} loading={save.isPending}>
            <Save className="size-4" />
            Save
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
