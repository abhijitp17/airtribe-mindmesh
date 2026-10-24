"use client";

import { useClerk } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { auth } from "./api";
import { isClerk } from "./auth-mode";

/** Ends the session in either sign-in mode. `isClerk` is fixed at build time, so the hook order is stable. */
export function useEndSession(): (redirectTo?: string) => Promise<void> {
  if (isClerk) {
    // eslint-disable-next-line react-hooks/rules-of-hooks -- build-time constant branch
    const clerk = useClerk();
    return async (redirectTo = "/welcome") => {
      auth.clear();
      await clerk.signOut({ redirectUrl: redirectTo });
    };
  }
  // eslint-disable-next-line react-hooks/rules-of-hooks -- build-time constant branch
  const router = useRouter();
  return async (redirectTo = "/login") => {
    auth.clear();
    router.replace(redirectTo);
  };
}
