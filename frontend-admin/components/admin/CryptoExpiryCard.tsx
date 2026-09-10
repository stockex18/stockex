"use client";

/**
 * Crypto option expiry — how long a contract runs, and when it settles.
 *
 * Two knobs, and the honest framing for the first one matters: Binance lists
 * the contracts and their dates are theirs, so nothing here invents an expiry.
 * The days setting caps which of the listed ones reach the platform at all.
 *
 * Super-admin only, and platform-wide — one settlement clock and one tenor
 * across every book, so it is not an admin-by-admin choice.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bitcoin, Save } from "lucide-react";
import { SettingsAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const DAYS_KEY = "crypto_expiry.max_days";
const TIME_KEY = "crypto_expiry.settle_time";
/** Binance settles at 08:00 UTC = 13:30 IST. Same default as the backend, so
 *  the card never shows something the sweep isn't actually using. */
const DEFAULT_TIME = "13:30";

export function CryptoExpiryCard() {
  const qc = useQueryClient();
  const { data, isFetching } = useQuery({
    queryKey: ["admin", "settings", "crypto_expiry"],
    queryFn: () => SettingsAPI.platformList("crypto_expiry"),
  });

  const [days, setDays] = useState("");
  const [time, setTime] = useState(DEFAULT_TIME);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (!data || hydrated) return;
    const byKey: Record<string, any> = {};
    for (const row of data as any[]) byKey[row.setting_key] = row.setting_value;
    const d = Number(byKey[DAYS_KEY] ?? 0);
    setDays(d > 0 ? String(d) : "");
    setTime(String(byKey[TIME_KEY] ?? DEFAULT_TIME));
    setHydrated(true);
  }, [data, hydrated]);

  const save = useMutation({
    mutationFn: async () => {
      const n = Number(days);
      await SettingsAPI.platformSet(DAYS_KEY, Number.isFinite(n) && n > 0 ? n : 0);
      await SettingsAPI.platformSet(TIME_KEY, time.trim() || DEFAULT_TIME);
    },
    onSuccess: () => {
      toast.success("Crypto expiry settings saved");
      qc.invalidateQueries({ queryKey: ["admin", "settings", "crypto_expiry"] });
    },
    onError: (e: any) => toast.error(e?.message || "Could not save"),
  });

  const dayNum = Number(days);
  const validTime = /^\d{1,2}:\d{2}$/.test(time.trim());
  const validDays = days.trim() === "" || (Number.isFinite(dayNum) && dayNum >= 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bitcoin className="size-5 text-primary" />
          Crypto option expiry
        </CardTitle>
        <CardDescription>
          How far out a crypto option may run, and when an expiring contract
          closes. Platform-wide — one clock for every book.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Expiry runs for (days)
            </label>
            <Input
              type="number"
              min={0}
              value={days}
              onChange={(e) => setDays(e.target.value)}
              placeholder="No limit"
              disabled={isFetching && !hydrated}
            />
            <p className="text-[10px] leading-relaxed text-muted-foreground">
              Binance lists the contracts and the dates are theirs, so this
              can&apos;t create an expiry — it hides the longer-dated ones.
              Blank or 0 lists every expiry, as now.
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Settles at (IST)
            </label>
            <Input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              disabled={isFetching && !hydrated}
            />
            <p className="text-[10px] leading-relaxed text-muted-foreground">
              On the expiry date, any position still open on that contract
              closes at its LTP. Default {DEFAULT_TIME} — Binance&apos;s own
              08:00 UTC settlement.
            </p>
          </div>
        </div>

        <div className="rounded-md border border-border bg-muted/10 px-3 py-2 text-xs">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
            What happens
          </div>
          <div className="mt-1 text-foreground">
            {dayNum > 0 ? (
              <>
                Only expiries within{" "}
                <span className="font-semibold">{dayNum} day{dayNum === 1 ? "" : "s"}</span>{" "}
                are listed
              </>
            ) : (
              <>Every listed expiry is available</>
            )}
            {" · open positions close at "}
            <span className="font-semibold">{validTime ? time : DEFAULT_TIME} IST</span>
            {" on expiry day, at LTP"}
          </div>
          <div className="mt-0.5 text-[10px] text-muted-foreground">
            No live LTP at that moment falls back to intrinsic value — settling
            an expired option at a stale premium would pay out on a contract
            that expired worthless.
          </div>
        </div>

        <Button
          type="button"
          onClick={() => save.mutate()}
          loading={save.isPending}
          disabled={!validDays || !validTime || save.isPending}
        >
          <Save className="size-4" />
          Save
        </Button>
      </CardContent>
    </Card>
  );
}
