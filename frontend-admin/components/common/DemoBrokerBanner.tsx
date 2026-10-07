"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Rocket, AlertTriangle } from "lucide-react";
import { useAdminAuthStore } from "@/stores/authStore";
import { AdminMeAPI, ApiError } from "@/lib/api";
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
 * Bold banner shown only to a DEMO BROKER. Converting turns the demo into a real
 * broker server-side: zeroes the 50L virtual float and unlocks user creation.
 * Rendered once in the admin shell so it appears on every page.
 */
export function DemoBrokerBanner() {
  const admin = useAdminAuthStore((s) => s.admin);
  const refreshMe = useAdminAuthStore((s) => s.refreshMe);
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!admin?.is_demo) return null;

  async function convert() {
    setBusy(true);
    try {
      await AdminMeAPI.convertToReal();
      await refreshMe();
      await queryClient.invalidateQueries();
      setOpen(false);
      toast.success("You're now a real broker — float ₹0. Contact your admin for funds.");
      router.push("/my-wallet");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not switch to real account.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-3.5 py-2.5">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-emerald-500/15 text-emerald-600">
          🪙
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-bold leading-tight">You&apos;re on a demo broker account</p>
          <p className="text-[11px] leading-snug text-muted-foreground">
            🪙50,00,000 virtual float · 3 demo clients to practise on — fund them,
            defund them, change their settings and trade for them. Switch to a real
            broker account when you want real clients.
          </p>
        </div>
        <Button
          onClick={() => setOpen(true)}
          className="h-9 shrink-0 bg-emerald-600 font-bold text-white hover:bg-emerald-700"
        >
          <Rocket className="mr-1.5 size-4" /> Switch to Real Broker
        </Button>
      </div>

      <Dialog open={open} onOpenChange={(v) => !busy && setOpen(v)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="size-5 text-amber-500" /> Switch to a real broker?
            </DialogTitle>
            <DialogDescription className="space-y-2 pt-1">
              <span className="block">Your demo becomes a real broker account. This will:</span>
              <span className="block rounded-lg border border-border bg-muted/30 p-2.5 text-[13px] leading-relaxed text-foreground">
                • Set your wallet float to <span className="font-bold">₹0</span> (your admin funds you)
                <br />• Let you create <span className="font-bold">real users</span> (your demo clients stay demo)
                <br />• Keep your login &amp; broker profile
              </span>
              <span className="block text-[12px]">This can&apos;t be undone.</span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-2">
            <Button variant="outline" onClick={() => setOpen(false)} disabled={busy}>
              Stay on demo
            </Button>
            <Button onClick={convert} loading={busy} className="bg-emerald-600 font-bold text-white hover:bg-emerald-700">
              Yes, make it real
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
