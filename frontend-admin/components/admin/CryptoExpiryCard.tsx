"use client";

/**
 * Crypto option expiry — how many expiries to list, and when they settle.
 *
 * The framing on the first knob matters: Binance lists the contracts and their
 * dates are theirs, so nothing here invents an expiry. It picks how many of
 * the listed ones reach the platform, nearest first — a COUNT, not days,
 * because once today's contract settles Binance drops it and the nearest
 * expiry becomes tomorrow's.
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

const COUNT_KEY = "crypto_expiry.max_expiries";
/** The name this shipped under first — read so a value saved before the
 *  rename still shows in the box. Same number, same intent. */
const LEGACY_DAYS_KEY = "crypto_expiry.max_days";
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
    const d = Number(byKey[COUNT_KEY] ?? byKey[LEGACY_DAYS_KEY] ?? 0);
    setDays(d > 0 ? String(d) : "");
    setTime(String(byKey[TIME_KEY] ?? DEFAULT_TIME));
    setHydrated(true);
  }, [data, hydrated]);

  const save = useMutation({
    mutationFn: async () => {
      const n = Number(days);
      await SettingsAPI.platformSet(COUNT_KEY, Number.isFinite(n) && n > 0 ? n : 0);
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
          How many expiries the chain shows, and when an expiring contract
          closes. Platform-wide — one clock for every book.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Show expiries (count)
            </label>
            <Input
              type="number"
              min={0}
              value={days}
              onChange={(e) => setDays(e.target.value)}
              placeholder="Platform default"
              disabled={isFetching && !hydrated}
            />
            <p className="text-[10px] leading-relaxed text-muted-foreground">
              Nearest first, the same count as the NSE / BSE / MCX boxes above.
              1 = the nearest expiry only. A count and not days on purpose:
              once today&apos;s contract settles Binance drops it, so the
              nearest becomes tomorrow&apos;s. Blank or 0 uses the default.
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
                The{" "}
                <span className="font-semibold">
                  nearest {dayNum} expir{dayNum === 1 ? "y" : "ies"}
                </span>{" "}
                {dayNum === 1 ? "is" : "are"} listed
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
