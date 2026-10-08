"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { IconType } from "react-icons";
import {
  PiBriefcase,
  PiBriefcaseFill,
  PiChartBar,
  PiChartBarFill,
  PiGameController,
  PiGameControllerFill,
  PiHouse,
  PiHouseFill,
  PiUser,
  PiUserFill,
} from "react-icons/pi";
import { cn } from "@/lib/utils";

// Outline when idle, filled + gold when it is the page you are on.
const items: { href: string; label: string; icon: IconType; active: IconType }[] = [
  { href: "/dashboard", label: "Home", icon: PiHouse, active: PiHouseFill },
  { href: "/marketwatch", label: "Market", icon: PiChartBar, active: PiChartBarFill },
  { href: "/games", label: "Games", icon: PiGameController, active: PiGameControllerFill },
  // /positions is the unified blotter (Position / Active / Closed /
  // Cancelled / Rejected tabs).
  { href: "/positions", label: "Position", icon: PiBriefcase, active: PiBriefcaseFill },
  { href: "/profile", label: "Profile", icon: PiUser, active: PiUserFill },
];

/**
 * Mobile-only bottom tab bar. Hidden ≥ md so the desktop sidebar is the
 * single nav surface there. Sits above the page in a translucent sticky
 * footer with safe-area padding.
 *
 * Edge-to-edge, full-width — the previous "compact pill" mode was
 * rejected by the user ("ye jo box ke andar rakh hai waisa mat rakh
 * yrr"). One consistent shape across every mobile route now.
 */
export function BottomNav() {
  const pathname = usePathname();
  return (
    <nav
      className={cn(
        // Solid bg (no backdrop-blur): a fixed full-width blur bar makes iOS
        // Safari re-composite the whole viewport every frame → the iPhone-only
        // scroll jank + slow route transitions. Solid is visually equivalent
        // and cheap. Android Chrome handled the blur fine; iOS does not.
        "fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background",
        "md:hidden",
      )}
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <ul className="grid grid-cols-5">
        {items.map((it) => {
          const active = pathname === it.href || pathname?.startsWith(it.href + "/");
          const Icon = active ? it.active : it.icon;
          return (
            <li key={it.href}>
              <Link
                href={it.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-14 flex-col items-center justify-center gap-0.5 text-[10.5px] font-bold transition-colors",
                  active ? "text-primary" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="size-[22px]" />
                <span>{it.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
