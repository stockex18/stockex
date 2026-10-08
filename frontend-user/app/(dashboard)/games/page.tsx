"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { PiArrowRightBold, PiArrowsSplitBold, PiHashBold, PiTrendUpBold, PiTrophyFill } from "react-icons/pi";
import { cn } from "@/lib/utils";
import { SymbolAvatar } from "@/components/common/SymbolAvatar";
import { GamesAPI } from "@/lib/api";
import { ALL_GAME_IDS, GAME_META, SETTINGS_KEY, type Mechanic } from "@/lib/games/ids";
import { useGamesSettings, useGamesPrice } from "@/components/games/useGames";
import { LivePriceTag, LiveDot } from "@/components/games/bits";

const MECHANIC_ICON: Record<Mechanic, any> = {
  updown: PiTrendUpBold,
  number: PiHashBold,
  bracket: PiArrowsSplitBold,
  jackpot: PiTrophyFill,
};

const GROUPS: { title: string; sub: string; mechanic: Mechanic }[] = [
  { title: "Up / Down", sub: "Predict the next 15-min move", mechanic: "updown" },
  { title: "Number", sub: "Guess the last two digits", mechanic: "number" },
  { title: "Bracket", sub: "Buy or sell the price band", mechanic: "bracket" },
  { title: "Jackpot", sub: "Predict the price, top the pool", mechanic: "jackpot" },
];

export default function GamesLobby() {
  const { data: settings, isLoading } = useGamesSettings();
  const { data: price } = useGamesPrice();
  const { data: activity } = useQuery({
    queryKey: ["games", "activity"],
    queryFn: () => GamesAPI.liveActivity(),
    refetchInterval: 10000,
  });

  const games = settings?.games || {};
  const nifty = price?.nifty ? Number(price.nifty) : null;
  const btc = price?.btc ? Number(price.btc) : null;
  const feedLive = !!(nifty || btc);

  return (
    <div className="space-y-6">
      {/* Live-price strip */}
      <div className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="grid grid-cols-2 gap-2 sm:flex sm:items-center">
          <LivePriceTag asset="NIFTY" value={nifty} className="min-w-0 sm:min-w-[140px]" />
          <LivePriceTag asset="BTC" value={btc} className="min-w-0 sm:min-w-[160px]" />
        </div>
        <LiveDot live={feedLive} label={feedLive ? "Live market feed" : "Waiting for feed…"} />
      </div>

      {isLoading ? (
        <LobbySkeleton />
      ) : (
        GROUPS.map((g) => {
          const ids = ALL_GAME_IDS.filter((id) => GAME_META[id].mechanic === g.mechanic);
          const Icon = MECHANIC_ICON[g.mechanic];
          return (
            <section key={g.mechanic}>
              <div className="mb-2.5">
                <h2 className="flex items-center gap-2 text-[15px] font-extrabold uppercase tracking-wide">
                  <Icon className="size-4 text-primary" /> {g.title}
                </h2>
                <p className="mt-0.5 text-[11px] font-semibold text-muted-foreground">{g.sub}</p>
              </div>
              {/* 2 small boxes per row on phone, 3 on desktop */}
              <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-3">
                {ids.map((id) => {
                  const meta = GAME_META[id];
                  const cfg = games[SETTINGS_KEY[id]];
                  const enabled = cfg ? cfg.enabled !== false : true;
                  const tickets = activity?.[SETTINGS_KEY[id]]?.tickets ?? 0;
                  const isBtc = meta.asset === "BTC";
                  return (
                    <GameCard
                      key={id}
                      id={id}
                      title={meta.title}
                      blurb={meta.blurb}
                      asset={meta.asset}
                      isBtc={isBtc}
                      isNumber={g.mechanic === "number"}
                      enabled={enabled}
                      tickets={tickets}
                    />
                  );
                })}
              </div>
            </section>
          );
        })
      )}
    </div>
  );
}

function GameCard({
  id, title, blurb, asset, isBtc, isNumber, enabled, tickets,
}: {
  id: string; title: string; blurb: string; asset: string; isBtc: boolean; isNumber: boolean; enabled: boolean; tickets: number;
}) {
  const body = (
    <>
      <span
        aria-hidden
        className={cn(
          "pointer-events-none absolute -right-6 -top-6 size-20 rounded-full blur-2xl transition-opacity",
          "bg-primary/20",
          enabled ? "opacity-100" : "opacity-30",
        )}
      />
      <div className="flex items-center justify-between gap-1">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 py-0.5 pl-0.5 pr-2 text-[10px] font-extrabold uppercase tracking-wider text-primary">
          <SymbolAvatar symbol={isBtc ? "BTCUSD" : "NIFTY"} className="size-4 text-[7px]" />
          {asset}
        </span>
        {isNumber && (
          <span className="rounded-md bg-primary/15 px-1.5 py-0.5 font-tabular text-[11px] font-extrabold text-primary">123</span>
        )}
        {enabled ? (
          <span className="inline-flex items-center gap-1 text-[10px] font-medium text-muted-foreground">
            <span className={cn("size-1.5 rounded-full", tickets > 0 ? "bg-buy animate-pulse" : "bg-muted-foreground/40")} />
            {tickets}
          </span>
        ) : (
          <span className="text-[10px] font-semibold text-muted-foreground">Off</span>
        )}
      </div>

      <div className="mt-2 flex-1">
        <div className="text-[15px] font-extrabold leading-tight tracking-tight">{title}</div>
        <div className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-muted-foreground">{blurb}</div>
      </div>

      {enabled ? (
        <div
          className={cn(
            "mt-3 flex h-10 items-center justify-center gap-1.5 rounded-xl bg-gradient-to-b from-yellow-300 to-amber-500 text-sm font-extrabold text-neutral-900 shadow-md shadow-amber-500/25 transition-transform group-hover:scale-[1.02] group-active:scale-100",
          )}
        >
          Play Now <PiArrowRightBold className="size-3.5" />
        </div>
      ) : (
        <div className="mt-3 flex h-10 items-center justify-center rounded-xl border border-border text-sm font-semibold text-muted-foreground">
          Disabled
        </div>
      )}
    </>
  );

  const cls = cn(
    "group relative flex flex-col overflow-hidden rounded-2xl border border-border bg-card p-3.5 transition-all",
    enabled ? "hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-lg hover:shadow-primary/5" : "cursor-not-allowed opacity-60",
  );

  return enabled ? (
    <Link href={`/games/${id}`} className={cls}>{body}</Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

function LobbySkeleton() {
  return (
    <div className="space-y-6">
      {[0, 1].map((s) => (
        <section key={s}>
          <div className="mb-2.5 h-4 w-24 animate-pulse rounded bg-muted" />
          <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-3">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex flex-col gap-2 rounded-2xl border border-border bg-card p-3.5">
                <div className="flex justify-between">
                  <div className="h-4 w-10 animate-pulse rounded bg-muted" />
                  <div className="h-4 w-6 animate-pulse rounded bg-muted" />
                </div>
                <div className="mt-2 h-4 w-4/5 animate-pulse rounded bg-muted" />
                <div className="h-3 w-full animate-pulse rounded bg-muted" />
                <div className="mt-3 h-10 w-full animate-pulse rounded-xl bg-muted" />
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
