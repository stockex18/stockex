"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, MapPin, Check, Building2, Hash, Users } from "lucide-react";
import { PiGenderFemaleBold, PiGenderMaleBold } from "react-icons/pi";
import { BrokerSearchAPI, type BrokerOption, type BrokerSearchMode, type ClientGender } from "@/lib/api";
import { brokerTitle, cn } from "@/lib/utils";

/** The three ways a client looks for their broker — inside the list their
 *  gender allows (the old "Female" tab is now the signup's gender question).
 *
 *  One combined box was not enough. A client who knows their PIN wants the
 *  brokers near them, and typing six digits into a box that also matches
 *  `user_code` hands them a stranger whose code happens to contain those
 *  digits. A client who knows neither still has to be able to browse, which
 *  is what "All" is for — it lists everyone rather than demanding a query.
 *
 *  Operator: "pin code wise and city wise broker search kar paye... aur all
 *  users ka option bhi mile."
 */
const MODES: { key: BrokerSearchMode; label: string; Icon: React.ElementType; placeholder: string }[] = [
  { key: "all", label: "All", Icon: Users, placeholder: "Search by brand, name, code, city or PIN…" },
  { key: "city", label: "City", Icon: MapPin, placeholder: "Enter your city — e.g. Mumbai" },
  { key: "pincode", label: "PIN", Icon: Hash, placeholder: "Enter your PIN — e.g. 400001" },
];

/** Pink for the female list, sky for the male one. Not `primary`: on the
 *  signup page that is near-black ink, which vanishes in dark mode. */
export const GENDER_TONE = {
  FEMALE: {
    bar: "border-pink-300 bg-pink-50 dark:border-pink-500/40 dark:bg-pink-500/10",
    tab: "bg-pink-500 text-white shadow-sm shadow-pink-500/30",
    input: "border-pink-300 focus:border-pink-500 dark:border-pink-500/40",
    list: "border-pink-200 bg-pink-50/60 dark:border-pink-500/30 dark:bg-pink-500/[0.06]",
    text: "text-pink-600 dark:text-pink-400",
    icon: "text-pink-500",
    picked: "border-pink-500 bg-pink-500/10",
    hover: "border-transparent hover:bg-pink-500/10",
  },
  MALE: {
    bar: "border-sky-300 bg-sky-50 dark:border-sky-500/40 dark:bg-sky-500/10",
    tab: "bg-sky-500 text-white shadow-sm shadow-sky-500/30",
    input: "border-sky-300 focus:border-sky-500 dark:border-sky-500/40",
    list: "border-sky-200 bg-sky-50/60 dark:border-sky-500/30 dark:bg-sky-500/[0.06]",
    text: "text-sky-600 dark:text-sky-400",
    icon: "text-sky-500",
    picked: "border-sky-500 bg-sky-500/10",
    hover: "border-transparent hover:bg-sky-500/10",
  },
} as const;

/**
 * Searchable broker directory (used at signup + in the profile broker-switch).
 * Debounced search → public `GET /user/auth/brokers`. Mobile-first.
 */
export function BrokerPicker({
  value,
  onSelect,
  gender,
}: {
  value?: string | null;
  onSelect: (b: BrokerOption) => void;
  /** The client's. FEMALE → female brokers only (pink); MALE → may switch
   *  between male (sky) and female (pink) brokers. Null for clients from
   *  before signup asked: everyone, as before. */
  gender?: ClientGender | null;
}) {
  const [mode, setMode] = useState<BrokerSearchMode>("all");
  // Which list a male client is looking at. A female client has no choice.
  const [maleView, setMaleView] = useState<ClientGender>("MALE");
  const list: ClientGender | null = gender === "FEMALE" ? "FEMALE" : gender === "MALE" ? maleView : null;
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 200);
    return () => clearTimeout(t);
  }, [q]);

  const active = MODES.find((m) => m.key === mode) ?? MODES[0];
  const pink = list === "FEMALE";
  const tone = list ? GENDER_TONE[list] : null;

  const { data, isLoading } = useQuery({
    queryKey: ["broker-search", mode, debounced, list],
    queryFn: () => BrokerSearchAPI.search(debounced, 30, mode, list),
    staleTime: 30_000,
  });
  const brokers = data || [];
  // Real matches first, always. Nearby ones are a fallback with their own heading,
  // so a client can tell "broker in my city" from "closest broker to my city".
  const exactRows = brokers.filter((b) => !b.nearby);
  const nearRows = brokers.filter((b) => b.nearby);
  const where =
    mode === "pincode" ? `PIN ${debounced}` : nearRows[0]?.near || `"${debounced}"`;

  return (
    <div className="space-y-2">
      {gender === "MALE" && (
        <div className="grid grid-cols-2 gap-2">
          {(["MALE", "FEMALE"] as const).map((g) => {
            const on = maleView === g;
            const f = g === "FEMALE";
            const Icon = f ? PiGenderFemaleBold : PiGenderMaleBold;
            return (
              <button
                key={g}
                type="button"
                aria-pressed={on}
                onClick={() => setMaleView(g)}
                className={cn(
                  "flex items-center justify-center gap-1.5 rounded-xl border-2 px-2 py-2 text-xs font-bold transition-colors",
                  on
                    ? f
                      ? "border-pink-500 bg-pink-500 text-white shadow-sm shadow-pink-500/30"
                      : "border-sky-500 bg-sky-500 text-white shadow-sm shadow-sky-500/30"
                    : f
                      ? "border-pink-300 text-pink-600 hover:bg-pink-500/10 dark:border-pink-500/40 dark:text-pink-400"
                      : "border-sky-300 text-sky-600 hover:bg-sky-500/10 dark:border-sky-500/40 dark:text-sky-400",
                )}
              >
                <Icon className="size-4" />
                {f ? "Female brokers" : "Male brokers"}
              </button>
            );
          })}
        </div>
      )}
      {/* Mode first, then the box — the label on the box changes with the
          mode, so picking the mode is the step that comes first. */}
      <div className={cn("flex gap-1 rounded-xl border p-1 transition-colors", tone?.bar ?? "border-border bg-muted/30")}>
        {MODES.map(({ key, label, Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => {
              setMode(key);
              // A city typed under "City" means nothing under "PIN code", and
              // leaving it behind shows an empty list that looks like a bug.
              setQ("");
              setDebounced("");
            }}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-semibold transition-colors",
              mode === key
                ? tone?.tab ?? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-3.5" />
            {label}
          </button>
        ))}
      </div>

      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <input
          value={q}
          onChange={(e) =>
            // A PIN is digits. Letting letters through only produces an empty
            // list, so the field refuses them rather than explaining later.
            setQ(mode === "pincode" ? e.target.value.replace(/\D/g, "").slice(0, 6) : e.target.value)
          }
          inputMode={mode === "pincode" ? "numeric" : "text"}
          placeholder={active.placeholder}
          className={cn(
            "h-11 w-full rounded-xl border bg-background pl-9 pr-3 text-sm outline-none transition-colors",
            tone?.input ?? "border-border focus:border-primary",
          )}
        />
      </div>

      <div
        className={cn(
          "max-h-64 space-y-1.5 overflow-y-auto overscroll-contain rounded-xl border p-1.5",
          tone?.list ?? "border-border/60 bg-card/40",
        )}
      >
        {tone && (
          <div className={cn("flex items-center gap-1.5 px-2 pb-1 pt-0.5 text-[11px] font-bold", tone.text)}>
            {pink ? <PiGenderFemaleBold className="size-3.5" /> : <PiGenderMaleBold className="size-3.5" />}
            {pink ? "Female brokers" : "Male brokers"}
            {!isLoading && <span className="font-semibold text-muted-foreground">· {brokers.length}</span>}
          </div>
        )}
        {isLoading && <div className="py-6 text-center text-xs text-muted-foreground">Searching…</div>}
        {!isLoading && brokers.length === 0 && (
          <div className="py-6 text-center text-xs text-muted-foreground">
            {debounced
              ? `No brokers found for "${debounced}".`
              : gender
                ? `No ${pink ? "female" : "male"} brokers listed yet.`
                : mode === "pincode"
                ? "Enter your PIN code to find brokers near you."
                : mode === "city"
                  ? "Enter your city to find brokers there."
                  : "No brokers available right now."}
          </div>
        )}
        {exactRows.map(renderRow)}
        {nearRows.length > 0 && (
          <>
            <div className="px-2 pb-0.5 pt-2 text-[11px] font-semibold text-muted-foreground">
              {exactRows.length === 0
                ? `No brokers in ${where} yet. The nearest ones:`
                : "Also nearby"}
            </div>
            {nearRows.map(renderRow)}
          </>
        )}
      </div>
    </div>
  );

  function renderRow(b: BrokerOption) {
          const picked = value === b.id;
          const { title, subtitle } = brokerTitle(b);
          const rowTone = b.gender === "FEMALE" ? GENDER_TONE.FEMALE : tone;
          return (
            <button
              type="button"
              key={b.id}
              onClick={() => onSelect(b)}
              className={cn(
                "flex w-full items-center justify-between gap-2 rounded-lg border px-3 py-2.5 text-left transition-colors",
                picked
                  ? rowTone?.picked ?? "border-primary bg-primary/10"
                  : rowTone?.hover ?? "border-transparent hover:bg-muted/50",
              )}
            >
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                  <Building2 className={cn("size-3.5 shrink-0", rowTone?.icon ?? "text-primary")} />
                  <span className="max-w-full truncate text-sm font-bold">{title}</span>
                  {/* Area and PIN right beside the name — the first thing a
                      client checks is whether the broker is near them. */}
                  <span
                    className={cn(
                      "inline-flex shrink-0 items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold",
                      b.city || b.pincode ? "bg-muted text-foreground/80" : "text-muted-foreground/70",
                    )}
                  >
                    <MapPin className="size-3" />
                    {b.city || b.pincode
                      ? [b.city, b.pincode].filter(Boolean).join(" · ")
                      : "Area not added"}
                  </span>
                  {b.gender === "FEMALE" && !gender && (
                    <span className="inline-flex shrink-0 items-center gap-0.5 rounded-full bg-pink-500/15 px-1.5 py-0.5 text-[10px] font-bold text-pink-600 dark:text-pink-400">
                      <PiGenderFemaleBold className="size-3" /> Female
                    </span>
                  )}
                </span>
                {subtitle && (
                  <span className="mt-0.5 block truncate pl-5 text-[11px] text-muted-foreground">
                    {subtitle}
                  </span>
                )}
                <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                  <span className="font-mono">{b.user_code}</span>
                  {b.admin_name && <span>· {b.admin_name}</span>}
                </span>
                {(b.nearby || b.distance_km === 0) && (b.distance_km != null || b.area) && (
                  <span className="mt-1 inline-block rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                    {b.distance_km === 0
                      ? `Same city as ${b.near ?? "your search"}`
                      : b.distance_km != null
                        ? `≈ ${b.distance_km} km away`
                        : b.area}
                  </span>
                )}
              </span>
              {picked && <Check className={cn("size-4 shrink-0", rowTone?.icon ?? "text-primary")} />}
            </button>
          );
  }
}
