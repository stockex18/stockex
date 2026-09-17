"use client";

/**
 * Ledgers — the ruled account statement, the way accounting software keeps it.
 *
 * Nothing is preset. You create the payment modes you actually use, and
 * creating one opens its ledger — so a mode can never be offered that has
 * nowhere to post. Every movement stamped with that mode then lands here on
 * its own, in the name of the admin it was with. Any other ledger you name is
 * hand-kept.
 *
 * Either way the balance is REPLAYED from the opening figure rather than
 * stored, so what the table shows is always what the rows add up to.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  BookOpen,
  Plus,
  HandCoins,
  Download,
  Trash2,
  Building2,
  Wallet,
  Users,
  Archive,
  Scale,
  CalendarDays,
  Coins,
  ShieldCheck,
} from "lucide-react";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AdminSecurityAPI, LedgerBooksAPI } from "@/lib/api";
import { useAdminAuthStore } from "@/stores/authStore";
import { collapseAutoRows } from "@/lib/securityRows";
import { TrialBalance } from "@/components/admin/TrialBalance";
import { CoinTrialBalance } from "@/components/admin/CoinTrialBalance";
import { DayBook } from "@/components/admin/DayBook";
import { VoucherForm } from "@/components/admin/VoucherForm";
import { AdminEntryForm } from "@/components/admin/AdminEntryForm";
import { SaCashBook } from "@/components/admin/SaCashBook";
import { cn } from "@/lib/utils";

/** Ledger columns stay blank at zero — a printed ledger never prints 0.00 in a
 *  column the line does not touch. */
function amt(v: unknown): string {
  const n = Number(v || 0);
  if (!n) return "";
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function total(v: unknown): string {
  return Number(v || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtDate(v?: string | null): string {
  if (!v) return "";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-GB").replace(/\//g, "-");
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  // Firefox ignores a click on an anchor that is not in the document, and
  // revoking synchronously can beat the download in Safari.
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** A failed PDF comes back as a Blob, not JSON — say something readable. */
function pdfError(e: any): string {
  return e?.response?.status === 404 ? "Ledger not found" : e?.message || "Could not build the PDF";
}

function hint(b: any): string {
  return b?.is_payment_mode
    ? `Payment mode "${b.name}" — every movement recorded by this mode posts here`
    : "Hand-kept — you post every line";
}

export default function LedgersPage() {
  const qc = useQueryClient();
  const [bookId, setBookId] = useState<string>("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [newOpen, setNewOpen] = useState(false);
  const [firmOpen, setFirmOpen] = useState(false);
  const [tab, setTab] = useState<
    "accounts" | "entry" | "daybook" | "coins" | "trial"
  >("accounts");

  const { data: books } = useQuery({
    queryKey: ["ledger-books"],
    queryFn: () => LedgerBooksAPI.list(),
    // Money posts itself here from other pages, so the global 60 s stale
    // window is wrong for this one — a line that has already been written
    // should be on screen, not a minute behind.
    staleTime: 0,
    refetchInterval: 15000,
  });

  const list: any[] = useMemo(() => books || [], [books]);
  const active = useMemo(
    () => list.find((b) => b.id === bookId) || list[0],
    [list, bookId],
  );

  // Everyone money has actually moved with. Picking one swaps this same table
  // over to their PARTY account — the mirror of the cash books — rather than
  // building a second screen that would drift out of step with this one.
  const { data: partyList } = useQuery({
    queryKey: ["ledger-parties"],
    queryFn: () => LedgerBooksAPI.parties(),
    staleTime: 0,
    refetchInterval: 30000,
  });
  const parties: any[] = partyList || [];
  const [party, setParty] = useState("");
  const partyName = parties.find((p) => p.code === party)?.name || party;

  // Security Money — each admin's security collateral as its own ruled
  // ledger: Received / Return / Top-up, their games' losses and wins, and the
  // brokerage drawn from it. The statement is the security service's own
  // (the same one the Security Money page prints), so the two pages can never
  // disagree. Super-admin only, like that page.
  const isSuper = useAdminAuthStore(
    (s) => String(s.admin?.role ?? "").toUpperCase() === "SUPER_ADMIN",
  );
  const { data: secList } = useQuery({
    queryKey: ["admin", "security-money"],
    queryFn: () => AdminSecurityAPI.list(),
    enabled: isSuper,
    staleTime: 0,
  });
  const secRows: any[] = secList || [];
  const [secAdmin, setSecAdmin] = useState("");
  const isSec = !!secAdmin;
  // Games and brokerage collapse to one line per day; "View all" opens them.
  const [secAll, setSecAll] = useState(false);
  const isParty = !!party && !isSec;
  const secName = (() => {
    const r = secRows.find((x) => x.admin_id === secAdmin);
    return r ? `${r.full_name || r.user_code} (${r.user_code})` : "";
  })();

  const from = () => (start ? new Date(start + "T00:00:00").toISOString() : undefined);
  const to = () => (end ? new Date(end + "T23:59:59").toISOString() : undefined);

  const { data: st, isLoading } = useQuery({
    queryKey: [
      "ledger-statement",
      isSec ? "sec:" + secAdmin : isParty ? "party:" + party : active?.id,
      start,
      end,
    ],
    queryFn: () =>
      isSec
        ? AdminSecurityAPI.statement(secAdmin, from(), to())
        : isParty
          ? LedgerBooksAPI.partyStatement(party, from(), to())
          : LedgerBooksAPI.statement(active.id, from(), to()),
    enabled: isSec || isParty || !!active?.id,
    staleTime: 0,
    refetchInterval: 6000,
  });

  const shownRows: any[] =
    isSec && !secAll ? collapseAutoRows(st?.rows || []) : st?.rows || [];

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["ledger-statement"] });
    qc.invalidateQueries({ queryKey: ["ledger-books"] });
    // A ledger flagged as a payment mode is also a dropdown entry everywhere
    // else — that list has to move at the same moment this one does.
    qc.invalidateQueries({ queryKey: ["payment-modes"] });
    qc.invalidateQueries({ queryKey: ["ledger-parties"] });
  };

  const pdf = useMutation({
    mutationFn: () =>
      isSec
        ? AdminSecurityAPI.pdf(secAdmin, from(), to())
        : isParty
          ? LedgerBooksAPI.partyPdf(party, from(), to())
          : LedgerBooksAPI.pdf(active.id, from(), to()),
    onSuccess: (blob) => {
      download(blob, `ledger-${isSec ? "security-" + secAdmin : isParty ? party : active.name}.pdf`);
      toast.success("Ledger PDF downloaded");
    },
    onError: (e: any) => toast.error(pdfError(e)),
  });

  const removeBook = useMutation({
    mutationFn: (id: string) => LedgerBooksAPI.remove(id),
    onSuccess: () => {
      toast.success("Ledger deleted");
      setBookId("");
      refresh();
    },
    onError: (e: any) => toast.error(e?.message || "Could not delete"),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Ledgers"
        description="Account statements — the money in and out of your books, ruled and totalled."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => setFirmOpen(true)}>
              <Building2 className="size-4" /> Firm header
            </Button>
            <Button size="sm" onClick={() => setNewOpen(true)}>
              <Plus className="size-4" /> New ledger
            </Button>
          </div>
        }
      />

      <div className="flex flex-wrap gap-2 border-b border-border pb-2">
        {([
          ["accounts", "Accounts", BookOpen],
          ["entry", "Admin entry", HandCoins],
          ["daybook", "Day Book", CalendarDays],
          ["coins", "Trial Balance — Coins", Coins],
          ["trial", isSuper ? "Cash Book" : "Trial Balance — Cash", isSuper ? Wallet : Scale],
        ] as const).map(([k, label, Icon]) => (
          <button
            key={k}
            type="button"
            onClick={() => setTab(k)}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition",
              tab === k
                ? "bg-primary/10 font-medium text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-4" /> {label}
          </button>
        ))}
      </div>

      {tab === "entry" && <AdminEntryForm />}

      {/* The super-admin's cash seat. An admin keeps the trial balance here —
          their own books are what "cash" means to them — while the super-admin
          gets the cash book, which is the same money read the way they run it:
          earnings, what came in, what went back, and who is holding what. */}
      {tab === "trial" && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              {isSuper ? <Wallet className="size-4" /> : <Scale className="size-4" />}{" "}
              {isSuper ? "Cash Book" : "Trial Balance"}
            </CardTitle>
            <CardDescription>
              {isSuper
                ? "Real money between you and your admins — what you earned out of each one's security, what came in, what went back, and what is still lying with them. Coins and wallet balances are not part of this book."
                : "Every account's closing balance, and the proof that debits equal credits."}
            </CardDescription>
          </CardHeader>
          <CardContent>{isSuper ? <SaCashBook /> : <TrialBalance />}</CardContent>
        </Card>
      )}

      {tab === "coins" && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Coins className="size-4" /> Trial Balance — Coins
            </CardTitle>
            <CardDescription>
              The main wallet&apos;s issuance on the credit side, and every wallet
              holding a piece of it on the debit side. Squares by identity — a coin
              exists in exactly one place, so the two sides are the same quantity
              counted twice. The Kuber pool is a separate house pool and is not
              part of this sheet.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <CoinTrialBalance />
          </CardContent>
        </Card>
      )}

      {tab === "daybook" && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <CalendarDays className="size-4" /> Day Book
            </CardTitle>
            <CardDescription>
              Every voucher in the period — one row per voucher, with both sides shown together.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <DayBook />
          </CardContent>
        </Card>
      )}

      {/* ── Which account ─────────────────────────────────────────── */}
      {tab === "accounts" && (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <BookOpen className="size-4" /> Accounts
          </CardTitle>
          <CardDescription>
            A ledger marked as a payment mode shows up wherever money is recorded, and every
            movement stamped with it posts here on its own.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            {list.map((b) => (
              <button
                key={b.id}
                type="button"
                onClick={() => { setParty(""); setSecAdmin(""); setBookId(b.id); }}
                title={hint(b)}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition",
                  !isParty && !isSec && active?.id === b.id
                    ? "border-primary bg-primary/10 font-medium text-primary"
                    : "border-border hover:border-primary/40",
                )}
              >
                {b.is_payment_mode && <Wallet className="size-3 opacity-60" />}
                {b.name}
              </button>
            ))}
            {list.length === 0 && (
              <p className="py-2 text-sm text-muted-foreground">No ledgers yet.</p>
            )}
          </div>

          {parties.length > 0 && (
            <div className="mt-4 border-t border-border pt-3">
              <div className="mb-2 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                <Users className="size-3" /> By admin
              </div>
              <div className="flex flex-wrap gap-2">
                {parties.map((p) => (
                  <button
                    key={p.code}
                    type="button"
                    onClick={() => { setSecAdmin(""); setParty(p.code); }}
                    title={"Everything that moved between you and " + p.name + ", across every ledger"}
                    className={cn(
                      "rounded-lg border px-3 py-1.5 text-sm transition",
                      isParty && party === p.code
                        ? "border-primary bg-primary/10 font-medium text-primary"
                        : "border-border hover:border-primary/40",
                    )}
                  >
                    {p.name}{" "}
                    <span className="font-mono text-[10px] opacity-60">{p.code}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {isSuper && secRows.length > 0 && (
            <div className="mt-4 border-t border-border pt-3">
              <div className="mb-2 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                <ShieldCheck className="size-3" /> Security Money
              </div>
              <div className="flex flex-wrap gap-2">
                {secRows.map((r) => (
                  <button
                    key={r.admin_id}
                    type="button"
                    onClick={() => { setParty(""); setSecAdmin(r.admin_id); }}
                    title={"Security money with " + (r.full_name || r.user_code) + " — received, returned, games and brokerage"}
                    className={cn(
                      "rounded-lg border px-3 py-1.5 text-sm transition",
                      secAdmin === r.admin_id
                        ? "border-emerald-500 bg-emerald-500/10 font-medium text-emerald-600 dark:text-emerald-400"
                        : "border-border hover:border-emerald-500/40",
                    )}
                  >
                    {r.full_name || r.user_code}{" "}
                    <span className="font-mono text-[10px] opacity-60">{r.user_code}</span>{" "}
                    <span className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">
                      {total(r.security_balance)}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
      )}

      {tab === "accounts" && (isSec || isParty || active) && (
        <Card>
          <CardHeader className="gap-3 pb-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <CardTitle className="text-base">
                {isSec ? "Security Money : " + secName : "Account : " + (isParty ? partyName : active.name)}
              </CardTitle>
              <CardDescription>
                {isSec
                  ? "Their security with you — Received / Return / Top-up, their games and your brokerage. Cr = you are holding it for them."
                  : isParty
                    ? "Their account with you, across every ledger — Dr they owe you, Cr you owe them"
                    : hint(active)}
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <div>
                <label className="text-[10px] uppercase tracking-wider text-muted-foreground">From</label>
                <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="h-9 w-[9.5rem]" />
              </div>
              <div>
                <label className="text-[10px] uppercase tracking-wider text-muted-foreground">To</label>
                <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="h-9 w-[9.5rem]" />
              </div>
              {isSec && (
                <Button variant="outline" size="sm" onClick={() => setSecAll((v) => !v)}>
                  {secAll ? "Group games & brokerage" : "View all"}
                </Button>
              )}
              <Button variant="outline" size="sm" loading={pdf.isPending} onClick={() => pdf.mutate()}>
                <Download className="size-4" /> PDF
              </Button>
              {!isParty && !isSec && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    if (confirm(`Delete the "${active.name}" ledger and all its entries?`)) {
                      removeBook.mutate(active.id);
                    }
                  }}
                >
                  <Trash2 className="size-4" />
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[52rem] text-sm">
                <thead>
                  <tr className="border-y border-border text-[11px] uppercase tracking-wider text-muted-foreground">
                    <th className="py-2 text-left font-medium">Date</th>
                    <th className="py-2 text-left font-medium">Type</th>
                    <th className="py-2 text-left font-medium">Vch No.</th>
                    <th className="py-2 text-left font-medium">Particulars</th>
                    <th className="py-2 text-left font-medium">Narration</th>
                    <th className="py-2 text-right font-medium">Debit</th>
                    <th className="py-2 text-right font-medium">Credit</th>
                    <th className="py-2 text-right font-medium">Balance</th>
                    <th className="w-8" />
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  <tr className="border-b border-border/50">
                    <td className="py-2">{fmtDate(st?.start)}</td>
                    <td colSpan={2} />
                    <td className="py-2 text-muted-foreground">Opening Balance</td>
                    <td />
                    <td className="py-2 text-right">
                      {st?.opening_side === "Dr" ? amt(st?.opening_balance) : ""}
                    </td>
                    <td className="py-2 text-right">
                      {st?.opening_side === "Cr" ? amt(st?.opening_balance) : ""}
                    </td>
                    <td className="py-2 text-right font-medium">
                      {total(st?.opening_balance)} {st?.opening_side}
                    </td>
                    <td />
                  </tr>
                  {shownRows.map((r: any, i: number) => (
                    <tr key={r.id || i} className="border-b border-border/40 hover:bg-muted/40">
                      <td className="py-2 whitespace-nowrap">{fmtDate(r.entry_date)}</td>
                      <td className="py-2">{r.voucher_type}</td>
                      <td className="py-2 font-mono text-xs">{r.voucher_no}</td>
                      <td className="py-2">{r.particulars}</td>
                      <td className="py-2 text-muted-foreground">{r.narration}</td>
                      <td className="py-2 text-right text-buy">{amt(r.debit)}</td>
                      <td className="py-2 text-right text-sell">{amt(r.credit)}</td>
                      <td className="py-2 text-right font-medium">
                        {total(r.balance)} {r.balance_side}
                      </td>
                      <td className="py-2 text-right">
                        {!isSec && !r.is_auto && <DeleteLine id={r.id} onDone={refresh} />}
                      </td>
                    </tr>
                  ))}
                  {isLoading && (
                    <tr>
                      <td colSpan={9} className="py-6 text-center text-muted-foreground">Loading…</td>
                    </tr>
                  )}
                  {!isLoading && (st?.rows || []).length === 0 && (
                    <tr>
                      <td colSpan={9} className="py-6 text-center text-muted-foreground">
                        No entries in this period.
                      </td>
                    </tr>
                  )}
                </tbody>
                <tfoot className="tabular-nums">
                  <tr className="border-t border-border font-medium">
                    <td colSpan={5} className="py-2 text-right text-muted-foreground">Total</td>
                    <td className="py-2 text-right">{total(st?.total_debit)}</td>
                    <td className="py-2 text-right">{total(st?.total_credit)}</td>
                    <td colSpan={2} />
                  </tr>
                  <tr>
                    <td colSpan={5} className="py-1 text-right text-muted-foreground">
                      {st?.closing_side === "Dr" ? "Debit Balance" : "Credit Balance"}
                    </td>
                    <td className="py-1 text-right">
                      {st?.closing_side === "Cr" ? total(st?.closing_balance) : ""}
                    </td>
                    <td className="py-1 text-right">
                      {st?.closing_side === "Dr" ? total(st?.closing_balance) : ""}
                    </td>
                    <td colSpan={2} />
                  </tr>
                  <tr className="border-t border-border font-bold">
                    <td colSpan={5} className="py-2 text-right">Grand Total</td>
                    <td className="py-2 text-right">{total(st?.grand_total)}</td>
                    <td className="py-2 text-right">{total(st?.grand_total)}</td>
                    <td colSpan={2} />
                  </tr>
                </tfoot>
              </table>
            </div>

            {!isParty && !isSec && <VoucherForm books={list} onDone={refresh} />}
            {!isParty && !isSec && <NewEntry bookId={active.id} onDone={refresh} />}

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
              <p className="text-xs text-muted-foreground">
                {start || end
                  ? "Downloads exactly the period shown above."
                  : "Downloads every entry. Set a From / To date to print a period."}
              </p>
              <Button size="sm" loading={pdf.isPending} onClick={() => pdf.mutate()}>
                <Download className="size-4" /> Download PDF
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <NewLedgerDialog open={newOpen} onOpenChange={setNewOpen} onDone={(id) => { setBookId(id); refresh(); }} />
      <FirmDialog open={firmOpen} onOpenChange={setFirmOpen} />
    </div>
  );
}

/* ── Post a line by hand ─────────────────────────────────────────── */
function NewEntry({ bookId, onDone }: { bookId: string; onDone: () => void }) {
  const [date, setDate] = useState(today());
  const [vtype, setVtype] = useState("Rcpt");
  const [vno, setVno] = useState("");
  const [particulars, setParticulars] = useState("");
  const [narration, setNarration] = useState("");
  const [debit, setDebit] = useState("");
  const [credit, setCredit] = useState("");

  const post = useMutation({
    mutationFn: () =>
      LedgerBooksAPI.addEntry(bookId, {
        entry_date: new Date(date + "T00:00:00").toISOString(),
        debit: Number(debit) || 0,
        credit: Number(credit) || 0,
        voucher_type: vtype,
        voucher_no: vno,
        particulars,
        narration,
      }),
    onSuccess: () => {
      toast.success("Entry posted");
      setVno(""); setParticulars(""); setNarration(""); setDebit(""); setCredit("");
      onDone();
    },
    onError: (e: any) => toast.error(e?.message || "Could not post the entry"),
  });

  // One side or the other — a line with both filled has no meaningful balance,
  // so the form refuses it before the API has to.
  const dr = Number(debit) || 0;
  const cr = Number(credit) || 0;
  const valid = date && (dr > 0) !== (cr > 0);

  return (
    <div className="rounded-xl border border-border/60 bg-muted/30 p-3">
      <div className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground">Add an entry</div>
      <div className="grid gap-2 md:grid-cols-12">
        <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-9 md:col-span-2" />
        <select
          value={vtype}
          onChange={(e) => setVtype(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm outline-none focus:ring-1 focus:ring-ring md:col-span-1"
        >
          <option value="Rcpt">Rcpt</option>
          <option value="Pymt">Pymt</option>
          <option value="Jrnl">Jrnl</option>
        </select>
        <Input value={vno} onChange={(e) => setVno(e.target.value)} placeholder="Vch no." className="h-9 md:col-span-2" />
        <Input value={particulars} onChange={(e) => setParticulars(e.target.value)} placeholder="Particulars" className="h-9 md:col-span-2" />
        <Input value={narration} onChange={(e) => setNarration(e.target.value)} placeholder="Narration" className="h-9 md:col-span-2" />
        <Input
          value={debit}
          onChange={(e) => { setDebit(e.target.value); if (e.target.value) setCredit(""); }}
          placeholder="Debit"
          inputMode="decimal"
          className="h-9 md:col-span-1"
        />
        <Input
          value={credit}
          onChange={(e) => { setCredit(e.target.value); if (e.target.value) setDebit(""); }}
          placeholder="Credit"
          inputMode="decimal"
          className="h-9 md:col-span-1"
        />
        <Button size="sm" disabled={!valid} loading={post.isPending} onClick={() => post.mutate()} className="md:col-span-1">
          <Plus className="size-4" />
        </Button>
      </div>
    </div>
  );
}

function DeleteLine({ id, onDone }: { id: string; onDone: () => void }) {
  const del = useMutation({
    mutationFn: () => LedgerBooksAPI.removeEntry(id),
    onSuccess: () => { toast.success("Entry removed"); onDone(); },
    onError: (e: any) => toast.error(e?.message || "Could not remove"),
  });
  return (
    <button
      type="button"
      onClick={() => del.mutate()}
      className="text-muted-foreground transition hover:text-sell"
      title="Remove this entry"
    >
      <Trash2 className="size-3.5" />
    </button>
  );
}

/* ── Create a ledger ─────────────────────────────────────────────── */
function NewLedgerDialog({
  open, onOpenChange, onDone,
}: { open: boolean; onOpenChange: (v: boolean) => void; onDone: (id: string) => void }) {
  const [name, setName] = useState("");
  const [isMode, setIsMode] = useState(true);
  const [acctType, setAcctType] = useState("CASH");
  const [opening, setOpening] = useState("");
  const [side, setSide] = useState<"Dr" | "Cr">("Dr");
  const [openDate, setOpenDate] = useState(today());
  const [note, setNote] = useState("");

  const create = useMutation({
    mutationFn: () =>
      LedgerBooksAPI.create({
        name,
        is_payment_mode: isMode,
        account_type: acctType,
        // Stored signed like a debit, so the statement can just add it up.
        opening_balance: (Number(opening) || 0) * (side === "Cr" ? -1 : 1),
        opening_date: new Date(openDate + "T00:00:00").toISOString(),
        note,
      }),
    onSuccess: (r) => {
      toast.success(`"${name}" created`);
      setName(""); setOpening(""); setNote(""); setIsMode(true); setAcctType("CASH");
      onOpenChange(false);
      onDone(r?.id);
    },
    onError: (e: any) => toast.error(e?.message || "Could not create the ledger"),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New ledger</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground">Account name</label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={isMode ? "Cash / Cheque / HDFC Bank …" : "M/S DEEPAK ENTERPRISES"}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Account type</label>
            <select
              value={acctType}
              onChange={(e) => setAcctType(e.target.value)}
              className="h-10 w-full rounded-md border border-input bg-background px-2 text-sm outline-none focus:ring-1 focus:ring-ring"
            >
              <option value="CASH">Cash</option>
              <option value="BANK">Bank</option>
              <option value="PARTY">Party (3rd party / admin)</option>
              <option value="EXPENSE">Expense</option>
              <option value="OTHER">Other</option>
            </select>
          </div>
          <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-border/60 bg-muted/30 p-2.5">
            <input
              type="checkbox"
              checked={isMode}
              onChange={(e) => setIsMode(e.target.checked)}
              className="mt-0.5 size-4 accent-current"
            />
            <span className="text-xs">
              <span className="font-medium">Use as a payment mode</span>
              <span className="block text-muted-foreground">
                Offered wherever money is recorded. Movements marked with it post here on their own.
              </span>
            </span>
          </label>
          <div className="grid grid-cols-3 gap-2">
            <div className="col-span-2">
              <label className="text-xs text-muted-foreground">Opening balance</label>
              <Input value={opening} onChange={(e) => setOpening(e.target.value)} placeholder="0.00" inputMode="decimal" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Side</label>
              <select
                value={side}
                onChange={(e) => setSide(e.target.value as "Dr" | "Cr")}
                className="h-10 w-full rounded-md border border-input bg-background px-2 text-sm outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="Dr">Dr</option>
                <option value="Cr">Cr</option>
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Opening as on</label>
            <Input type="date" value={openDate} onChange={(e) => setOpenDate(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Note</label>
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional" />
          </div>
          <Button className="w-full" disabled={!name.trim()} loading={create.isPending} onClick={() => create.mutate()}>
            Create ledger
          </Button>
          <p className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
            <Archive className="mt-0.5 size-3 shrink-0" />
            The name is what everyone sees in the mode dropdowns. It can be renamed later without
            disturbing a single entry already recorded under it.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* ── The header printed on the PDF ───────────────────────────────── */
function FirmDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["ledger-firm"], queryFn: () => LedgerBooksAPI.getFirm(), enabled: open });
  const [name, setName] = useState<string | null>(null);
  const [address, setAddress] = useState<string | null>(null);
  const [statutory, setStatutory] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () =>
      LedgerBooksAPI.setFirm({
        name: name ?? data?.name ?? "",
        address: address ?? data?.address ?? "",
        statutory: statutory ?? data?.statutory ?? "",
      }),
    onSuccess: () => {
      toast.success("Header saved");
      qc.invalidateQueries({ queryKey: ["ledger-firm"] });
      onOpenChange(false);
    },
    onError: (e: any) => toast.error(e?.message || "Could not save"),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Firm header</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">Printed at the top of every ledger PDF.</p>
          <div>
            <label className="text-xs text-muted-foreground">Firm name</label>
            <Input value={name ?? data?.name ?? ""} onChange={(e) => setName(e.target.value)} placeholder="V N AGENCIES PVT LTD" />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Address</label>
            <Input value={address ?? data?.address ?? ""} onChange={(e) => setAddress(e.target.value)} placeholder="WZ-250B, MAIN ROAD, NEW DELHI-110059" />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">CIN / GSTIN line</label>
            <Input value={statutory ?? data?.statutory ?? ""} onChange={(e) => setStatutory(e.target.value)} placeholder="CIN : … ; GSTIN : …" />
          </div>
          <Button className="w-full" loading={save.isPending} onClick={() => save.mutate()}>Save header</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
