"use client";

import { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { usePager, Pager } from "@/components/common/Pager";

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  className?: string;
  width?: string;
  align?: "left" | "right" | "center";
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[] | undefined;
  keyExtractor: (row: T) => string;
  loading?: boolean;
  empty?: ReactNode;
  rowClassName?: (row: T) => string | undefined;
  onRowClick?: (row: T) => void;
  /** Tailwind max-height class applied to the scrollable wrapper.
   *  Default `max-h-[70vh]` so a long admin blotter scrolls internally
   *  instead of pushing the PageHeader / filter row off-screen. Pass
   *  an empty string to disable. */
  maxHeight?: string;
  /** Client-side page size. Defaults to 50 → any list longer than 50 rows
   *  auto-paginates with a footer pager. Server-paginated pages hand us
   *  ≤ their own page_size (all ≤ 50), so `total ≤ pageSize` and the pager
   *  stays hidden — no double-paging, no visual change. Pass 0 to render
   *  the whole array (old scroll-only behaviour). */
  pageSize?: number;
}

export function DataTable<T>({ columns, rows, keyExtractor, loading, empty, rowClassName, onRowClick, maxHeight = "max-h-[70vh]", pageSize = 50 }: Props<T>) {
  const all = rows ?? [];
  const paginate = pageSize > 0;
  // usePager is a hook → always call it (size falls back to the full length
  // when paging is off, giving a single page the pager hides anyway).
  const pg = usePager(all, paginate ? pageSize : all.length || 1);
  const view = paginate ? pg.slice : all;

  return (
    <div className="space-y-2">
      <div
        className={cn(
          // Vertical scroll lives inside the table container so the admin
          // page header + filters stay pinned. Horizontal scroll still
          // kicks in for wide column sets on smaller screens.
          "overflow-auto rounded-lg border border-border bg-card",
          maxHeight,
        )}
      >
        <table className="min-w-full text-sm">
          {/* Sticky header — column labels stay visible while rows scroll. */}
          <thead className="sticky top-0 z-10 border-b border-border bg-card text-xs uppercase text-muted-foreground shadow-[inset_0_-1px_0_0_hsl(var(--border))]">
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  className={cn(
                    "px-3 py-2 font-medium",
                    c.align === "right" && "text-right",
                    c.align === "center" && "text-center",
                    !c.align && "text-left",
                    c.className
                  )}
                  style={{ width: c.width }}
                >
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {loading && (
              <tr>
                <td colSpan={columns.length} className="px-3 py-12 text-center text-muted-foreground">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && all.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-3 py-12 text-center text-muted-foreground">
                  {empty ?? "No data"}
                </td>
              </tr>
            )}
            {!loading &&
              view.map((row) => (
                <tr
                  key={keyExtractor(row)}
                  onClick={() => onRowClick?.(row)}
                  className={cn(
                    "transition-colors hover:bg-muted/40",
                    onRowClick && "cursor-pointer",
                    rowClassName?.(row)
                  )}
                >
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={cn(
                        "whitespace-nowrap px-3 py-2 font-tabular",
                        c.align === "right" && "text-right",
                        c.align === "center" && "text-center",
                        c.className
                      )}
                    >
                      {c.render ? c.render(row) : (row as any)[c.key]}
                    </td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      {!loading && paginate && <Pager {...pg} />}
    </div>
  );
}
