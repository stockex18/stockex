"use client";

import { cn } from "@/lib/utils";

export type BrokerGender = "MALE" | "FEMALE";

/** Male / Female, asked whenever a broker is created. It decides which
 *  clients may pick them: female clients join female brokers only. */
export function GenderChoice({
  value,
  onChange,
  tone = "panel",
}: {
  value: BrokerGender | "" | undefined;
  onChange: (g: BrokerGender) => void;
  /** "dark" for the broker signup screen's dark gold card. */
  tone?: "panel" | "dark";
}) {
  return (
    <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Gender">
      {(["MALE", "FEMALE"] as const).map((g) => {
        const on = value === g;
        const f = g === "FEMALE";
        return (
          <button
            key={g}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(g)}
            className={cn(
              "h-10 rounded-lg border text-sm font-semibold transition-colors",
              on
                ? f
                  ? "border-pink-500 bg-pink-500 text-white"
                  : "border-sky-500 bg-sky-500 text-white"
                : tone === "dark"
                  ? "border-[#f5ecd0]/20 bg-white/5 text-[#f5ecd0]/80 hover:bg-white/10"
                  : "border-border bg-background text-muted-foreground hover:text-foreground",
            )}
          >
            {f ? "♀ Female" : "♂ Male"}
          </button>
        );
      })}
    </div>
  );
}
