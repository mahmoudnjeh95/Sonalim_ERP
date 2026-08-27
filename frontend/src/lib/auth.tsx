import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiFetch } from "./api";

interface Session {
  token: string;
  tenantId: string;
  userId: string;
  email: string;
  expiresAt: string;
  refreshToken: string;
  refreshExpiresAt: string;
  permissions: string[];
}

interface LoginResponse {
  token: string;
  expires_at: string;
  refresh_token: string;
  refresh_expires_at: string;
  tenant_id: string;
  user_id: string;
  email: string;
  permissions: string[];
}

interface AuthContextValue {
  session: Session | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  hasPermission: (permission: string) => boolean;
}

// sessionStorage is an interim choice: it survives a reload but not a closed
// tab, which is safer than localStorage but still readable by injected JS.
// Revisit alongside the broader auth/security pass (httpOnly cookie via a
// backend-issued session) before this ships for real users.
const STORAGE_KEY = "sonalim-erp.session";

const AuthContext = createContext<AuthContextValue | null>(null);

function toSession(response: LoginResponse): Session {
  return {
    token: response.token,
    tenantId: response.tenant_id,
    userId: response.user_id,
    email: response.email,
    expiresAt: response.expires_at,
    refreshToken: response.refresh_token,
    refreshExpiresAt: response.refresh_expires_at,
    permissions: response.permissions,
  };
}

function isExpired(session: Session): boolean {
  return new Date(session.expiresAt).getTime() <= Date.now();
}

function readStoredSession(): Session | null {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Session;
    // An expired access token is still worth keeping if the refresh token
    // underneath it is still good — the expiry effect below will renew it.
    return parsed.refreshToken ? parsed : isExpired(parsed) ? null : parsed;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => readStoredSession());

  const applySession = (response: LoginResponse) => {
    const next = toSession(response);
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    setSession(next);
  };

  const logout = () => {
    // Read from storage rather than the `session` state closure: this function
    // is also called from effects registered once on mount (the 401 listener
    // below), whose closures would otherwise hold a stale (often null)
    // session and silently skip revoking a real token.
    const stored = sessionStorage.getItem(STORAGE_KEY);
    sessionStorage.removeItem(STORAGE_KEY);
    setSession(null);

    if (stored) {
      try {
        const { token, refreshToken } = JSON.parse(stored) as Session;
        // Best-effort: the client-side session is already gone either way,
        // so a failed revocation call doesn't change what the user sees.
        void apiFetch("/core/auth/logout", {
          method: "POST",
          token,
          body: { refresh_token: refreshToken },
        }).catch(() => {});
      } catch {
        // malformed stored session; nothing to revoke server-side
      }
    }
  };

  const login = async (email: string, password: string) => {
    const response = await apiFetch<LoginResponse>("/core/auth/login", {
      method: "POST",
      body: { email, password },
    });
    applySession(response);
  };

  // Access tokens are short-lived (core/auth.py: ACCESS_TOKEN_TTL) on
  // purpose — this silently trades the old one in for a new one just before
  // it dies, using the longer-lived refresh token, so an active user never
  // sees a logout. Only a failed refresh (revoked, reused, or itself
  // expired) actually signs the user out.
  useEffect(() => {
    if (!session) return;

    const renew = () => {
      apiFetch<LoginResponse>("/core/auth/refresh", {
        method: "POST",
        body: { refresh_token: session.refreshToken },
      })
        .then(applySession)
        .catch(() => logout());
    };

    const remaining = new Date(session.expiresAt).getTime() - Date.now();
    if (remaining <= 0) {
      renew();
      return;
    }
    const timeout = window.setTimeout(renew, remaining);
    return () => window.clearTimeout(timeout);
  }, [session]);

  // Any apiFetch call that gets a 401 the refresh cycle above didn't
  // already handle (refresh token itself invalid/expired/reused, backend
  // restart clearing sessions, etc.) reports it here instead of every call
  // site handling it.
  useEffect(() => {
    window.addEventListener("auth:unauthorized", logout);
    return () => window.removeEventListener("auth:unauthorized", logout);
  }, []);

  // Optional chaining on `permissions` too (not just `session`): a session already
  // in sessionStorage from before this field existed would otherwise throw here
  // until it naturally refreshes.
  const hasPermission = (permission: string) => session?.permissions?.includes(permission) ?? false;

  const value = useMemo(() => ({ session, login, logout, hasPermission }), [session]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
