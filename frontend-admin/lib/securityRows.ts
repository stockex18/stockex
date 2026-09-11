/**
 * Collapse the automatic rows of a security statement — every games result
 * and every brokerage draw is its own row, hundreds a day on a busy book —
 * into one line per type per IST day. Consecutive rows only, so the running
 * balance on each summary line is exactly the balance after its last row and
 * the ledger still adds up. Manual rows (Received / Return / Top-up) stay
 * as they are. "View all" shows the raw rows.
 */

function istDay(v?: string | null): string {
  if (!v) return "";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

const fmt = (n: number) =>
  n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function collapseAutoRows(rows: any[]): any[] {
  const out: any[] = [];
  for (const r of rows) {
    const day = istDay(r.entry_date);
    const last = out[out.length - 1];
    if (r.is_auto && last?._group && last.voucher_type === r.voucher_type && last._day === day) {
      last._n += 1;
      last._dr += Number(r.debit || 0);
      last._cr += Number(r.credit || 0);
      last.balance = r.balance;
      last.balance_side = r.balance_side;
      last.payable_balance = r.payable_balance;
      continue;
    }
    if (r.is_auto) {
      out.push({
        ...r,
        id: "g:" + r.id,
        _group: true,
        _first: r,
        _day: day,
        _n: 1,
        _dr: Number(r.debit || 0),
        _cr: Number(r.credit || 0),
      });
    } else {
      out.push(r);
    }
  }
  return out.map((g) => {
    if (!g._group) return g;
    if (g._n === 1) return g._first;
    const games = String(g.voucher_type).toLowerCase().startsWith("game");
    return {
      ...g,
      voucher_no: "",
      client_name: "",
      client_code: "",
      particulars: `${g.voucher_type} · ${g._n} entries`,
      narration: games
        ? `Users lost ${fmt(g._dr)} · users won ${fmt(g._cr)}`
        : `Brokerage drawn ${fmt(g._dr)}`,
      debit: String(g._dr.toFixed(2)),
      credit: String(g._cr.toFixed(2)),
    };
  });
}
