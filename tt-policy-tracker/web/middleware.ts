import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { isAllowedSessionEmail } from "@/lib/allowed-email";

// Gates every page and the /backend API proxy. Exempt (see matcher): the
// Auth.js routes (/api/auth/*), the sign-in page, and static assets.
export default auth((req) => {
  if (isAllowedSessionEmail(req.auth?.user?.email)) return NextResponse.next();

  const { pathname, search } = req.nextUrl;
  if (pathname.startsWith("/backend/")) {
    return NextResponse.json({ error: "Sign in required" }, { status: 401 });
  }
  const url = new URL("/signin", req.nextUrl.origin);
  url.searchParams.set("callbackUrl", pathname + search);
  return NextResponse.redirect(url);
});

export const config = {
  matcher: [
    "/((?!api/auth(?:/|$)|signin(?:/|$)|_next/static|_next/image|favicon\\.ico|robots\\.txt).*)",
  ],
};
