"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CategoryChips } from "@/components/admin/netting/CategoryChips";
import { SegmentMatrix } from "@/components/admin/netting/SegmentMatrix";

/** A PARENT (admin, or a broker for its sub-broker) edits ONE broker's per-segment
 *  settings — the same per-node editor the super-admin uses for an admin. When the
 *  broker runs the FIXED-brokerage flow, the rate set here is frozen as the
 *  parent's take from the broker's whole subtree. */
export function BrokerSegmentDialog({
  open,
  onOpenChange,
  brokerId,
  brokerName,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  brokerId: string | null;
  brokerName?: string;
}) {
  const [category, setCategory] = useState("lot");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-5xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Segment settings · {brokerName || "Broker"}</DialogTitle>
          <DialogDescription>
            Set this broker&apos;s per-segment settings. If the broker is on the fixed-brokerage
            flow, the brokerage you set here is the FIXED rate you take from their whole subtree —
            no matter what they later charge their own users.
          </DialogDescription>
        </DialogHeader>
        {brokerId && (
          <div className="space-y-3">
            <CategoryChips value={category} onChange={setCategory} />
            <SegmentMatrix categoryId={category} brokerId={brokerId} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
