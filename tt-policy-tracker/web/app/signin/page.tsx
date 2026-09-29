import { redirect } from "next/navigation";
import { auth, signIn } from "@/auth";
import { DENIAL_MESSAGE, isAllowedSessionEmail, safeCallback } from "@/lib/allowed-email";

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string; error?: string }>;
}) {
  const { callbackUrl, error } = await searchParams;
  const target = safeCallback(callbackUrl);

  const session = await auth();
  if (isAllowedSessionEmail(session?.user?.email)) redirect(target);

  const denied = error === "AccessDenied";

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
        background: "linear-gradient(135deg, #0f0724 0%, #1e1b4b 40%, #0b1120 100%)",
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 400,
          background: "#fff",
          borderRadius: 16,
          padding: "32px 28px",
          boxShadow: "0 24px 60px rgba(0,0,0,0.35)",
          textAlign: "center",
        }}
      >
        <h1 style={{ fontSize: 24, fontWeight: 800, margin: "0 0 6px" }}>Jeanne Machine</h1>
        <p style={{ color: "#64748b", fontSize: 14, margin: "0 0 24px" }}>
          Sign in with your TurboTenant Google account.
        </p>

        {denied && (
          <p
            role="alert"
            style={{
              background: "#fef2f2",
              color: "#b91c1c",
              border: "1px solid #fecaca",
              borderRadius: 10,
              padding: "10px 12px",
              fontSize: 14,
              fontWeight: 600,
              margin: "0 0 20px",
            }}
          >
            {DENIAL_MESSAGE}
          </p>
        )}
        {error && !denied && (
          <p role="alert" style={{ color: "#b91c1c", fontSize: 14, margin: "0 0 20px" }}>
            Sign-in failed ({error}). Please try again.
          </p>
        )}

        <form
          action={async () => {
            "use server";
            await signIn("google", { redirectTo: target });
          }}
        >
          <button
            type="submit"
            style={{
              width: "100%",
              padding: "12px 16px",
              fontSize: 15,
              fontWeight: 700,
              color: "#fff",
              background: "linear-gradient(135deg, #7c3aed 0%, #ec4899 100%)",
              border: "none",
              borderRadius: 10,
              cursor: "pointer",
            }}
          >
            {denied ? "Try a different Google account" : "Sign in with Google"}
          </button>
        </form>
        <p style={{ color: "#94a3b8", fontSize: 12, margin: "16px 0 0" }}>{DENIAL_MESSAGE}</p>
      </div>
    </main>
  );
}
