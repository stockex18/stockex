/**
 * Which login page this device belongs to — the broker login or the admin one.
 *
 * Both are separate doors onto the same panel, each installable as its own
 * app. Everything that sends someone back to a login page (sign-out, an
 * expired session, the auth guard) has to send a broker to the BROKER login:
 * the admin login now refuses brokers, so landing there would be a dead end.
 *
 * Remembered from the signed-in role, not from which page was used, so a
 * broker already signed in before the split is routed correctly too.
 */

export type Portal = "admin" | "broker";

export const PORTAL_KEY = "nb.admin.portal";

export const LOGIN_PATHS: Record<Portal, string> = {
  admin: "/login",
  broker: "/broker/login",
};

export function portalForRole(role: string | null | undefined): Portal {
  return String(role || "").toUpperCase() === "BROKER" ? "broker" : "admin";
}

export function rememberPortal(p: Portal): void {
  try {
    if (typeof window !== "undefined") window.localStorage.setItem(PORTAL_KEY, p);
  } catch {
    // Private mode / blocked storage — fall back to the admin login.
  }
}

export function lastPortal(): Portal {
  try {
    if (typeof window !== "undefined" && window.localStorage.getItem(PORTAL_KEY) === "broker") {
      return "broker";
    }
  } catch {
    // ignore
  }
  return "admin";
}

/** Where to send this device when it needs to sign in again. Pass the role if
 *  you still have it — it beats the remembered hint. */
export function loginPath(role?: string | null): string {
  return LOGIN_PATHS[role ? portalForRole(role) : lastPortal()];
}

/** True on either login page — used to avoid redirecting a login page to itself. */
export function isLoginPath(pathname: string): boolean {
  return pathname.startsWith("/login") || pathname.startsWith("/broker/login");
}
