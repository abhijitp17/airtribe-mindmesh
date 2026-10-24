/** Which sign-in the web app uses. Set at build time; must match the API's AUTH_PROVIDER.
 *  local: email + password against the API (dev, tests, offline). clerk: Clerk (Google, LinkedIn, email). */
export const AUTH_PROVIDER: "local" | "clerk" = process.env.NEXT_PUBLIC_AUTH_PROVIDER === "clerk" ? "clerk" : "local";
export const isClerk = AUTH_PROVIDER === "clerk";
export const SIGN_IN_PATH = isClerk ? "/sign-in" : "/login";
export const SIGN_UP_PATH = isClerk ? "/sign-up" : "/login?mode=signup";

/** A signed-out gap report waiting to be saved after sign-up (survives the OAuth redirect). */
export const PENDING_REPORT_KEY = "mindmesh_report_token";

export function rememberReport(token: string): void {
  try {
    window.sessionStorage.setItem(PENDING_REPORT_KEY, token);
  } catch {
    // Storage blocked: the report can't be carried across sign-up; the user can make it again.
  }
}

export function takePendingReport(): string | null {
  try {
    const t = window.sessionStorage.getItem(PENDING_REPORT_KEY);
    window.sessionStorage.removeItem(PENDING_REPORT_KEY);
    return t;
  } catch {
    return null;
  }
}
