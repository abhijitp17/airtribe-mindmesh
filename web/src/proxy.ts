import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse, type NextFetchEvent, type NextRequest } from "next/server";
import { isClerk } from "@/lib/auth-mode";

// Next 16 "proxy" (formerly middleware). With Clerk, every page except the public ones needs a
// signed-in session; Clerk sends everyone else to /sign-in (and "/" to the front page, /about). With local auth it does nothing
// (pages check the local token themselves), so no Clerk keys are needed in that mode.
const isPublic = createRouteMatcher(["/about", "/welcome", "/roles(.*)", "/share(.*)", "/sign-in(.*)", "/sign-up(.*)", "/login"]);

const clerk = clerkMiddleware(async (auth, req) => {
  // Signed-out visitors to the home page see the public front page instead of a sign-in wall.
  if (req.nextUrl.pathname === "/" && !(await auth()).userId) return NextResponse.redirect(new URL("/about", req.url));
  if (!isPublic(req)) await auth.protect();
});

export default function proxy(req: NextRequest, event: NextFetchEvent) {
  return isClerk ? clerk(req, event) : NextResponse.next();
}

export const config = {
  // Everything except Next internals and static files.
  matcher: ["/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|txt|webmanifest)).*)"],
};
