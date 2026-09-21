"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, Coins, HandCoins, Landmark, RefreshCw, Wallet } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { SaLedgerAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * The super-admin's CASH book — real money only, never coins.
 *
 * Two streams, shown apart because the operator runs them apart:
 *
 *   SECURITY — the admin lodges cash as collateral, and what is left goes
 *              back when they withdraw.
 *   BOOKS    — the super-admin's own cash / bank / cheque books: the receipts
 *              and payments written by hand against those accounts.
 *
 * Brokerage, the P&L share and the games result are NOT here. Charging them
 * moves no money — they are earned, and they are read in the trial balance,
 * where each admin's account carries what they owe against them.
 *
 * Laid out the way a ledger is read rather than the way the data arrives:
 * what came in, what went out, and who it was with.
 */

const inr = (n: number) =>
  Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Which of the five arrangements an admin is on.
 *
 * The backend reads this off the same fields the money is actually split by,
 * so the badge cannot drift from what the admin is really charged. Hovering
 * gives the whole rule in a sentence. */
function AdminTypeBadge({ t }: { t: any }) {
  if (!t?.n) return null;
  return (
    <span
      title={t.detail || t.label}
      className="mt-0.5 inline-flex w-fit items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary ring-1 ring-primary/25"
    >
      <span className="rounded-sm bg-primary/20 px-1 leading-4">{t.n}</span>
      {t.label}
    </span>
  );
}

function Amount({ value, className }: { value: number; className?: string }) {
  const v = Number(value || 0);
  return (
    <span
      className={cn(
        "font-tabular tabular-nums",
        v < 0 ? "text-destructive" : undefined,
        className,
      )}
    >
      {inr(v)}
    </span>
  );
}

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: number;
  hint?: string;
  tone?: "in" | "out" | "earn";
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-card px-3 py-2.5">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div
        className={cn(
          "font-tabular text-lg font-semibold tabular-nums",
          tone === "earn" && "text-emerald-600 dark:text-emerald-400",
          tone === "out" && "text-destructive",
        )}
      >
        🪙{inr(value)}
      </div>
      {hint ? <div className="text-[11px] text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

function SectionTitle({ icon: Icon, children, note }: { icon: any; children: React.ReactNode; note?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border pb-1.5">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold">
        <Icon className="size-4 text-primary" /> {children}
      </h3>
      {note ? <span className="text-[11px] text-muted-foreground">{note}</span> : null}
    </div>
  );
}

/**
 * What the super-admin earned off ONE admin, opened from their row.
 *
 * The cash book above it answers "what changed hands". This answers the
 * question the operator actually argues with an admin about: where did it
 * come from — their book's P&L, the brokerage on their users' trades, or the
 * games. Read off the security ledger, the same rows the income accounts are
 * posted from, so it cannot disagree with the trial balance.
 */
function AdminEarningsDialog({
  adminId,
  from,
  to,
  onClose,
}: {
  adminId: string | null;
  from: string;
  to: string;
  onClose: () => void;
}) {
  const { data, isFetching } = useQuery<any>({
    queryKey: ["sa-admin-earnings", adminId, from, to],
    queryFn: () =>
      SaLedgerAPI.adminEarnings(adminId as string, {
        date_from: from || undefined,
        date_to: to || undefined,
      }),
    enabled: !!adminId,
    staleTime: 15_000,
  });

  const t = data?.totals ?? {};
  const g = data?.games_split ?? {};
  const who = data?.admin;
  const days: any[] = data?.days ?? [];
  const lines: any[] = data?.lines ?? [];

  return (
    <Dialog open={!!adminId} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {who?.full_name || "Admin"}
            {!!who?.admin_type?.n && (
              <span
                title={who.admin_type.detail}
                className="inline-flex items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary ring-1 ring-primary/25"
              >
                <span className="rounded-sm bg-primary/20 px-1 leading-4">{who.admin_type.n}</span>
                {who.admin_type.label}
              </span>
            )}
          </DialogTitle>
          <DialogDescription>
            What you earned off {who?.user_code || "this admin"}, and where it came from.
            {from || to ? " For the period shown." : " Whole book."}
          </DialogDescription>
        </DialogHeader>

        {isFetching && !data ? (
          <p className="py-8 text-center text-sm text-muted-foreground">Reading the ledger…</p>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="P&L share" value={t.pnl_share ?? 0} tone="earn" hint="your cut of their book" />
              <Stat label="Brokerage" value={t.brokerage ?? 0} tone="earn" hint="on their users' trades" />
              <Stat label="Games" value={t.games ?? 0} tone="earn" hint="house result" />
              <Stat label="Total earned" value={t.earned ?? 0} tone="earn" />
            </div>

            {/* Netting the two directions hides the story, so show both. */}
            {!!(g.collected || g.paid_out) && (
              <p className="text-[11px] text-muted-foreground">
                Games in detail — collected 🪙{inr(g.collected ?? 0)}, paid out on wins 🪙
                {inr(g.paid_out ?? 0)}.
              </p>
            )}

            <div className="grid grid-cols-2 gap-2">
              <Stat label="Security held now" value={data?.security_balance ?? 0} hint="their collateral with you" />
              <Stat label="Payable now" value={data?.payable_balance ?? 0} tone="out" hint="owed back to them" />
            </div>

            {days.length > 0 && (
              <section className="space-y-2">
                <SectionTitle icon={CalendarDays} note="most recent first">
                  Day by day
                </SectionTitle>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[520px] text-sm">
                    <thead>
                      <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                        <th className="py-1.5 text-left font-medium">Date</th>
                        <th className="py-1.5 text-right font-medium">P&amp;L share</th>
                        <th className="py-1.5 text-right font-medium">Brokerage</th>
                        <th className="py-1.5 text-right font-medium">Games</th>
                        <th className="py-1.5 text-right font-medium">Earned</th>
                      </tr>
                    </thead>
                    <tbody>
                      {days.map((d) => (
                        <tr key={d.date} className="border-b border-border/40">
                          <td className="py-1.5 font-mono text-[12px]">{d.date}</td>
                          <td className="py-1.5 text-right"><Amount value={d.pnl_share} /></td>
                          <td className="py-1.5 text-right"><Amount value={d.brokerage} /></td>
                          <td className="py-1.5 text-right"><Amount value={d.games} /></td>
                          <td className="py-1.5 text-right font-semibold"><Amount value={d.earned} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {lines.length > 0 && (
              <section className="space-y-2">
                <SectionTitle icon={CalendarDays} note={`latest ${lines.length} lines`}>
                  Every line
                </SectionTitle>
                <div className="max-h-72 overflow-y-auto">
                  <table className="w-full min-w-[520px] text-sm">
                    <tbody>
                      {lines.map((l, i) => (
                        <tr key={i} className="border-b border-border/40">
                          <td className="py-1.5 font-mono text-[11px] text-muted-foreground">
                            {new Date(l.date).toLocaleString("en-IN", {
                              day: "2-digit",
                              month: "short",
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </td>
                          <td className="py-1.5">
                            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                              {l.stream === "pnl_share"
                                ? "P&L share"
                                : l.stream === "brokerage"
                                  ? "Brokerage"
                                  : "Games"}
                            </span>
                          </td>
                          <td className="py-1.5 text-[12px]">{l.narration}</td>
                          <td className="py-1.5 text-right"><Amount value={l.amount} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {!lines.length && (
              <p className="py-6 text-center text-sm text-muted-foreground">
                Nothing earned off this admin in this period.
              </p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}


export function SaCashBook() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  // Which admin the operator opened the earnings breakdown for.
  const [drill, setDrill] = useState<string | null>(null);

  const { data, isFetching, refetch } = useQuery<any>({
    queryKey: ["sa-cash-book", from, to],
    queryFn: () => SaLedgerAPI.cashBook({ date_from: from || undefined, date_to: to || undefined }),
    staleTime: 15_000,
  });

  const t = data?.totals ?? {};
  const admins: any[] = data?.admins ?? [];
  const books: any[] = data?.books ?? [];
  const days: any[] = data?.days ?? [];
  const entries: any[] = data?.entries ?? [];

  const withActivity = useMemo(
    () =>
      admins.filter(
        (a) => a.cash_in || a.cash_out || a.security_balance || a.payable_balance,
      ),
    [admins],
  );

  return (
    <div className="space-y-5">
      {/* Period */}
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">From</div>
          <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-9 w-[160px]" />
        </div>
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">To</div>
          <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-9 w-[160px]" />
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw className={cn("size-4", isFetching && "animate-spin")} /> Refresh
        </Button>
        {(from || to) && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setFrom("");
              setTo("");
            }}
          >
            Whole book
          </Button>
        )}
        <span className="ml-auto text-[11px] text-muted-foreground">
          Real cash only — coins and wallet balances are not part of this book.
        </span>
      </div>

      {/* Earnings are not cash. Say where they went, once. */}
      <p className="flex items-start gap-1.5 rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground">
        <Coins className="mt-0.5 size-3.5 shrink-0" />
        <span>
          Brokerage, P&amp;L share and games are <strong>earned, not received</strong> — charging
          them moves no money, so they are not in this book. They post to the income accounts
          against each admin&apos;s own account, and the Trial Balance is where they are read and
          reconciled.
        </span>
      </p>

      {/* Cash with the admins */}
      <section className="space-y-2">
        <SectionTitle icon={Wallet} note="security lodged with the super-admin">
          Security money
        </SectionTitle>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Received" value={t.cash_in ?? 0} hint="admin → super-admin" />
          <Stat label="Returned / funded" value={t.cash_out ?? 0} tone="out" hint="super-admin → admin" />
          <Stat label="Held now" value={t.security_balance ?? 0} hint="closing collateral" />
          <Stat label="Payable" value={t.payable_balance ?? 0} tone="out" hint="owed back to admins" />
        </div>
      </section>

      {/* The super-admin's own books */}
      <section className="space-y-2">
        <SectionTitle icon={Landmark} note="cash / bank / cheque accounts">
          Books
        </SectionTitle>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Stat label="Receipts" value={t.book_receipts ?? 0} />
          <Stat label="Payments" value={t.book_payments ?? 0} tone="out" />
          <Stat label="Net" value={t.book_net ?? 0} />
        </div>
        {books.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-1.5 text-left font-medium">Account</th>
                  <th className="py-1.5 text-right font-medium">Receipts</th>
                  <th className="py-1.5 text-right font-medium">Payments</th>
                  <th className="py-1.5 text-right font-medium">Net</th>
                </tr>
              </thead>
              <tbody>
                {books.map((b) => (
                  <tr key={b.name} className="border-b border-border/40">
                    <td className="py-1.5">{b.name}</td>
                    <td className="py-1.5 text-right"><Amount value={b.receipts} /></td>
                    <td className="py-1.5 text-right"><Amount value={b.payments} /></td>
                    <td className="py-1.5 text-right font-semibold"><Amount value={b.net} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Admin by admin */}
      <section className="space-y-2">
        <SectionTitle icon={HandCoins} note="click a row for what you earned off them">
          Admin accounts
        </SectionTitle>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-sm">
            <thead>
              <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                <th className="py-1.5 text-left font-medium">Admin</th>
                <th className="py-1.5 text-right font-medium">Cash in</th>
                <th className="py-1.5 text-right font-medium">Cash out</th>
                <th className="py-1.5 text-right font-medium">Held</th>
                <th className="py-1.5 text-right font-medium">Payable</th>
              </tr>
            </thead>
            <tbody>
              {withActivity.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-6 text-center text-muted-foreground">
                    {isFetching ? "Reading the book…" : "Nothing in this period."}
                  </td>
                </tr>
              ) : (
                withActivity.map((a) => (
                  <tr
                    key={a.admin_id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setDrill(a.admin_id)}
                    onKeyDown={(e) => { if (e.key === "Enter") setDrill(a.admin_id); }}
                    title="Open what you earned off this admin — P&L share, brokerage, games"
                    className="cursor-pointer border-b border-border/40 transition-colors hover:bg-muted/30"
                  >
                    <td className="py-1.5">
                      <span className="block font-medium">{a.admin_name}</span>
                      <span className="block font-mono text-[11px] text-muted-foreground">{a.admin_code}</span>
                      <AdminTypeBadge t={a.admin_type} />
                    </td>
                    <td className="py-1.5 text-right"><Amount value={a.cash_in} /></td>
                    <td className="py-1.5 text-right"><Amount value={a.cash_out} /></td>
                    <td className="py-1.5 text-right"><Amount value={a.security_balance} /></td>
                    <td className="py-1.5 text-right"><Amount value={a.payable_balance} /></td>
                  </tr>
                ))
              )}
            </tbody>
            {withActivity.length > 0 && (
              <tfoot>
                <tr className="border-t-2 border-border font-semibold">
                  <td className="py-2">Total</td>
                  <td className="py-2 text-right"><Amount value={t.cash_in ?? 0} /></td>
                  <td className="py-2 text-right"><Amount value={t.cash_out ?? 0} /></td>
                  <td className="py-2 text-right"><Amount value={t.security_balance ?? 0} /></td>
                  <td className="py-2 text-right"><Amount value={t.payable_balance ?? 0} /></td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </section>

      {/* Day by day */}
      {days.length > 0 && (
        <section className="space-y-2">
          <SectionTitle icon={CalendarDays} note="most recent first">
            Day book
          </SectionTitle>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-1.5 text-left font-medium">Date</th>
                  <th className="py-1.5 text-right font-medium">Cash in</th>
                  <th className="py-1.5 text-right font-medium">Cash out</th>
                </tr>
              </thead>
              <tbody>
                {days.map((d) => (
                  <tr key={d.date} className="border-b border-border/40">
                    <td className="py-1.5 font-mono text-[12px]">{d.date}</td>
                    <td className="py-1.5 text-right"><Amount value={d.cash_in} /></td>
                    <td className="py-1.5 text-right"><Amount value={d.cash_out} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* The lines themselves */}
      {entries.length > 0 && (
        <section className="space-y-2">
          <SectionTitle icon={CalendarDays} note={`latest ${entries.length} lines`}>
            Statement
          </SectionTitle>
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-1.5 text-left font-medium">Date</th>
                  <th className="py-1.5 text-left font-medium">With</th>
                  <th className="py-1.5 text-left font-medium">Particulars</th>
                  <th className="py-1.5 text-right font-medium">Amount</th>
                  <th className="py-1.5 text-right font-medium">Balance</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e, i) => (
                  <tr key={i} className="border-b border-border/40">
                    <td className="whitespace-nowrap py-1.5 font-mono text-[11px]">
                      {new Date(e.date).toLocaleString("en-IN", {
                        day: "2-digit",
                        month: "short",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </td>
                    <td className="py-1.5">
                      <span className="block">{e.name}</span>
                      {e.code ? (
                        <span className="block font-mono text-[10px] text-muted-foreground">{e.code}</span>
                      ) : null}
                    </td>
                    <td className="py-1.5">
                      <span
                        className={cn(
                          "mr-1.5 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                          e.stream === "SECURITY"
                            ? "bg-primary/10 text-primary"
                            : "bg-muted text-muted-foreground",
                        )}
                      >
                        {e.type}
                      </span>
                      <span className="text-muted-foreground">{e.narration}</span>
                    </td>
                    <td className="py-1.5 text-right"><Amount value={e.amount} /></td>
                    <td className="py-1.5 text-right text-muted-foreground">
                      {e.balance_after == null ? "—" : <Amount value={e.balance_after} />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <AdminEarningsDialog
        adminId={drill}
        from={from}
        to={to}
        onClose={() => setDrill(null)}
      />
    </div>
  );
}
