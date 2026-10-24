import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setUnauthorizedHandler, tokenStore, type User } from "./api";

type Auth = {
  user: User | null;
  ready: boolean;
  signIn: (email: string, password: string, mode: "login" | "signup") => Promise<void>;
  signOut: () => Promise<void>;
};

const Ctx = createContext<Auth | null>(null);

/** Email + password sign-in (the API's local mode). Clerk sign-in on mobile comes with the Clerk keys. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const signOut = useCallback(async () => {
    await tokenStore.set(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => { void signOut(); });
    (async () => {
      try {
        if (await tokenStore.get()) setUser(await api.me());
      } catch {
        await tokenStore.set(null);
      } finally {
        setReady(true);
      }
    })();
    return () => setUnauthorizedHandler(null);
  }, [signOut]);

  const signIn = useCallback(async (email: string, password: string, mode: "login" | "signup") => {
    const out = mode === "login" ? await api.login(email.trim(), password) : await api.signup(email.trim(), password);
    await tokenStore.set(out.token);
    setUser(out.user);
  }, []);

  const value = useMemo(() => ({ user, ready, signIn, signOut }), [user, ready, signIn, signOut]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): Auth {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
