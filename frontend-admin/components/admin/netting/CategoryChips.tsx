"use client";

import { cn } from "@/lib/utils";
import { categoriesFor } from "@/lib/nettingMatrixConfig";
import { useAdminAuthStore } from "@/stores/authStore";

export function CategoryChips({
  value,
  onChange,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  className?: string;
}) {
  const role = useAdminAuthStore((s) => s.admin?.role);
  return (
    <div
      className={cn(
        "inline-flex flex-wrap gap-1 rounded-md border border-border bg-muted/20 p-1 text-xs",
        className
      )}
    >
      {categoriesFor(role).map((c) => (
        <button
          key={c.id}
          type="button"
          onClick={() => onChange(c.id)}
          className={cn(
            "rounded px-2.5 py-1 transition-colors",
            value === c.id
              ? "bg-primary/15 text-primary"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {c.label}
        </button>
      ))}
    </div>
  );
}
