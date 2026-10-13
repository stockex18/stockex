"use client";

import { usePathname } from "next/navigation";
import { HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { startTour, tourForPath } from "@/components/tour/tours";

/** Header "?" button: replays this page's tour. Hidden on pages that don't
 *  have one yet, rather than sending the user off to another page's tour. */
export function TourButton({ className }: { className?: string }) {
  const pathname = usePathname();
  const id = tourForPath(pathname);
  if (!id) return null;

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Take a tour"
      title="Take a tour"
      onClick={() => void startTour(id)}
      data-tour="tour-button"
      className={className}
    >
      <HelpCircle className="size-4" />
    </Button>
  );
}
