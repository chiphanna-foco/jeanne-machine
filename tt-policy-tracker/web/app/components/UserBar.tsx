import { auth, signOut } from "@/auth";

// Small signed-in strip over the top-right of the page header.
// Server component: reads the session, renders nothing when signed out.
export async function UserBar() {
  const session = await auth();
  const email = session?.user?.email;
  if (!email) return null;

  return (
    <div
      style={{
        position: "absolute",
        top: 10,
        right: 16,
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        gap: 10,
        fontSize: 12,
        color: "rgba(255,255,255,0.85)",
        maxWidth: "calc(100vw - 32px)",
      }}
    >
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {email}
      </span>
      <form
        action={async () => {
          "use server";
          await signOut({ redirectTo: "/signin" });
        }}
      >
        <button
          type="submit"
          style={{
            background: "transparent",
            border: "none",
            padding: 0,
            color: "#fff",
            textDecoration: "underline",
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          Sign out
        </button>
      </form>
    </div>
  );
}
