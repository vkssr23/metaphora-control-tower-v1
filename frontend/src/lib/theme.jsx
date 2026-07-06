import React, { createContext, useContext, useEffect, useState, useCallback } from "react";

const ThemeCtx = createContext(null);

export function ThemeProvider({ children }) {
  const [pref, setPref] = useState(() => localStorage.getItem("metaphora_theme") || "auto");
  const [resolved, setResolved] = useState("dark");

  const apply = useCallback((p) => {
    let r = p;
    if (p === "auto") {
      r = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    setResolved(r);
    document.documentElement.classList.remove("dark", "light");
    document.documentElement.classList.add(r);
  }, []);

  useEffect(() => {
    apply(pref);
    if (pref === "auto" && window.matchMedia) {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      const handler = () => apply("auto");
      mq.addEventListener("change", handler);
      return () => mq.removeEventListener("change", handler);
    }
  }, [pref, apply]);

  const setTheme = (p) => {
    localStorage.setItem("metaphora_theme", p);
    setPref(p);
  };

  return <ThemeCtx.Provider value={{ pref, resolved, setTheme }}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);
