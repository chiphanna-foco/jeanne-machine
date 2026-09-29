import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";
import { isAllowedSessionEmail } from "@/lib/allowed-email";

// Server-side proxy from the browser to the Railway API.
//   /backend/api/<x>   -> ${API_URL}/api/<x>   (adds X-Jeanne-Key)
//   /backend/admin/<x> -> ${API_URL}/admin/<x> (?token= passes through unchanged)
// It replaces the old next.config rewrite of /api/* so /api/auth/* is free
// for Auth.js, and so the API key never reaches the browser.

export const dynamic = "force-dynamic";
export const maxDuration = 60;

const ALLOWED_ROOTS = new Set(["api", "admin"]);
const FORWARD_REQUEST_HEADERS = ["content-type", "accept"];
const FORWARD_RESPONSE_HEADERS = ["content-type", "cache-control"];

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const session = await auth();
  if (!isAllowedSessionEmail(session?.user?.email)) {
    return NextResponse.json({ error: "Sign in required" }, { status: 401 });
  }

  const { path } = await ctx.params;
  if (!path?.length || !ALLOWED_ROOTS.has(path[0]) || path.some((p) => p === "." || p === "..")) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const apiUrl = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL;
  const apiKey = process.env.JEANNE_API_KEY;
  if (!apiUrl || !apiKey) {
    console.error("backend proxy: API_URL or JEANNE_API_KEY is not set on this deployment");
    return NextResponse.json(
      { error: "Server is missing API_URL or JEANNE_API_KEY" },
      { status: 500 },
    );
  }

  const target =
    `${apiUrl.replace(/\/+$/, "")}/${path.map(encodeURIComponent).join("/")}` + req.nextUrl.search;

  const headers = new Headers();
  for (const h of FORWARD_REQUEST_HEADERS) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  headers.set("X-Jeanne-Key", apiKey);

  const hasBody = !["GET", "HEAD"].includes(req.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? await req.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch (e) {
    console.error("backend proxy: upstream fetch failed", e);
    return NextResponse.json({ error: "API unreachable" }, { status: 502 });
  }

  const out = new Headers();
  for (const h of FORWARD_RESPONSE_HEADERS) {
    const v = upstream.headers.get(h);
    if (v) out.set(h, v);
  }
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
