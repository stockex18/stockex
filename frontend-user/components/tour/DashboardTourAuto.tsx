"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { hasSeenDashboardTour, startDashboardTour } from "@/components/tour/dashboardTour";

/**
 * Starts the dashboard tour automatically on a user's first visit (per
 * browser), or when the page is opened with ?tour=1 (the header "?" button
 * from another page). Renders nothing, so it can't affect hydration.
 */
export function DashboardTourAuto() {
  const params = useSearchParams();
  const router = useRouter();
  const forced = params.get("tour") === "1";

  useEffect(() => {
    // Let the dashboard paint (wallet cards, tiles) — and the logged-in user
    // load, since "seen" is remembered per user — before deciding.
    const t = window.setTimeout(() => {
      if (!forced && hasSeenDashboardTour()) return;
      void startDashboardTour();
      if (forced) router.replace("/dashboard", { scroll: false });
    }, 900);
    return () => window.clearTimeout(t);
  }, [forced, router]);

  return null;
}
