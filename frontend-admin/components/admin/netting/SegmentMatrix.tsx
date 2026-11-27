"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Save, ShieldAlert, Trash2 } from "lucide-react";
import { InstrumentAdminAPI, NettingAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { CATEGORY_FIELDS, isFieldNA, PREMIUM_ROWS, type SegmentRow } from "@/lib/nettingMatrixConfig";

const PREMIUM_ROW_LIST = Array.from(PREMIUM_ROWS);
import { Cell } from "./Cell";
import { useAdminAuthStore } from "@/stores/authStore";
import { canEdit } from "@/lib/permissions";

export function SegmentMatrix({ categoryId, subAdminId, brokerId }: { categoryId: string; subAdminId?: string; brokerId?: string }) {
  const qc = useQueryClient();
  const me = useAdminAuthStore((s) => s.admin);
  // Per-node key: a specific admin (subAdminId) or a specific broker (brokerId).
  const nodeKey = subAdminId ?? (brokerId ? `broker:${brokerId}` : "self");
  // subAdminId → super-admin only. brokerId → any in-scope parent (admin/broker/
  // SA); the backend enforces the parent↔child scope. Else the per-role gate.
  const canMutate = subAdminId
    ? me?.role === "SUPER_ADMIN"
    : brokerId
      ? canEdit(me, "segment_settings") || me?.role === "SUPER_ADMIN"
      : canEdit(me, "segment_settings");
  const fields = CATEGORY_FIELDS[categoryId] || [];
  const { data: segments, isLoading } = useQuery({
    queryKey: ["admin", "netting", "segments", nodeKey],
    queryFn: () =>
      subAdminId
        ? NettingAPI.segmentsForSubAdmin(subAdminId)
        : brokerId
          ? NettingAPI.segmentsForBroker(brokerId)
          : NettingAPI.segments(),
  });

  const [edits, setEdits] = useState<Record<string, Record<string, any>>>({});
  const [saving, setSaving] = useState(false);
  const [notAllowed, setNotAllowed] = useState<string | null>(null);

  // ── Premium tab: instrument-wise rows (super admin; platform or one admin) ──
  const showRules = categoryId === "premium" && !brokerId && me?.role === "SUPER_ADMIN";
  const rulesKey = ["admin", "netting", "premium-rules", subAdminId ?? "platform"];
  const { data: savedRules } = useQuery({
    queryKey: rulesKey,
    queryFn: () => NettingAPI.premiumRules(subAdminId),
    enabled: showRules,
  });
  const [rules, setRules] = useState<any[] | null>(null); // null = untouched
  const shownRules: any[] = rules ?? savedRules ?? [];
  const rulesDirty = rules !== null;
  const { data: symbolOptions } = useQuery({
    queryKey: ["admin", "premium-symbols"],
    enabled: showRules,
    staleTime: 10 * 60_000,
    queryFn: async () => {
      const out: Record<string, string[]> = {};
      for (const seg of PREMIUM_ROW_LIST) {
        const res = await InstrumentAdminAPI.list({ netting_segment: seg, page_size: 500 });
        out[seg] = Array.from(new Set((res?.items ?? []).map((r: any) => r.symbol).filter(Boolean)));
      }
      return out;
    },
  });
  function addRule(segName: string) {
    setRules([
      ...shownRules,
      { segment_name: segName, symbol: "", premiumType: "percentage", premiumCharge: 0, premiumOn: "both", premiumTime: "22:30" },
    ]);
  }
  function setRule(i: number, key: string, val: any) {
    setRules(shownRules.map((r, j) => (j === i ? { ...r, [key]: val } : r)));
  }
  function removeRule(i: number) {
    setRules(shownRules.filter((_, j) => j !== i));
  }

  function setEdit(segId: string, key: string, val: any) {
    setEdits((prev) => ({ ...prev, [segId]: { ...(prev[segId] || {}), [key]: val } }));
  }
  function getValue(seg: any, key: string) {
    if (edits[seg.id]?.[key] !== undefined) return edits[seg.id][key];
    return seg[key];
  }

  // LOT category only: split EVERY option segment (NSE stock/index option, BSE
  // option, MCX option, crypto option — anything with optionApplies) into Buy +
  // Sell rows, each editing the per-side lot fields (optionBuyMinLots /
  // optionSellMinLots …). Every non-option segment/category stays one row
  // editing the field directly. The backend resolver already applies
  // optionBuy*/optionSell* per option order for ANY option segment (it keys off
  // the order's CE/PE + BUY/SELL, not the segment name), so once the admin sets
  // a per-side value here it is enforced live. Unset per-side fields fall back
  // to the segment-wide lot, so existing single-row values keep applying.
  function keyFor(sub: string | null, key: string) {
    return sub ? `${sub}${key[0].toUpperCase()}${key.slice(1)}` : key;
  }
  function expand(seg: any): Array<{ label: string; sub: string | null }> {
    if (categoryId === "lot" && seg.optionApplies) {
      return [
        { label: `${seg.displayName} · Buy`, sub: "optionBuy" },
        { label: `${seg.displayName} · Sell`, sub: "optionSell" },
      ];
    }
    return [{ label: seg.displayName, sub: null }];
  }

  // Self-heal stored select values that are no longer a valid option
  // (legacy enum like `marginCalcMode: "percent"` after we retired that
  // mode). Stage a dirty edit so the next Save normalises the row to a
  // current option.
  //
  // Critically: do NOT stage for null/undefined values. The backend
  // resolver has a defensive inference path (sniff intradayMargin > 100
  // → Times, else Fixed) that handles unset rows correctly. If we
  // pre-stage "fixed" here, an admin who edits `intradayMargin` from
  // default 100 → 700 expecting Times leverage will silently get
  // "Fixed · 🪙100/lot" because Save commits both the staged
  // "marginCalcMode=fixed" AND keeps intradayMargin at 100 (the change
  // they thought they made never got typed in). Leave null alone — the
  // admin's explicit dropdown click is the only way to commit a mode.
  useEffect(() => {
    if (!segments || !fields.length) return;
    setEdits((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const seg of segments as any[]) {
        for (const f of fields) {
          if (f.type !== "select") continue;
          const stored = seg[f.key];
          // Leave unset values alone — backend resolver infers.
          if (stored === null || stored === undefined || stored === "") continue;
          const valid = (f.options ?? []).some((o: any) => String(o.v) === String(stored));
          if (valid) continue;
          const fallback = f.options?.[0]?.v;
          if (fallback === undefined) continue;
          if (next[seg.id]?.[f.key] === fallback) continue;
          next[seg.id] = { ...(next[seg.id] || {}), [f.key]: fallback };
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    // intentional: rerun whenever the data refetches or the category changes
  }, [segments, fields]);

  const dirtyCount =
    Object.values(edits).reduce((s, e) => s + Object.keys(e).length, 0) + (rulesDirty ? 1 : 0);

  async function saveAll() {
    setSaving(true);
    if (rulesDirty) {
      try {
        await NettingAPI.savePremiumRules(shownRules, subAdminId);
        setRules(null);
        await qc.refetchQueries({ queryKey: rulesKey });
        if (Object.keys(edits).length === 0) toast.success("Instrument premiums saved");
      } catch (e: any) {
        toast.error(e?.message || "Instrument premiums didn't save");
        setSaving(false);
        return;
      }
    }
    if (Object.keys(edits).length === 0) {
      setSaving(false);
      return;
    }
    const ids = Object.keys(edits);
    // Parallelise the PUTs, but with allSettled so ONE segment's failure never
    // discards the whole batch (the old Promise.all rejected on the first
    // failure → every save silently "reverted" in the UI even though most had
    // persisted — the "segment setting save nahi ho raha" report).
    const results = await Promise.allSettled(
      ids.map((id) =>
        subAdminId
          ? NettingAPI.updateSegmentForSubAdmin(subAdminId, id, edits[id])
          : brokerId
            ? NettingAPI.updateSegmentForBroker(brokerId, id, edits[id])
            : NettingAPI.updateSegment(id, edits[id]),
      ),
    );
    // ALWAYS force-refetch so the grid reflects exactly what the server stored.
    // Values may have been CLAMPED to the parent ceiling/floor (limits ≤ parent,
    // brokerage ≥ parent), so this is also what makes the clamp visible.
    try {
      await qc.refetchQueries({ queryKey: ["admin", "netting", "segments", nodeKey] });
    } catch {
      /* ignore refetch hiccup */
    }
    qc.invalidateQueries({ queryKey: ["segment-settings"] });

    const failedIdx = results
      .map((r, i) => ({ r, id: ids[i] }))
      .filter((x) => x.r.status === "rejected");
    if (failedIdx.length === 0) {
      toast.success(`Saved ${dirtyCount} change${dirtyCount === 1 ? "" : "s"}`);
      setEdits({});
    } else {
      // Keep ONLY the edits that failed so the operator can retry just those;
      // succeeded ones are cleared (their values now come from the refetch).
      const failedIds = new Set(failedIdx.map((f) => f.id));
      setEdits((prev) =>
        Object.fromEntries(Object.entries(prev).filter(([k]) => failedIds.has(k))),
      );
      const firstErr = (failedIdx[0].r as PromiseRejectedResult).reason;
      const msg = firstErr?.message || "error";
      // A super-admin limit violation comes back as "Not allowed — …". Surface
      // it as a blocking popup (not a fleeting toast) so the admin clearly sees
      // their change was rejected and why.
      if (/not allowed/i.test(msg)) {
        setNotAllowed(msg);
      } else {
        toast.error(`${failedIdx.length} of ${ids.length} didn't save: ${msg}`);
      }
    }
    setSaving(false);
  }

  if (isLoading) return <div className="text-sm text-muted-foreground">Loading segments…</div>;

  return (
    <div className="space-y-3">
      {/* Blocking "not allowed" popup — shown when a save is rejected for
          exceeding the super-admin's segment limits. */}
      <Dialog open={!!notAllowed} onOpenChange={(v) => !v && setNotAllowed(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldAlert className="size-5 text-destructive" /> Not allowed
            </DialogTitle>
            <DialogDescription className="space-y-2 pt-1">
              <span className="block">
                Your super-admin has set limits for these settings — your change goes past them, so it wasn&apos;t saved.
              </span>
              <span className="block rounded-lg border border-border bg-muted/30 p-2.5 text-[13px] leading-relaxed text-foreground">
                {(notAllowed || "").replace(/^Not allowed — /i, "")}
              </span>
              <span className="block text-[12px]">Adjust the value within the allowed limit and save again.</span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button onClick={() => setNotAllowed(null)}>Got it</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <div className="flex items-center justify-end">
        <Button
          onClick={saveAll}
          disabled={dirtyCount === 0 || !canMutate}
          title={canMutate ? undefined : "View-only access"}
          loading={saving}
        >
          <Save className="size-4" /> Save {dirtyCount > 0 ? `(${dirtyCount})` : ""}
        </Button>
      </div>
      {/* ── Mobile: card per segment ─────────────────────────────── */}
      <div className="md:hidden space-y-2">
        {(segments ?? []).flatMap((seg: any) => {
          const segRow: SegmentRow = {
            code: seg.name,
            name: seg.displayName,
            lotApplies: seg.lotApplies,
            qtyApplies: seg.qtyApplies,
            optionApplies: seg.optionApplies,
            expiryHoldApplies: seg.expiryHoldApplies,
            futureApplies: seg.futureApplies,
          };
          const activeFields = fields.filter((f) => !isFieldNA(segRow, categoryId, f));
          if (activeFields.length === 0) return [];
          return expand(seg).map((row) => {
            const rowId = seg.id + (row.sub ?? "");
            return (
              <div key={rowId} className="rounded-lg border border-border bg-card">
                {/* Segment header */}
                <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
                  <div className="size-7 rounded-md bg-muted flex items-center justify-center text-[10px] font-bold text-muted-foreground shrink-0">
                    {seg.displayName.slice(0, 2)}
                  </div>
                  <div>
                    <div className="text-xs font-semibold">{row.label}</div>
                    <div className="text-[10px] font-mono text-muted-foreground">{seg.name}</div>
                  </div>
                </div>
                {/* Fields grid */}
                <div className="grid grid-cols-2 gap-x-3 gap-y-3 p-3">
                  {activeFields.map((f) => {
                    const k = keyFor(row.sub, f.key);
                    return (
                      <div key={f.key} className="space-y-1">
                        <Label className="text-[10px] text-muted-foreground leading-none">{f.label}</Label>
                        <Cell
                          field={f}
                          na={false}
                          value={getValue(seg, k)}
                          dirty={edits[seg.id]?.[k] !== undefined}
                          onChange={(v) => setEdit(seg.id, k, v)}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          });
        })}
      </div>

      {/* ── Desktop: horizontal scroll table ─────────────────────── */}
      <div className="hidden md:block overflow-x-auto rounded-lg border border-border bg-card">
        <table className="min-w-full text-xs">
          <thead className="bg-card">
            <tr className="border-b border-border">
              <th className="sticky left-0 z-10 bg-card px-3 py-2 text-left text-muted-foreground">
                Segment
              </th>
              {showRules && (
                <th className="whitespace-nowrap px-2 py-2 text-left text-muted-foreground">Instrument</th>
              )}
              {fields.map((f) => (
                <th key={f.key} className="whitespace-nowrap px-2 py-2 text-left text-muted-foreground">
                  {f.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {(segments ?? []).flatMap((seg: any) => {
              const segRow: SegmentRow = {
                code: seg.name,
                name: seg.displayName,
                lotApplies: seg.lotApplies,
                qtyApplies: seg.qtyApplies,
                optionApplies: seg.optionApplies,
                expiryHoldApplies: seg.expiryHoldApplies,
                futureApplies: seg.futureApplies,
              };
              // Premium only applies to crypto rows — leave the rest out.
              if (categoryId === "premium" && fields.every((f) => isFieldNA(segRow, categoryId, f))) return [];
              const segRows = expand(seg).map((row) => {
                const rowId = seg.id + (row.sub ?? "");
                return (
                  <tr key={rowId} className="hover:bg-muted/30">
                    <td className="sticky left-0 z-0 whitespace-nowrap bg-card px-3 py-2">
                      <div className="font-medium">{row.label}</div>
                      <div className="text-[10px] font-mono text-muted-foreground">{seg.name}</div>
                    </td>
                    {showRules && (
                      <td className="whitespace-nowrap px-2 py-1">
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] text-muted-foreground">All instruments</span>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-[11px]"
                            disabled={!canMutate}
                            onClick={() => addRule(seg.name)}
                          >
                            <Plus className="size-3" /> Add instrument
                          </Button>
                        </div>
                      </td>
                    )}
                    {fields.map((f) => {
                      const k = keyFor(row.sub, f.key);
                      return (
                        <td key={f.key} className="px-1 py-1">
                          <Cell
                            field={f}
                            na={isFieldNA(segRow, categoryId, f)}
                            value={getValue(seg, k)}
                            dirty={edits[seg.id]?.[k] !== undefined}
                            onChange={(v) => setEdit(seg.id, k, v)}
                          />
                        </td>
                      );
                    })}
                  </tr>
                );
              });
              if (!showRules) return segRows;
              // This segment's instrument-wise rows: each prices ONE instrument
              // on its own, ahead of the segment's "All instruments" value.
              const listId = `premium-symbols-${seg.name}`;
              const ruleRows = shownRules
                .map((r, i) => ({ r, i }))
                .filter(({ r }) => r.segment_name === seg.name)
                .map(({ r, i }) => (
                  <tr key={`${seg.id}-rule-${i}`} className="bg-muted/10 hover:bg-muted/30">
                    <td className="sticky left-0 z-0 whitespace-nowrap bg-card px-3 py-2 text-right text-[10px] text-muted-foreground">
                      ↳
                    </td>
                    <td className="px-1 py-1">
                      <div className="flex items-center gap-1">
                        <input
                          list={listId}
                          value={r.symbol}
                          placeholder="Instrument, e.g. BTCUSD"
                          disabled={!canMutate}
                          onChange={(e) => setRule(i, "symbol", e.target.value.toUpperCase())}
                          className="h-8 w-44 rounded-md border border-primary/40 bg-background px-2 text-xs uppercase outline-none focus:border-primary"
                        />
                        <button
                          type="button"
                          title="Remove this instrument"
                          disabled={!canMutate}
                          onClick={() => removeRule(i)}
                          className="rounded p-1 text-muted-foreground hover:text-destructive"
                        >
                          <Trash2 className="size-3.5" />
                        </button>
                      </div>
                    </td>
                    {fields.map((f) => (
                      <td key={f.key} className="px-1 py-1">
                        <Cell field={f} na={false} value={r[f.key]} dirty onChange={(v) => setRule(i, f.key, v)} />
                      </td>
                    ))}
                  </tr>
                ));
              return [
                ...segRows,
                ...ruleRows,
                <tr key={`${seg.id}-list`} className="hidden">
                  <td>
                    <datalist id={listId}>
                      {(symbolOptions?.[seg.name] ?? []).map((sym) => (
                        <option key={sym} value={sym} />
                      ))}
                    </datalist>
                  </td>
                </tr>,
              ];
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
