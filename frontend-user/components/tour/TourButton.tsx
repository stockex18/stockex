"use client";

import { usePathname, useRouter } from "next/navigation";
import { HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { startDashboardTour } from "@/components/tour/dashboardTour";

/** Header "?" button: replays the dashboard tour (from any page). */
export function TourButton() {
  const pathname = usePathname();
  const router = useRouter();

  function onClick() {
    if (pathname === "/dashboard") {
      void startDashboardTour();
    } else {
      router.push("/dashboard?tour=1");
    }
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Take a tour"
      title="Take a tour"
      onClick={onClick}
      data-tour="tour-button"
    >
      <HelpCircle className="size-4" />
    </Button>
  );
}
