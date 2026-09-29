// Who may sign in to Jeanne Machine. Kept free of Next/Auth.js imports so it
// can be unit tested with `node --test`.

export const ALLOWED_DOMAIN = "turbotenant.com";

export const DENIAL_MESSAGE = "Only turbotenant.com Google accounts can sign in.";

/**
 * Google sign-in rule: a verified email ending "@turbotenant.com" (lowercase
 * compare) AND the hosted-domain claim `hd` equal to turbotenant.com. `hd` is
 * required: a consumer Google account made on a turbotenant.com address has no
 * `hd` and is refused.
 */
export function isAllowedEmail(
  email: unknown,
  emailVerified: unknown,
  hd?: unknown,
): boolean {
  if (emailVerified !== true) return false;
  if (typeof email !== "string") return false;
  if (!email.trim().toLowerCase().endsWith(`@${ALLOWED_DOMAIN}`)) return false;
  if (typeof hd !== "string" || hd.trim().toLowerCase() !== ALLOWED_DOMAIN) return false;
  return true;
}

/** Second check on an existing session (middleware and the /backend proxy). */
export function isAllowedSessionEmail(email: unknown): boolean {
  return typeof email === "string" && email.trim().toLowerCase().endsWith(`@${ALLOWED_DOMAIN}`);
}

/**
 * Post-sign-in redirect target. Resolves `raw` against the site and keeps it
 * only when it stays on the same origin, so "//evil.com", "/\\evil.com" and
 * absolute URLs all fall back to "/".
 */
export function safeCallback(raw: unknown): string {
  if (typeof raw !== "string" || raw === "") return "/";
  const base = new URL("https://site.invalid");
  let u: URL;
  try {
    u = new URL(raw, base);
  } catch {
    return "/";
  }
  if (u.origin !== base.origin) return "/";
  return u.pathname + u.search + u.hash;
}
