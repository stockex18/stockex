"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Bell, BellOff, BellRing } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  ensureNotificationPermission,
  setUserNotificationsEnabled,
  subscribeForWebPush,
  userNotificationsEnabled,
} from "@/lib/notify-sound";
import { cn } from "@/lib/utils";

type PermState = "unsupported" | "default" | "granted" | "denied";

function readPerm(): PermState {
  if (typeof window === "undefined" || typeof Notification === "undefined") return "unsupported";
  return Notification.permission as PermState;
}

/* Phone notifications (Web Push) — the switch a user can actually find.

   `banner` (Alerts page): only while notifications are not allowed yet.
   `card` (Notifications page — where the 🔔 bell and Profile → Notifications
   both lead): always shown, with the phone status and the in-app pop-up
   switch. The mobile app had no way to reach the old Alerts-page-only
   banner, so clients never saw an option at all.

   iPhone only asks after a tap, and only for StockEx added to the Home
   Screen — so this is a button, never an automatic prompt. Everything reads
   the browser only after mount, so the server and first browser draw match. */
export function PushOptIn({ variant }: { variant: "banner" | "card" }) {
  const [mounted, setMounted] = useState(false);
  const [perm, setPerm] = useState<PermState>("default");
  const [popups, setPopups] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setMounted(true);
    const p = readPerm();
    setPerm(p);
    setPopups(userNotificationsEnabled());
    // Allowed already (maybe before push was set up on the server): make
    // sure this phone is registered. Idempotent on the server.
    if (variant === "card" && p === "granted") void subscribeForWebPush();
  }, [variant]);

  if (!mounted) return null;
  if (variant === "banner" && perm === "granted") return null;

  async function enable() {
    setBusy(true);
    try {
      const ok = await ensureNotificationPermission();
      setPerm(readPerm());
      if (!ok) {
        toast.error("Notifications are blocked for StockEx");
        return;
      }
      const registered = await subscribeForWebPush();
      if (registered) toast.success("Phone notifications on — you'll be told when an alert is hit");
      else toast.warning("Notifications allowed, but this phone could not be registered. Try again later.");
    } finally {
      setBusy(false);
    }
  }

  function togglePopups() {
    const next = !popups;
    setPopups(next);
    setUserNotificationsEnabled(next);
  }

  const on = perm === "granted";
  const blocked = perm === "denied";
  const unsupported = perm === "unsupported";

  const title = on
    ? "Phone notifications are on"
    : blocked
      ? "Phone notifications are blocked"
      : unsupported
        ? "Phone notifications aren't available here"
        : "Get a phone notification when an alert is hit";
  const hint = on
    ? "Price alerts, deposits and withdrawals reach this phone even with the app closed."
    : unsupported
      ? "On iPhone, add StockEx to your Home Screen first (Share → Add to Home Screen), then open it from there."
      : blocked
        ? "Allow notifications for StockEx in your phone or browser settings, then reopen the app."
        : "You'll still see alerts in the app, but not with the app closed.";

  const Icon = on ? BellRing : BellOff;

  return (
    <div
      className={cn(
        "rounded-xl border p-3",
        on ? "border-emerald-500/40 bg-emerald-500/10" : "border-amber-500/40 bg-amber-500/10",
      )}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span className="flex min-w-0 items-start gap-2.5">
          <Icon className={cn("mt-0.5 size-4 shrink-0", on ? "text-emerald-500" : "text-amber-500")} />
          <span className="min-w-0 text-sm">
            <span className="block font-semibold">{title}</span>
            <span className="block text-xs text-muted-foreground">{hint}</span>
          </span>
        </span>
        {!on && !blocked && !unsupported && (
          <Button onClick={enable} loading={busy} className="shrink-0">
            <Bell className="size-4" /> Enable notifications
          </Button>
        )}
      </div>

      {variant === "card" && (
        <div className="mt-3 flex items-center justify-between gap-3 border-t border-border/60 pt-3">
          <span className="min-w-0 text-sm">
            <span className="block font-medium">Pop-ups and sound in the app</span>
            <span className="block text-xs text-muted-foreground">
              While the app is open. Off = the list here still fills, quietly.
            </span>
          </span>
          <button
            type="button"
            onClick={togglePopups}
            aria-pressed={popups}
            aria-label={popups ? "Turn off in-app pop-ups and sound" : "Turn on in-app pop-ups and sound"}
            className={cn(
              "relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full transition-colors",
              popups ? "bg-emerald-500" : "bg-muted",
            )}
          >
            <span
              className={cn(
                "inline-block size-5 transform rounded-full bg-white shadow transition-transform",
                popups ? "translate-x-6" : "translate-x-1",
              )}
            />
          </button>
        </div>
      )}
    </div>
  );
}
