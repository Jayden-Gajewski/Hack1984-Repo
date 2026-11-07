import { NextResponse, type NextRequest } from "next/server";

// First gate: no session cookie, no scanner. The scanner then asks the backend
// (/api/auth/me) whether the cookie is still a valid session.
export function proxy(req: NextRequest) {
  if (!req.cookies.has("h84_session")) {
    const url = new URL("/login", req.url);
    url.searchParams.set("next", req.nextUrl.pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/app/:path*"] };
