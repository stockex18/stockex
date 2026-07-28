"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Rocket, AlertTriangle } from "lucide-react";
import { useAuthStore } from "@/stores/authStore";
import { ProfileAPI, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";

/**
 * A bold, always-visible banner shown ONLY on a demo account. It lets the user
 * convert their personal demo into a real account — which server-side wipes all
 * demo trades/positions and zeroes the balance (POST /users/me/convert-to-real).
 * Rendered once in the dashboard shell so it appears on every page.
 */
export function DemoSwitchBanner() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!user?.is_demo) return null;

  async function convert() {
    setBusy(true);
    try {
      await ProfileAPI.convertToReal();
      // Flip the persisted user so every is_demo gate updates instantly.
      if (user) setUser({ ...user, is_demo: false });
      // Demo data was wiped server-side — drop all cached queries so wallet,
      // positions, orders, etc. refetch their fresh (empty / ₹0) state.
      await queryClient.invalidateQueries();
      setOpen(false);
      toast.success("Your account is now real — balance ₹0. Add funds to start trading.");
      router.push("/wallet");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not switch to real account.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-4">
      {/* Red = "you're in DEMO" warning state. Stacks on mobile so the copy never
          collapses; goes side-by-side from sm: up. */}
      <div className="relative overflow-hidden rounded-xl border border-[#ef4444]/40 bg-gradient-to-r from-[#ef4444]/10 to-[#ef4444]/[0.04] px-3.5 py-3">
        <span aria-hidden className="pointer-events-none absolute -right-8 -top-8 size-24 rounded-full bg-[#ef4444]/10 blur-2xl" />
        <div className="relative flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="flex min-w-0 flex-1 items-start gap-3">
            <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-[#ef4444]/15 text-[#ef4444]">
              <AlertTriangle className="size-4" />
            </span>
            <div className="min-w-0">
              <p className="flex items-center gap-2 text-sm font-bold leading-tight text-foreground">
                You&apos;re on a demo account
                <span className="rounded bg-[#ef4444]/15 px-1.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wide text-[#ef4444]">
                  Demo
                </span>
              </p>
              <p className="text-[11px] leading-snug text-muted-foreground">
                Balance is virtual practice money. Ready to trade for real?
              </p>
            </div>
          </div>
          <Button
            onClick={() => setOpen(true)}
            className="h-9 w-full shrink-0 rounded-lg border-0 bg-gradient-to-r from-[#dc2626] to-[#ef4444] px-4 text-sm font-bold text-white shadow-md shadow-[#ef4444]/30 transition hover:opacity-95 active:scale-[0.99] sm:w-auto"
          >
            <Rocket className="mr-1.5 size-4" /> Switch to Real Account
          </Button>
        </div>
      </div>

      <Dialog open={open} onOpenChange={(v) => !busy && setOpen(v)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="size-5 text-atm" /> Switch to a real account?
            </DialogTitle>
            <DialogDescription className="space-y-2 pt-1">
              <span className="block">
                Your demo is about to become a <span className="font-bold text-foreground">real account</span>. This will:
              </span>
              <span className="block rounded-lg border border-border/50 bg-muted/30 p-2.5 text-[13px] leading-relaxed text-foreground">
                • Set your balance to <span className="font-bold">₹0</span> (deposit to start trading)
                <br />• Remove all demo trades, positions &amp; orders
                <br />• Keep your login &amp; chosen broker
              </span>
              <span className="block text-[12px]">
                This can&apos;t be undone. Your demo data will be permanently cleared.
              </span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-2">
            <Button variant="outline" onClick={() => setOpen(false)} disabled={busy}>
              Stay on demo
            </Button>
            <Button
              onClick={convert}
              loading={busy}
              className="border-0 bg-gradient-to-r from-[#16A34A] to-[#22C55E] font-bold text-white hover:opacity-95"
            >
              Yes, make it real
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
