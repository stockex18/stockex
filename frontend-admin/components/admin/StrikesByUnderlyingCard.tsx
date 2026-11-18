"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { SettingsAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * ITM / OTM strikes per instrument (super-admin).
 *
 * Requested by the client so each instrument can have its own ITM / OTM range
 * instead of one "strikes around ATM" number per segment. Stored as
 * `option_chain.strikes_by_underlying` = {"NIFTY": {"itm": 10, "otm": 20}}.
 * A blank box uses the segment's "strikes around ATM" value.
 *
 * A call is ITM below spot and a put above it, so the backend applies these
 * counts to each side separately (CE: ITM below / OTM above; PE: the reverse).
 */

const KEY = "option_chain.strikes_by_underlying";
const SEG_KEY = "option_chain.strikes_around_atm_by_segment";

// Shown by default so the common ones are one click away; any stock can be added.
const INDEX = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"];
const MCX = ["CRUDEOIL", "NATURALGAS", "GOLD", "GOLDM", "SILVER", "SILVERM", "COPPER", "ZINC"];
const CRYPTO = ["BTC", "ETH"];
const DEFAULT_LIST = [...INDEX, ...MCX, ...CRYPTO];

type Entry = { itm: string; otm: string };
type Saved = Record<string, { itm?: number; otm?: number }>;

function segmentFor(symbol: string): { key: string; label: string } {
  if (INDEX.includes(symbol)) return { key: "NSE_IDX_OPT", label: "Index" };
  if (MCX.includes(symbol)) return { key: "MCX_OPT", label: "MCX" };
  if (CRYPTO.includes(symbol)) return { key: "CRYPTO_OPT", label: "Crypto" };
  return { key: "NSE_STK_OPT", label: "Stock" };
}

function toEntries(saved: Saved): Record<string, Entry> {
  const out: Record<string, Entry> = {};
  for (const s of DEFAULT_LIST) out[s] = { itm: "", otm: "" };
  for (const [s, v] of Object.entries(saved || {})) {
    out[s] = { itm: v?.itm ? String(v.itm) : "", otm: v?.otm ? String(v.otm) : "" };
  }
  return out;
}

function toSaved(entries: Record<string, Entry>): Saved {
  const out: Saved = {};
  for (const [s, e] of Object.entries(entries)) {
    const itm = Number(e.itm);
    const otm = Number(e.otm);
    const v: { itm?: number; otm?: number } = {};
    if (e.itm.trim() !== "" && itm > 0) v.itm = itm;
    if (e.otm.trim() !== "" && otm > 0) v.otm = otm;
    if (v.itm || v.otm) out[s] = v;
  }
  return out;
}

export function StrikesByUnderlyingCard() {
  const qc = useQueryClient();
  const { data: rows } = useQuery({
    queryKey: ["admin", "settings", "platform", "option_chain"],
    queryFn: () => SettingsAPI.platformList("option_chain"),
  });
  const saved = useMemo<Saved>(() => (rows?.find((r: any) => r.key === KEY)?.value || {}) as Saved, [rows]);
  const segDefaults = useMemo<Record<string, number>>(
    () => (rows?.find((r: any) => r.key === SEG_KEY)?.value || {}) as Record<string, number>,
    [rows],
  );

  const [entries, setEntries] = useState<Record<string, Entry>>(() => toEntries({}));
  const [newSymbol, setNewSymbol] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (rows) setEntries(toEntries(saved));
  }, [rows, saved]);

  const dirty = JSON.stringify(toSaved(entries)) !== JSON.stringify(toSaved(toEntries(saved)));

  function setField(symbol: string, field: keyof Entry, value: string) {
    setEntries((p) => ({ ...p, [symbol]: { ...p[symbol], [field]: value.replace(/[^0-9]/g, "") } }));
  }

  function addSymbol() {
    const s = newSymbol.trim().toUpperCase().replace(/\s+/g, "");
    if (!s) return;
    if (entries[s]) {
      toast.info(`${s} is already in the list`);
    } else {
      setEntries((p) => ({ ...p, [s]: { itm: "", otm: "" } }));
    }
    setNewSymbol("");
  }

  function removeSymbol(symbol: string) {
    setEntries((p) => {
      const next = { ...p };
      if (DEFAULT_LIST.includes(symbol)) next[symbol] = { itm: "", otm: "" };
      else delete next[symbol];
      return next;
    });
  }

  async function save() {
    for (const [s, e] of Object.entries(entries)) {
      for (const f of ["itm", "otm"] as const) {
        if (e[f].trim() === "") continue;
        const n = Number(e[f]);
        if (!Number.isInteger(n) || n < 1 || n > 100) {
          toast.error(`${s}: ${f.toUpperCase()} must be a whole number from 1 to 100, or blank`);
          return;
        }
      }
    }
    setSaving(true);
    try {
      await SettingsAPI.updatePlatform(KEY, toSaved(entries));
      toast.success("ITM / OTM strikes saved — live for traders within a minute");
      qc.invalidateQueries({ queryKey: ["admin", "settings", "platform", "option_chain"] });
    } catch (e: any) {
      toast.error(e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  const symbols = [
    ...DEFAULT_LIST,
    ...Object.keys(entries)
      .filter((s) => !DEFAULT_LIST.includes(s))
      .sort(),
  ];

  return (
    <Card data-tour="exp-itm-otm">
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div className="space-y-1">
          <CardTitle>ITM / OTM strikes per instrument</CardTitle>
          <CardDescription>
            How many in-the-money and out-of-the-money strikes each instrument&apos;s option chain shows and
            lets users trade. Leave a box blank to use the segment&apos;s &quot;Strikes around ATM&quot;. Calls
            are ITM below the spot price and puts above it, so each side is applied the right way round.
          </CardDescription>
        </div>
        <Button onClick={save} disabled={!dirty} loading={saving}>
          Save ITM / OTM
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-semibold">Instrument</th>
                <th className="px-3 py-2 text-left font-semibold">Segment default</th>
                <th className="px-3 py-2 text-left font-semibold">ITM strikes</th>
                <th className="px-3 py-2 text-left font-semibold">OTM strikes</th>
                <th className="w-10 px-2 py-2" />
              </tr>
            </thead>
            <tbody>
              {symbols.map((s) => {
                const seg = segmentFor(s);
                const def = Number(segDefaults?.[seg.key]) || 15;
                const e = entries[s] ?? { itm: "", otm: "" };
                const custom = e.itm !== "" || e.otm !== "";
                return (
                  <tr key={s} className="border-t border-border/60">
                    <td className="px-3 py-1.5 font-semibold">{s}</td>
                    <td className="px-3 py-1.5 text-xs text-muted-foreground">
                      {seg.label} · ATM ±{def}
                    </td>
                    <td className="px-3 py-1.5">
                      <Input
                        inputMode="numeric"
                        className="h-8 w-24"
                        value={e.itm}
                        placeholder={String(def)}
                        onChange={(ev) => setField(s, "itm", ev.target.value)}
                        aria-label={`${s} ITM strikes`}
                      />
                    </td>
                    <td className="px-3 py-1.5">
                      <Input
                        inputMode="numeric"
                        className="h-8 w-24"
                        value={e.otm}
                        placeholder={String(def)}
                        onChange={(ev) => setField(s, "otm", ev.target.value)}
                        aria-label={`${s} OTM strikes`}
                      />
                    </td>
                    <td className="px-2 py-1.5">
                      {(custom || !DEFAULT_LIST.includes(s)) && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          onClick={() => removeSymbol(s)}
                          aria-label={`Reset ${s}`}
                          title={DEFAULT_LIST.includes(s) ? "Back to segment default" : "Remove"}
                        >
                          <Trash2 className="size-4 text-muted-foreground" />
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            className="h-9 w-56"
            value={newSymbol}
            onChange={(e) => setNewSymbol(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addSymbol();
              }
            }}
            placeholder="Add a stock, e.g. RELIANCE"
          />
          <Button type="button" variant="outline" size="sm" onClick={addSymbol}>
            <Plus className="size-4" /> Add instrument
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Example: NIFTY with ITM 5 and OTM 15 shows calls from 5 strikes below ATM to 15 above, and puts from 15
          below to 5 above. A strike that falls outside its range becomes close-only for users already holding it.
        </p>
      </CardContent>
    </Card>
  );
}
