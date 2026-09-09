"use client";

/**
 * Scrolling announcement lines shown across the top of the user home page.
 *
 * SUPER ADMIN only. Targeting is by ADMIN, not by user: "All admins" runs the
 * line for the whole book, otherwise it runs only for users sitting under the
 * admins picked here. The caller hides this card for anyone else — the
 * endpoint is gated too, so a sub-admin would only get a 403 to stare at.
 *
 * Each line saves and deletes on its own, so a half-typed row can't block the
 * others and a failed save loses one line's edit, not the whole set.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Megaphone, Plus, Save, Trash2 } from "lucide-react";
import {
  TickerAPI,
  type TickerAdminChoice,
  type TickerItem,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function TickerCard() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["admin", "ticker"],
    queryFn: () => TickerAPI.list(),
  });

  const createMut = useMutation({
    mutationFn: () =>
      TickerAPI.create({
        text: "New announcement",
        // Off by default so placeholder text never reaches a real user
        // between "Add line" and the first save.
        enabled: false,
        target_all: true,
        admin_ids: [],
        sort_order: (data?.items?.length ?? 0) + 1,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "ticker"] }),
    onError: (e: any) => toast.error(e?.message || "Could not add a line"),
  });

  const items = data?.items ?? [];
  const admins = data?.admins ?? [];

  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Megaphone className="size-5 text-primary" />
          Home-page ticker
        </CardTitle>
        <CardDescription>
          Scrolling announcement strip at the top of the user home page. Send a
          line to every admin&apos;s users, or pick admins one by one — a user
          sees it when one of the admins above them is selected. Enabled lines
          scroll one after another; with none enabled the strip disappears.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <p className="text-xs text-muted-foreground">Loading…</p>
        ) : items.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No lines yet. Add one — it starts switched off, so nothing reaches
            users until you enable it.
          </p>
        ) : (
          items.map((it) => <TickerRow key={it.id} item={it} admins={admins} />)
        )}

        <Button
          type="button"
          variant="outline"
          onClick={() => createMut.mutate()}
          loading={createMut.isPending}
        >
          <Plus className="size-4" />
          Add line
        </Button>
      </CardContent>
    </Card>
  );
}

function TickerRow({
  item,
  admins,
}: {
  item: TickerItem;
  admins: TickerAdminChoice[];
}) {
  const qc = useQueryClient();
  // Seeded once from the row we were handed. A background refetch replaces
  // the parent's data but not this state, so a half-typed line survives.
  const [text, setText] = useState(item.text);
  const [enabled, setEnabled] = useState(item.enabled);
  const [targetAll, setTargetAll] = useState(item.target_all);
  const [ids, setIds] = useState<string[]>(item.admin_ids ?? []);
  const [order, setOrder] = useState(String(item.sort_order));

  const payload = {
    text: text.trim(),
    enabled,
    target_all: targetAll,
    admin_ids: ids,
    sort_order: Number(order) || 0,
  };

  const saveMut = useMutation({
    mutationFn: () => TickerAPI.update(item.id, payload),
    onSuccess: () => {
      // Saying only "saved" is what made a switched-off line look broken:
      // the write succeeded, nothing appeared, and there was no clue why.
      if (enabled) toast.success("Ticker line is live");
      else toast.warning("Saved — but still OFF. Tick Enabled to show it.");
      qc.invalidateQueries({ queryKey: ["admin", "ticker"] });
    },
    onError: (e: any) => toast.error(e?.message || "Could not save the line"),
  });

  const delMut = useMutation({
    mutationFn: () => TickerAPI.remove(item.id),
    onSuccess: () => {
      toast.success("Ticker line removed");
      qc.invalidateQueries({ queryKey: ["admin", "ticker"] });
    },
    onError: (e: any) => toast.error(e?.message || "Could not delete the line"),
  });

  const sameIds =
    ids.slice().sort().join(",") ===
    (item.admin_ids ?? []).slice().sort().join(",");
  const dirty =
    payload.text !== item.text ||
    enabled !== item.enabled ||
    targetAll !== item.target_all ||
    payload.sort_order !== item.sort_order ||
    !sameIds;

  // A targeted line with nothing selected reaches nobody. Say so, rather than
  // letting it sit "enabled" and leaving the super admin to wonder why it
  // never showed up.
  const reachesNobody = enabled && !targetAll && ids.length === 0;

  const toggleId = (id: string) =>
    setIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );

  return (
    <div
      className={`space-y-2 rounded-md border p-3 ${
        enabled ? "border-primary/40 bg-primary/5" : "border-border bg-muted/10"
      }`}
    >
      {/* A saved-but-off line is the one failure mode with no symptom: the
          write succeeds and nothing appears on the user side. Say it loudly
          on the row itself, not just in the toast that already faded. */}
      {!enabled && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-600 dark:text-amber-400">
          <span className="font-semibold">This line is OFF.</span> Users
          don&apos;t see it. Tick <span className="font-semibold">Enabled</span>{" "}
          below, then Save.
        </div>
      )}

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        maxLength={500}
        placeholder="Announcement text"
        className="w-full rounded-md border border-border bg-muted/20 px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus:border-primary"
      />

      <div className="flex flex-wrap items-center gap-4 text-xs">
        <label
          className={`flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1 ${
            enabled
              ? "border-primary/50 bg-primary/10"
              : "border-amber-500/40 bg-amber-500/10"
          }`}
        >
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="size-4 accent-primary"
          />
          <span className="font-semibold">
            {enabled ? "Enabled · shows to users" : "Enabled"}
          </span>
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={targetAll}
            onChange={(e) => setTargetAll(e.target.checked)}
            className="size-4 accent-primary"
          />
          <span className="font-medium">All admins</span>
        </label>
        <label className="flex items-center gap-2 text-muted-foreground">
          Order
          <input
            type="number"
            value={order}
            onChange={(e) => setOrder(e.target.value)}
            className="h-7 w-16 rounded-md border border-border bg-muted/20 px-2 text-xs outline-none focus:border-primary"
          />
        </label>
      </div>

      {/* Hidden while "All admins" is on: the backend ignores the selection in
          that mode, and showing it would suggest the two combine. */}
      {!targetAll && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <span>
              Show to users under these admins ({ids.length} selected)
            </span>
            <button
              type="button"
              className="underline"
              onClick={() => setIds(admins.map((a) => a.id))}
            >
              select all
            </button>
            <button
              type="button"
              className="underline"
              onClick={() => setIds([])}
            >
              clear
            </button>
          </div>
          <div className="max-h-52 space-y-1 overflow-y-auto rounded-md border border-border bg-background p-2">
            {admins.length === 0 ? (
              <p className="text-[11px] text-muted-foreground">No admins yet.</p>
            ) : (
              admins.map((a) => (
                <label key={a.id} className="flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={ids.includes(a.id)}
                    onChange={() => toggleId(a.id)}
                    className="size-4 accent-primary"
                  />
                  <span className="flex-1 truncate">{a.name}</span>
                  <span className="text-[10px] text-muted-foreground">
                    {a.code ? `${a.code} · ` : ""}
                    {a.role}
                  </span>
                </label>
              ))
            )}
          </div>
        </div>
      )}

      {reachesNobody && (
        <p className="text-[11px] text-loss">
          Enabled but no admins selected — this line reaches nobody.
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          onClick={() => saveMut.mutate()}
          loading={saveMut.isPending}
          disabled={!dirty || !payload.text || saveMut.isPending}
        >
          <Save className="size-4" />
          Save
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => delMut.mutate()}
          loading={delMut.isPending}
        >
          <Trash2 className="size-4" />
          Delete
        </Button>
        {!dirty && (
          <span className="text-[11px] text-muted-foreground">
            {item.enabled
              ? item.target_all
                ? "Live · all admins"
                : `Live · ${item.admin_ids.length} admin(s)`
              : "Off · not shown"}
          </span>
        )}
      </div>
    </div>
  );
}
