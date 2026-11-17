"use client";

/**
 * Super-admin: how many shares / units make one lot.
 *
 * A value saved here wins over the platform's built-in tables (and the
 * exchange's lot for stock F&O) on every new order, the order panel and the
 * instrument list. Open positions keep the lot they were filled at. Remove
 * a row to go back to the built-in value. Backend: /api/v1/admin/lot-sizes.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, Pencil, Search, Trash2 } from "lucide-react";
import { LotSizesAPI, type LotMarket, type LotSizeRow } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/common/PageHeader";
import { cn } from "@/lib/utils";

const MARKETS: { value: LotMarket; label: string; hint: string }[] = [
  {
    value: "INDIAN",
    label: "Indian F&O (NSE / BSE / MCX)",
    hint: "Contract name before the expiry: NIFTY, BANKNIFTY, RELIANCE, GOLDM, CRUDEOIL",
  },
  {
    value: "INTERNATIONAL",
    label: "International (forex / crypto / metals)",
    hint: "Symbol: EURUSD, XAUUSD, BTCUSD — use BTC for all BTC options",
  },
];
const marketLabel = (m: LotMarket) => (m === "INDIAN" ? "Indian F&O" : "International");

function errorText(e: unknown) {
  return (e as { message?: string })?.message || "Something went wrong. Please try again.";
}

function istDateTime(v: string | null) {
  if (!v) return "—";
  const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(v) ? v : `${v}Z`);
  return d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export default function LotSizesPage() {
  const qc = useQueryClient();
  const [market, setMarket] = useState<LotMarket>("INDIAN");
  const [underlying, setUnderlying] = useState("");
  const [lotSize, setLotSize] = useState("");
  const [note, setNote] = useState("");
  const [filter, setFilter] = useState("");

  const { data, isLoading, isError, error } = useQuery({ queryKey: ["lot-sizes"], queryFn: LotSizesAPI.list });
  const overrides = data?.overrides ?? [];
  const builtin = data?.builtin ?? [];

  const key = underlying.replace(/\s+/g, "").toUpperCase();
  const builtinNow = builtin.find((b) => b.market === market && b.underlying === key);
  const existing = overrides.find((o) => o.market === market && o.underlying === key);
  const suggestions = useMemo(() => builtin.filter((b) => b.market === market), [builtin, market]);

  const save = useMutation({
    mutationFn: () =>
      LotSizesAPI.save({ market, underlying: key, lot_size: Number(lotSize), note: note.trim() }),
    onSuccess: (r) => {
      toast.success(`${r.underlying}: 1 lot = ${r.lot_size.toLocaleString("en-IN")} · ${r.instruments_updated} instruments updated`);
      setUnderlying("");
      setLotSize("");
      setNote("");
      qc.invalidateQueries({ queryKey: ["lot-sizes"] });
      qc.invalidateQueries({ queryKey: ["admin", "instruments"] });
    },
    onError: (e) => toast.error(errorText(e)),
  });

  const remove = useMutation({
    mutationFn: (row: LotSizeRow) => LotSizesAPI.remove(row.id),
    onSuccess: (r, row) => {
      toast.success(`${row.underlying}: back to the built-in lot size · ${r.instruments_updated} instruments updated`);
      qc.invalidateQueries({ queryKey: ["lot-sizes"] });
      qc.invalidateQueries({ queryKey: ["admin", "instruments"] });
    },
    onError: (e) => toast.error(errorText(e)),
  });

  function edit(m: LotMarket, u: string, lot: number, n = "") {
    setMarket(m);
    setUnderlying(u);
    setLotSize(String(lot));
    setNote(n);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const lotNum = Number(lotSize);
  const canSave = key.length > 0 && Number.isInteger(lotNum) && lotNum >= 1 && !save.isPending;

  const f = filter.trim().toUpperCase();
  const builtinShown = builtin.filter((b) => !f || b.underlying.includes(f) || b.group.toUpperCase().includes(f));
  const overridden = new Set(overrides.map((o) => `${o.market}:${o.underlying}`));

  return (
    <div className="space-y-5">
      <PageHeader
        title="Lot Sizes"
        description="How many shares / units make 1 lot. Your value wins over the built-in one for every new order. Open positions keep the lot they were filled at."
      />

      <Card>
        <CardContent className="space-y-4 p-4 sm:p-5">
          <p className="text-sm font-semibold">{existing ? `Change ${existing.underlying}` : "Set a lot size"}</p>
          <form
            className="grid gap-3 sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,0.7fr)_minmax(0,1fr)_auto] sm:items-end"
            onSubmit={(e) => {
              e.preventDefault();
              if (canSave) save.mutate();
            }}
          >
            <label className="flex flex-col gap-1.5 text-xs font-medium text-muted-foreground">
              Market
              <select
                value={market}
                onChange={(e) => setMarket(e.target.value as LotMarket)}
                className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground"
              >
                {MARKETS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1.5 text-xs font-medium text-muted-foreground">
              Underlying
              <Input
                value={underlying}
                onChange={(e) => setUnderlying(e.target.value.toUpperCase())}
                placeholder={market === "INDIAN" ? "NIFTY" : "EURUSD"}
                list="lot-size-suggestions"
                maxLength={30}
                className="font-mono"
              />
              <datalist id="lot-size-suggestions">
                {suggestions.map((s) => (
                  <option key={s.underlying} value={s.underlying}>
                    {s.group} · {s.lot_size}
                  </option>
                ))}
              </datalist>
            </label>
            <label className="flex flex-col gap-1.5 text-xs font-medium text-muted-foreground">
              Shares / units in 1 lot
              <Input
                value={lotSize}
                onChange={(e) => setLotSize(e.target.value.replace(/\D/g, ""))}
                inputMode="numeric"
                placeholder="75"
                maxLength={8}
              />
            </label>
            <label className="flex flex-col gap-1.5 text-xs font-medium text-muted-foreground">
              Note <span className="sr-only">(optional)</span>
              <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional, e.g. SEBI revision" maxLength={200} />
            </label>
            <Button type="submit" disabled={!canSave}>
              {save.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save
            </Button>
          </form>
          <p className="text-xs text-muted-foreground">
            {MARKETS.find((m) => m.value === market)?.hint}.{" "}
            {key &&
              (builtinNow
                ? `Built-in for ${key}: ${builtinNow.lot_size.toLocaleString("en-IN")}.`
                : market === "INDIAN"
                  ? `${key} has no built-in value — it follows the exchange's lot until you set one.`
                  : `${key} has no built-in value — it uses its segment's default until you set one.`)}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <div className="border-b border-border px-4 py-3 text-sm font-semibold">Your lot sizes</div>
          {isLoading ? (
            <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading…
            </div>
          ) : isError ? (
            <p className="px-4 py-6 text-sm text-red-400">{errorText(error)}</p>
          ) : overrides.length === 0 ? (
            <p className="px-4 py-6 text-sm text-muted-foreground">
              None yet — every instrument uses the built-in lot size below.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3">Underlying</th>
                    <th className="px-4 py-3">Market</th>
                    <th className="px-4 py-3 text-right">1 lot =</th>
                    <th className="px-4 py-3 text-right">Built-in</th>
                    <th className="px-4 py-3">Note</th>
                    <th className="px-4 py-3">Updated</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {overrides.map((r) => (
                    <tr key={r.id}>
                      <td className="px-4 py-3 font-mono font-medium">{r.underlying}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">{marketLabel(r.market)}</td>
                      <td className="px-4 py-3 text-right font-semibold tabular-nums">{r.lot_size.toLocaleString("en-IN")}</td>
                      <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                        {r.builtin_lot_size == null ? "Exchange" : r.builtin_lot_size.toLocaleString("en-IN")}
                      </td>
                      <td className="max-w-[14rem] truncate px-4 py-3 text-xs text-muted-foreground" title={r.note}>
                        {r.note || "—"}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">{istDateTime(r.updated_at)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Change ${r.underlying}`}
                          onClick={() => edit(r.market, r.underlying, r.lot_size, r.note)}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Remove ${r.underlying}`}
                          disabled={remove.isPending}
                          onClick={() => {
                            const back = r.builtin_lot_size == null ? "the exchange's lot" : r.builtin_lot_size.toLocaleString("en-IN");
                            if (window.confirm(`Remove ${r.underlying}? New orders go back to ${back} per lot.`)) remove.mutate(r);
                          }}
                        >
                          <Trash2 className="h-4 w-4 text-red-400" />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <div className="flex flex-col gap-2 border-b border-border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold">Built-in lot sizes</p>
              <p className="text-xs text-muted-foreground">
                Used when you haven&apos;t set one. NSE / BSE stock F&amp;O (RELIANCE, TCS…) follow the exchange&apos;s lot.
              </p>
            </div>
            <div className="relative sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search" className="pl-8" />
            </div>
          </div>
          <div className="max-h-[28rem] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 border-b border-border bg-card text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-4 py-2">Underlying</th>
                  <th className="px-4 py-2">Group</th>
                  <th className="px-4 py-2 text-right">1 lot =</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {builtinShown.map((b) => {
                  const mine = overridden.has(`${b.market}:${b.underlying}`);
                  return (
                    <tr key={`${b.market}:${b.underlying}`} className={cn(mine && "opacity-50")}>
                      <td className="px-4 py-2 font-mono">{b.underlying}</td>
                      <td className="px-4 py-2 text-xs text-muted-foreground">{b.group}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{b.lot_size.toLocaleString("en-IN")}</td>
                      <td className="px-4 py-2 text-right text-xs">
                        {mine ? (
                          <span className="text-muted-foreground">Overridden</span>
                        ) : (
                          <button
                            type="button"
                            className="text-primary hover:underline"
                            onClick={() => edit(b.market, b.underlying, b.lot_size)}
                          >
                            Change
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
