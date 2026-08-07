import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  getAuthStatus,
  authSetup,
  authLogin,
  authLogout,
  setAuthToken,
} from "../api";

interface AuthState {
  /** True once the initial status check completes. */
  checking: boolean;
  /** Whether a master password has been configured. */
  configured: boolean;
  /** True when the user has passed authentication (or auth is not configured). */
  authenticated: boolean;
  /** The live session token (null when locked / not configured). */
  authToken: string | null;

  login: (password: string) => Promise<{ ok: boolean; error?: string }>;
  setup: (password: string) => Promise<{ ok: boolean; error?: string }>;
  logout: () => Promise<void>;
  /** Skip setup for now (the "Later" button). */
  skip: () => void;
}

const AuthContext = createContext<AuthState>({
  checking: true,
  configured: false,
  authenticated: false,
  authToken: null,
  login: async () => ({ ok: false }),
  setup: async () => ({ ok: false }),
  logout: async () => {},
  skip: () => {},
});

const AUTH_TOKEN_KEY = "werub-auth-token";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [checking, setChecking] = useState(true);
  const [configured, setConfigured] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [authToken, setToken] = useState<string | null>(null);

  // Restore token from sessionStorage and wire it into the api module.
  useEffect(() => {
    const stored = sessionStorage.getItem(AUTH_TOKEN_KEY);
    if (stored) {
      setToken(stored);
      setAuthToken(stored);
    }
  }, []);

  // Check auth status on mount — determines whether to show the login gate.
  useEffect(() => {
    const stored = sessionStorage.getItem(AUTH_TOKEN_KEY);
    if (stored) setAuthToken(stored);

    getAuthStatus()
      .then((s) => {
        setConfigured(s.configured);
        if (!s.configured) {
          // No password set — pass through.
          setAuthenticated(true);
        } else if (!s.locked && stored) {
          // Password set, but the token is still valid.
          setAuthenticated(true);
        } else {
          setAuthenticated(false);
        }
      })
      .catch(() => {
        // Server unreachable — let the app boot normally (the health retry loop
        // will catch it). Treat as unauthenticated-but-unconfigured.
        setAuthenticated(true);
      })
      .finally(() => setChecking(false));
  }, []);

  const saveToken = useCallback((token: string | null) => {
    setToken(token);
    setAuthToken(token);
    if (token) {
      sessionStorage.setItem(AUTH_TOKEN_KEY, token);
    } else {
      sessionStorage.removeItem(AUTH_TOKEN_KEY);
    }
  }, []);

  const login = useCallback(
    async (password: string) => {
      const res = await authLogin(password);
      if (res.ok && res.token) {
        saveToken(res.token);
        setAuthenticated(true);
        setConfigured(true);
      }
      return { ok: res.ok, error: res.error };
    },
    [saveToken],
  );

  const setup = useCallback(
    async (password: string) => {
      const res = await authSetup(password);
      if (res.ok && res.token) {
        saveToken(res.token);
        setAuthenticated(true);
        setConfigured(true);
      }
      return { ok: res.ok, error: res.error };
    },
    [saveToken],
  );

  const logout = useCallback(async () => {
    await authLogout().catch(() => {});
    saveToken(null);
    setAuthenticated(false);
  }, [saveToken]);

  const skip = useCallback(() => {
    setAuthenticated(true);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        checking,
        configured,
        authenticated,
        authToken,
        login,
        setup,
        logout,
        skip,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
