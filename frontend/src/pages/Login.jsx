import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { Zap, ArrowRight } from "lucide-react";
import { toast, Toaster } from "sonner";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("owner@dispatch.com");
  const [password, setPassword] = useState("owner123");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await login(email, password);
      toast.success("Welcome back to Dispatch OS");
      nav("/");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Login failed");
    } finally { setBusy(false); }
  };

  const quick = (e, p) => { setEmail(e); setPassword(p); };

  return (
    <div className="min-h-screen gradient-hero flex items-center justify-center p-6">
      <Toaster position="top-right" theme="dark" />
      <div className="w-full max-w-md">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-md bg-sky-500/10 border border-sky-500/40 flex items-center justify-center">
            <Zap className="w-5 h-5 text-sky-400" />
          </div>
          <div>
            <div className="font-display font-bold text-xl tracking-tight">AI Dispatch OS</div>
            <div className="font-mono text-[10px] text-zinc-500 uppercase tracking-widest">Trucking Operations Control Tower</div>
          </div>
        </div>

        <div className="terminal-card p-6">
          <div className="font-mono text-[10px] text-zinc-500 uppercase tracking-widest mb-1">// Access Terminal</div>
          <h2 className="text-2xl font-display font-bold mb-6">Sign in to command</h2>

          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="text-xs font-mono uppercase text-zinc-500 tracking-widest">Email</label>
              <input
                data-testid="login-email"
                value={email} onChange={(e)=>setEmail(e.target.value)}
                className="mt-1 w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label className="text-xs font-mono uppercase text-zinc-500 tracking-widest">Password</label>
              <input type="password"
                data-testid="login-password"
                value={password} onChange={(e)=>setPassword(e.target.value)}
                className="mt-1 w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm outline-none focus:border-sky-500"
              />
            </div>
            <button
              type="submit" disabled={busy}
              data-testid="login-submit-btn"
              className="w-full bg-sky-500 hover:bg-sky-600 disabled:opacity-60 text-white rounded px-4 py-2.5 font-medium text-sm flex items-center justify-center gap-2 transition-colors"
            >
              {busy ? "Signing in…" : <>Sign in <ArrowRight className="w-4 h-4" /></>}
            </button>
          </form>

          <div className="mt-6 pt-4 border-t border-zinc-800">
            <div className="font-mono text-[10px] text-zinc-500 uppercase tracking-widest mb-2">Quick sign-in (demo)</div>
            <div className="grid grid-cols-3 gap-1.5 text-[11px]">
              <button data-testid="quick-owner" onClick={()=>quick("owner@dispatch.com","owner123")} className="px-2 py-1.5 bg-zinc-900 border border-zinc-800 rounded hover:border-sky-500 font-mono">OWNER</button>
              <button data-testid="quick-dispatcher" onClick={()=>quick("dispatcher@dispatch.com","dispatch123")} className="px-2 py-1.5 bg-zinc-900 border border-zinc-800 rounded hover:border-sky-500 font-mono">DISPATCH</button>
              <button data-testid="quick-finance" onClick={()=>quick("finance@dispatch.com","finance123")} className="px-2 py-1.5 bg-zinc-900 border border-zinc-800 rounded hover:border-sky-500 font-mono">FINANCE</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
