import React, { createContext, useContext, useState, useEffect } from "react";
import api from "./api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const u = localStorage.getItem("user");
    return u ? JSON.parse(u) : null;
  });
  const [loading, setLoading] = useState(false);

  const applySession = (data) => {
    localStorage.setItem("token", data.token);
    localStorage.setItem("user", JSON.stringify(data.user));
    setUser(data.user);
    return data.user;
  };

  const login = async (email, password) => {
    setLoading(true);
    try {
      const { data } = await api.post("/auth/login", { email, password });
      return applySession(data);
    } finally { setLoading(false); }
  };

  const signup = async (payload) => {
    setLoading(true);
    try {
      const { data } = await api.post("/auth/signup", payload);
      return applySession(data);
    } finally { setLoading(false); }
  };

  // Metaphora Secure SSO handoff: trades the short-lived, single-use code
  // from the ?metaphora_sso_code= redirect for a normal session, exactly
  // like login/signup — see MetaphoraSsoGate in App.js for where this is
  // called.
  const exchangeMetaphoraCode = async (code) => {
    const { data } = await api.post("/auth/metaphora/exchange", { code });
    return applySession(data);
  };

  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    setUser(null);
  };

  return (
    <AuthCtx.Provider value={{ user, login, signup, exchangeMetaphoraCode, logout, loading }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
