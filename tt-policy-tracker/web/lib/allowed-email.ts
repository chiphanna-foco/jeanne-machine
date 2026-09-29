// Who may sign in to Jeanne Machine. Kept free of Next/Auth.js imports so it
// can be unit tested with `node --test`.

export const ALLOWED_DOMAIN = "turbotenant.com";

export const DENIAL_MESSAGE = "Only turbotenant.com Google accounts can sign in.";

/**
 * Google sign-in rule: a verified email ending "@turbotenant.com" (lowercase
 * compare). When Google sends the hosted-domain claim `hd`, it must also be
 * turbotenant.com.
 */
export function isAllowedEmail(
  email: unknown,
  emailVerified: unknown,
  hd?: unknown,
): boolean {
  if (emailVerified !== true) return false;
  if (typeof email !== "string") return false;
  if (!email.trim().toLowerCase().endsWith(`@${ALLOWED_DOMAIN}`)) return false;
  if (hd !== undefined && hd !== null) {
    if (typeof hd !== "string" || hd.trim().toLowerCase() !== ALLOWED_DOMAIN) return false;
  }
  return true;
}

/** Second check on an existing session (middleware and the /backend proxy). */
export function isAllowedSessionEmail(email: unknown): boolean {
  return typeof email === "string" && email.trim().toLowerCase().endsWith(`@${ALLOWED_DOMAIN}`);
}
