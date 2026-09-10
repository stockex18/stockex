"use client";

/**
 * "Whose book is this?" — the admin filter and the per-row admin badge.
 *
 * The super-admin sees every admin's orders and positions in one list, which
 * is only useful if each row says who it belongs to and the list can be cut
 * down to one admin. Both live here so the two monitors cannot drift apart.
 *
 * The badge colour is DERIVED FROM THE ADMIN'S ID, not from row order. That is
 * the whole point: the same admin is the same colour on every row, on every
 * page, across reloads — which is what lets you pick their rows out of a mixed
 * list at a glance. Colour picked by row index would reshuffle on every sort.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Users } from "lucide-react";
import { AdminMeAPI } from "@/lib/api";
import { useAdminAuthStore } from "@/stores/authStore";
import { cn } from "@/lib/utils";

/** Fixed palette — readable on both themes, and distinct from the buy/sell
 *  green and red so an admin badge is never mistaken for a P&L colour. */
const TONES = [
  "border-violet-500/40 bg-violet-500/15 text-violet-600 dark:text-violet-300",
  "border-sky-500/40 bg-sky-500/15 text-sky-600 dark:text-sky-300",
  "border-amber-500/40 bg-amber-500/15 text-amber-600 dark:text-amber-300",
  "border-teal-500/40 bg-teal-500/15 text-teal-600 dark:text-teal-300",
  "border-fuchsia-500/40 bg-fuchsia-500/15 text-fuchsia-600 dark:text-fuchsia-300",
  "border-cyan-500/40 bg-cyan-500/15 text-cyan-600 dark:text-cyan-300",
  "border-indigo-500/40 bg-indigo-500/15 text-indigo-600 dark:text-indigo-300",
  "border-orange-500/40 bg-orange-500/15 text-orange-600 dark:text-orange-300",
];

function toneFor(key: string): string {
  // Cheap stable hash — same id in, same tone out, every time.
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
  return TONES[Math.abs(h) % TONES.length];
}

export function useIsSuperAdmin(): boolean {
  const me = useAdminAuthStore((s) => s.admin);
  return (me?.role || "") === "SUPER_ADMIN";
}

/** The admins this caller can filter by. Empty for anyone with no members. */
export function useAdminChoices() {
  const { data } = useQuery({
    queryKey: ["admin", "me", "members"],
    queryFn: () => AdminMeAPI.members(),
    staleTime: 5 * 60_000,
  });
  return useMemo(
    () =>
      ((data as any[]) || []).filter(
        (m) => m?.id && ["ADMIN", "BROKER"].includes(String(m.role || "ADMIN")),
      ),
    [data],
  );
}

/** Row badge naming the admin a row belongs to. Renders nothing when the row
 *  has no owning admin — a super-admin's own direct client, typically. */
export function AdminBadge({
  id,
  name,
  className = "",
}: {
  id?: string | null;
  name?: string | null;
  className?: string;
}) {
  const label = (name || "").trim();
  if (!label) return null;
  return (
    <span
      className={cn(
        "inline-flex max-w-[11rem] items-center truncate rounded border px-1.5 py-0.5 text-[10px] font-medium leading-none",
        toneFor(String(id || label)),
        className,
      )}
      title={`Admin: ${label}`}
    >
      {label}
    </span>
  );
}

/** The picker. Hidden entirely for a caller with nobody to choose between —
 *  a broker filtering by "their one admin" is just the page they already see. */
export function AdminFilter({
  value,
  onChange,
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  className?: string;
}) {
  const admins = useAdminChoices();
  if (admins.length === 0) return null;
  const picked = admins.find((a) => String(a.id) === value);
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <Users className="size-4 shrink-0 text-muted-foreground" />
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 rounded-md border border-input bg-background px-2 text-sm outline-none focus:ring-1 focus:ring-ring"
        title="Show one admin's book, or everybody's"
      >
        <option value="">All admins</option>
        {admins.map((a) => (
          <option key={a.id} value={String(a.id)}>
            {(a.full_name || a.user_code) + " · " + a.user_code}
          </option>
        ))}
      </select>
      {picked && (
        <AdminBadge id={String(picked.id)} name={picked.full_name || picked.user_code} />
      )}
    </div>
  );
}
