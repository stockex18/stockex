import Link from "next/link";
import { cn } from "@/lib/utils";

/* Cross-links between the four tools. Landing on one calculator from the
   homepage grid used to be a dead end — you had to go back to the
   homepage to reach the next one. */

export const TOOLS = [
  { href: "/tools/brokerage-calculator", label: "Brokerage" },
  { href: "/tools/profit-loss-calculator", label: "Profit & Loss" },
  { href: "/tools/margin-calculator", label: "Margin" },
  { href: "/tools/market-heatmap", label: "Market Heatmap" },
];

export function ToolsNav({ current }: { current: string }) {
  return (
    <nav
      aria-label="Trading tools"
      className="flex flex-wrap gap-1.5 rounded-2xl border border-mp-border bg-mp-surface-2 p-1.5"
    >
      {TOOLS.map((t) => {
        const active = t.href === current;
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "rounded-xl px-4 py-2 text-[13px] font-semibold transition-colors",
              active
                ? "bg-mp-primary text-white"
                : "text-mp-text-mut hover:bg-mp-surface hover:text-mp-text",
            )}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
