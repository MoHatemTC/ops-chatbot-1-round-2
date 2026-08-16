import { createContext, useContext, useState, useEffect, type ReactNode } from "react";
import { api } from "../lib/api";

interface User {
    email: string;
    username: string;
    role: string;
}

interface AuthContextType {
    user: User | null;
    loading: boolean;
    login: (email: string, password: string) => Promise<void>;
    logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const stored = localStorage.getItem("auth_user");
        if (stored) {
            setUser(JSON.parse(stored));
        }
        setLoading(false);
    }, []);

    async function login(email: string, password: string) {
        const params = new URLSearchParams();
        params.append("email", email);
        params.append("password", password);
        params.append("grant_type", "password");

        const res = await api.post("/auth/login", params, {
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
        });

        const { access_token, role } = res.data;
        localStorage.setItem("auth_token", access_token);

        // Login doesn't return username, so fetch the profile once right after.
        const meRes = await api.get("/users/me");
        const loggedInUser: User = { email, username: meRes.data.username, role };

        localStorage.setItem("auth_user", JSON.stringify(loggedInUser));
        setUser(loggedInUser);
    }

    function logout() {
        localStorage.removeItem("auth_token");
        localStorage.removeItem("auth_user");
        setUser(null);
        window.location.href = "/login";
    }

    return (
        <AuthContext.Provider value={{ user, loading, login, logout }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const ctx = useContext(AuthContext);
    if (!ctx) throw new Error("useAuth must be used within AuthProvider");
    return ctx;
}