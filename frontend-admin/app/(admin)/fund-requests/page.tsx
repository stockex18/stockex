"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, X, Send, Inbox, HandCoins, ArrowRightLeft } from "lucide-react";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AdminFundAPI } from "@/lib/api";
import { formatINR, cn } from "@/lib/utils";
import { useAdminAuthStore } from "@/stores/authStore";

const STATUS_TONE: Record<string, string> = {
  PENDING: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  APPROVED: "bg-buy/15 text-buy",
  REJECTED: "bg-sell/15 text-sell",
};

export default function FundRequestsPage() {
  const qc = useQueryClient();
  const admin = useAdminAuthStore((s) => s.admin);
  const isSuper = admin?.role === "SUPER_ADMIN";

  const { data: incoming } = useQuery({
    queryKey: ["admin", "fund", "incoming"],
    queryFn: () => AdminFundAPI.incoming("PENDING"),
    refetchInterval: 10000,
  });
  const { data: mine } = useQuery({
    queryKey: ["admin", "fund", "mine"],
    queryFn: () => AdminFundAPI.mine(),
    refetchInterval: 10000,
  });

  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["admin", "fund", "incoming"] });
    qc.invalidateQueries({ queryKey: ["admin", "fund", "mine"] });
    qc.invalidateQueries({ queryKey: ["admin", "me", "wallet"] });
  };

  // Peer transfer — send my own float to another admin by their ID/code.
  const [xferTarget, setXferTarget] = useState("");
  const [xferAmount, setXferAmount] = useState("");
  const [xferNote, setXferNote] = useState("");
  const transfer = useMutation({
    mutationFn: () => AdminFundAPI.transferToAdmin(xferTarget.trim(), Number(xferAmount), xferNote),
    onSuccess: (r: any) => {
      toast.success(`Sent ${formatINR(Number(xferAmount))} to ${r?.to_code || xferTarget}`);
      setXferTarget(""); setXferAmount(""); setXferNote(""); refresh();
    },
    onError: (e: any) => toast.error(e?.message || "Transfer failed"),
  });
  const xferAmt = Number(xferAmount);
  const validXfer = xferTarget.trim().length > 0 && Number.isFinite(xferAmt) && xferAmt > 0;

  const create = useMutation({
    mutationFn: () => AdminFundAPI.createRequest(Number(amount), reason),
    onSuccess: () => { toast.success("Fund request submitted"); setAmount(""); setReason(""); refresh(); },
    onError: (e: any) => toast.error(e?.message || "Failed"),
  });
  const resolve = useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) => AdminFundAPI.resolve(id, approve),
    onSuccess: (_r, v) => { toast.success(v.approve ? "Approved" : "Rejected"); refresh(); },
    onError: (e: any) => toast.error(e?.message || "Failed"),
  });

  const amt = Number(amount);
  const validAmt = Number.isFinite(amt) && amt > 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Fund Requests"
        description="Requests flow up, funds flow down. Ask your parent for funds, or approve your members' requests."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Request funds (non-super only) */}
        {!isSuper && (
          <Card data-tour="fr-request">
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><Send className="size-4 text-primary" /> Request funds</CardTitle>
              <CardDescription>Ask your parent (admin/broker) or the super-admin for funds.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <Label className="text-xs">Amount (🪙)</Label>
                  <Input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" inputMode="decimal" />
                </div>
                <div>
                  <Label className="text-xs">Reason</Label>
                  <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Optional" />
                </div>
              </div>
              <Button disabled={!validAmt || create.isPending} loading={create.isPending} onClick={() => create.mutate()}>
                <Send className="size-4" /> Submit request
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Send funds to ANOTHER admin by ID — peer transfer from own float */}
        <Card data-tour="fr-send">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ArrowRightLeft className="size-4 text-primary" /> Send to another admin
            </CardTitle>
            <CardDescription>
              Transfer from your own balance to any admin by their ID (e.g. ADM… / BRK…). Settles instantly.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <Label className="text-xs">Recipient admin ID</Label>
              <Input
                value={xferTarget}
                onChange={(e) => setXferTarget(e.target.value)}
                placeholder="ADM55199697"
                className="font-mono"
              />
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <Label className="text-xs">Amount (🪙)</Label>
                <Input value={xferAmount} onChange={(e) => setXferAmount(e.target.value)} placeholder="0.00" inputMode="decimal" />
              </div>
              <div>
                <Label className="text-xs">Note</Label>
                <Input value={xferNote} onChange={(e) => setXferNote(e.target.value)} placeholder="Optional" />
              </div>
            </div>
            <Button
              variant="outline"
              className="border-primary/40 text-primary hover:bg-primary/10"
              disabled={!validXfer || transfer.isPending}
              loading={transfer.isPending}
              onClick={() => transfer.mutate()}
            >
              <ArrowRightLeft className="size-4" /> Send funds
            </Button>
          </CardContent>
        </Card>

        {/* Incoming requests to approve */}
        <Card data-tour="fr-incoming" className={cn(isSuper && "lg:col-span-2")}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Inbox className="size-4 text-primary" /> Incoming requests</CardTitle>
            <CardDescription>Pending fund requests from your members.</CardDescription>
          </CardHeader>
          <CardContent>
            {(incoming?.length ?? 0) === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">No pending requests.</div>
            ) : (
              <div className="space-y-2">
                {(incoming || []).map((r: any) => (
                  <div key={r.id} className="flex flex-col gap-3 rounded-xl border border-border/60 bg-card p-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-semibold">{r.requester_code}</span>
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-bold text-muted-foreground">{r.requester_role}</span>
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">{r.reason || "—"} · {r.created_at ? new Date(r.created_at).toLocaleString("en-IN") : ""}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="font-tabular text-lg font-bold tabular-nums">{formatINR(r.amount)}</span>
                      <Button size="sm" className="bg-buy text-buy-foreground hover:bg-buy/90" loading={resolve.isPending} onClick={() => resolve.mutate({ id: r.id, approve: true })}>
                        <Check className="size-4" /> Approve
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => resolve.mutate({ id: r.id, approve: false })}>
                        <X className="size-4" /> Reject
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* My requests history */}
      <Card data-tour="fr-mine">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><HandCoins className="size-4 text-muted-foreground" /> My requests</CardTitle>
        </CardHeader>
        <CardContent>
          {(mine?.length ?? 0) === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">You haven&apos;t requested any funds.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">Amount</th>
                    <th className="py-2 pr-3 font-medium">To</th>
                    <th className="py-2 pr-3 font-medium">Reason</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 text-right font-medium">When</th>
                  </tr>
                </thead>
                <tbody>
                  {(mine || []).map((r: any) => (
                    <tr key={r.id} className="border-b border-border/50 last:border-0">
                      <td className="py-2 pr-3 font-tabular font-bold tabular-nums">{formatINR(r.amount)}</td>
                      <td className="py-2 pr-3 font-mono text-xs text-muted-foreground">{r.target_code}</td>
                      <td className="py-2 pr-3 text-muted-foreground">{r.reason || "—"}</td>
                      <td className="py-2 pr-3">
                        <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-bold uppercase", STATUS_TONE[r.status] || "bg-muted text-muted-foreground")}>{r.status}</span>
                      </td>
                      <td className="py-2 text-right text-[11px] tabular-nums text-muted-foreground">
                        {r.created_at ? new Date(r.created_at).toLocaleDateString("en-IN") : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
