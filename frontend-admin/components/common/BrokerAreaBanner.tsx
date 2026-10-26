"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { MapPin } from "lucide-react";
import { useAdminAuthStore } from "@/stores/authStore";
import { AdminMeAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";

/** Shared with the Settings place editor, which invalidates it on save so the
 *  banner goes the moment the broker fills the gap. */
export const MY_PROFILE_KEY = ["admin-me-profile"] as const;

/**
 * Shown to a REAL broker whose city or PIN code is missing. The client-side
 * signup picker's City and PIN modes match on nothing else, so such a broker
 * is invisible to every client searching their own area. Signup now asks for
 * both; this catches the brokers who registered before it did.
 * Demo brokers are never offered to clients, so they are not nagged.
 */
export function BrokerAreaBanner() {
  const admin = useAdminAuthStore((s) => s.admin);
  const isRealBroker = String(admin?.role ?? "").toUpperCase() === "BROKER" && !admin?.is_demo;

  const { data } = useQuery({
    queryKey: MY_PROFILE_KEY,
    queryFn: AdminMeAPI.profile,
    enabled: isRealBroker,
    staleTime: 5 * 60_000,
  });

  if (!isRealBroker || !data) return null;
  const missing = [!data.city && "city", !data.pincode && "PIN code"].filter(Boolean) as string[];
  if (missing.length === 0) return null;

  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-amber-500/30 bg-amber-500/5 px-3.5 py-2.5">
      <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-amber-500/15 text-amber-600">
        <MapPin className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold leading-tight">Add your {missing.join(" and ")}</p>
        <p className="text-[11px] leading-snug text-muted-foreground">
          New clients search for brokers by city and PIN code when they sign up. Until you add
          your {missing.join(" and ")}, you won&apos;t appear in those searches.
        </p>
      </div>
      <Button asChild className="h-9 shrink-0 bg-amber-600 font-bold text-white hover:bg-amber-700">
        <Link href="/settings/platform">Add now</Link>
      </Button>
    </div>
  );
}
