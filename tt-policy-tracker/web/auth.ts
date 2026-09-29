import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import { isAllowedEmail } from "./lib/allowed-email";

// Env (set on Vercel, never in code): AUTH_SECRET, AUTH_GOOGLE_ID, AUTH_GOOGLE_SECRET.
// Auth.js reads them by name. Callback URL: <site>/api/auth/callback/google.
export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
  trustHost: true,
  session: { strategy: "jwt" },
  pages: { signIn: "/signin", error: "/signin" },
  callbacks: {
    async signIn({ account, profile }) {
      if (account?.provider !== "google") return false;
      // false -> Auth.js redirects to /signin?error=AccessDenied
      return isAllowedEmail(profile?.email, profile?.email_verified, profile?.hd);
    },
  },
});
