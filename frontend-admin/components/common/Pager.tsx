"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Dead-simple client-side pagination over an already-fetched array.
 * Slice the rows you render with `slice`, drop a <Pager> under the table.
 * Fetch a generous window (e.g. limit 200-300) and page through it locally —
 * no backend paging needed for the common admin lists.
 *
 *   const pg = usePager(rows, 20);
 *   {pg.slice.map(...)}
 *   <Pager {...pg} />
 */
export function usePager<T>(rows: T[], pageSize = 20) {
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const clamped = Math.min(page, pageCount - 1);
  const start = clamped * pageSize;
  return {
    page: clamped,
    setPage,
    pageCount,
    pageSize,
    total: rows.length,
    slice: rows.slice(start, start + pageSize),
  };
}

export function Pager({
  page,
  setPage,
  pageCount,
  pageSize,
  total,
}: {
  page: number;
  setPage: (p: number) => void;
  pageCount: number;
  pageSize: number;
  total: number;
}) {
  if (total <= pageSize) return null; // single page → no controls
  const from = page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  return (
    <div className="flex items-center justify-between gap-2 pt-3 text-xs text-muted-foreground">
      <span className="tabular-nums">
        {from}–{to} of {total}
      </span>
      <div className="flex items-center gap-1">
        <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
          <ChevronLeft className="size-4" />
        </Button>
        <span className="px-1 tabular-nums">
          {page + 1} / {pageCount}
        </span>
        <Button variant="outline" size="sm" disabled={page >= pageCount - 1} onClick={() => setPage(page + 1)}>
          <ChevronRight className="size-4" />
        </Button>
      </div>
    </div>
  );
}
