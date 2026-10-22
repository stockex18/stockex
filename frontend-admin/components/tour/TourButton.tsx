"use client";

import { usePathname } from "next/navigation";
import { HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAdminAuthStore } from "@/stores/authStore";
import { isTourAudience, startTour, tourForPath } from "@/components/tour/tours";

/** Header "?" button: replays this page's tour. Brokers only, and hidden on
 *  pages that don't have a tour yet. */
export function TourButton({ className }: { className?: string }) {
  const pathname = usePathname();
  const admin = useAdminAuthStore((s) => s.admin);
  const id = isTourAudience(admin) ? tourForPath(pathname) : undefined;
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
