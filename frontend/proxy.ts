import { NextResponse, type NextRequest } from "next/server";

// First gate: no session cookie, no scanner. The scanner then asks the backend
// (/api/auth/me) whether the cookie is still a valid session, and clears it if not.
// Already signed in: /login and /signup go straight to the scanner.
export function proxy(req: NextRequest) {
  const signedIn = req.cookies.has("h84_session");
  const { pathname } = req.nextUrl;
  if (pathname === "/login" || pathname === "/signup") {
    return signedIn ? NextResponse.redirect(new URL("/app", req.url)) : NextResponse.next();
  }
  if (signedIn) return NextResponse.next();
  const url = new URL("/login", req.url);
  url.searchParams.set("next", pathname);
  return NextResponse.redirect(url);
}

export const config = { matcher: ["/app/:path*", "/login", "/signup"] };
