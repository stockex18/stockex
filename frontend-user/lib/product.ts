/**
 * How a product type reads on screen. CNC is "Delivery" to a user, and a
 * pledged delivery (backend pledge_service) says so — the shares back F&O
 * margin, which is worth being able to see on the position itself.
 */
type ProductRow = { product_type?: string | null; is_pledge?: boolean | null } | null | undefined;

export function productLabel(r: ProductRow): string {
  const p = String(r?.product_type || "MIS").toUpperCase();
  if (p === "CNC") return r?.is_pledge ? "Delivery · Pledged" : "Delivery";
  return p;
}

/** One-letter form for tight table columns: M / N / D. */
export function productShort(r: ProductRow): string {
  const p = String(r?.product_type || "MIS").toUpperCase();
  return p === "CNC" ? "D" : p.slice(0, 1);
}
