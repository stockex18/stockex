"use client";

import { usePathname, useRouter } from "next/navigation";
import { HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { startTour, tourForPath } from "@/components/tour/tours";

/** Header "?" button: replays this page's tour, or the dashboard tour on
 *  pages that don't have one yet. */
export function TourButton({ className }: { className?: string }) {
  const pathname = usePathname();
  const router = useRouter();

  function onClick() {
    const id = tourForPath(pathname);
    if (id) {
      void startTour(id);
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
      className={className}
    >
      <HelpCircle className="size-4" />
    </Button>
  );
}
