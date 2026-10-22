"use client";

import { useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useAdminAuthStore } from "@/stores/authStore";
import { hasSeenTour, isTourAudience, startTour, tourForPath } from "@/components/tour/tours";

/**
 * Starts the current page's tour on a broker's first visit, or when the page
 * is opened with ?tour=1. Mounted once in the (admin) layout, so pages only
 * need data-tour markers. Renders nothing, so it can't affect hydration.
 * Needs a <Suspense> boundary around it (useSearchParams).
 * Broker tours were added as per client requirement, to help new brokers
 * find their way around the panel.
 */
export function TourAuto() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const admin = useAdminAuthStore((s) => s.admin);
  const id = isTourAudience(admin) ? tourForPath(pathname) : undefined;
  const forced = params.get("tour") === "1";

  useEffect(() => {
    if (!id) return;
    // Let the page paint (cards, tables) before deciding.
    const t = window.setTimeout(() => {
      if (!forced && hasSeenTour(id)) return;
      // A dialog is already open: don't put a tour on top of it. Not marked
      // seen, so it shows next visit instead.
      if (!forced && document.querySelector('[role="dialog"]')) return;
      void startTour(id);
      if (forced) router.replace(pathname, { scroll: false });
    }, 900);
    return () => window.clearTimeout(t);
  }, [forced, id, pathname, router]);

  return null;
}
