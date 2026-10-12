"use client";

import { useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { hasSeenTour, startTour, type TourId } from "@/components/tour/tours";

/**
 * Starts a page's tour automatically on the user's first visit, or when the
 * page is opened with ?tour=1. Renders nothing, so it can't affect hydration.
 * Needs a <Suspense> boundary around it (useSearchParams).
 */
export function PageTourAuto({ id }: { id: TourId }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const forced = params.get("tour") === "1";

  useEffect(() => {
    // Let the page paint (cards, tiles) — and the logged-in user load, since
    // "seen" is remembered per user — before deciding.
    const t = window.setTimeout(() => {
      if (!forced && hasSeenTour(id)) return;
      // A dialog is already open (e.g. /wallet?action=deposit): don't put a
      // tour on top of it. Not marked seen, so it shows next visit instead.
      if (!forced && document.querySelector('[role="dialog"]')) return;
      void startTour(id);
      if (forced) router.replace(pathname, { scroll: false });
    }, 900);
    return () => window.clearTimeout(t);
  }, [forced, id, pathname, router]);

  return null;
}
