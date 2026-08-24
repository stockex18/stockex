"use client";

import { useQuery } from "@tanstack/react-query";
import { LedgerBooksAPI } from "@/lib/api";

export type PaymentMode = { code: string; label: string };

/**
 * The payment modes the super-admin defined on the Ledgers page.
 *
 * Nothing is hardcoded: creating a mode there opens its ledger, and every
 * dropdown that asks "how did this money move?" reads the same list — so a
 * mode can never be offered that has nowhere to post.
 */
export function usePaymentModes() {
  const { data, isLoading } = useQuery({
    queryKey: ["payment-modes"],
    queryFn: () => LedgerBooksAPI.paymentModes(),
    staleTime: 60_000,
  });
  const modes: PaymentMode[] = data || [];
  const label = (code: string) => modes.find((m) => m.code === code)?.label || code;
  return { modes, label, isLoading };
}
