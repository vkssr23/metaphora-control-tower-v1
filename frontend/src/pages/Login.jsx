import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { Command, ArrowRight, TrendingUp, ShieldCheck, Zap } from "lucide-react";
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
      toast.success("Welcome to Metaphora Control Tower");
      nav("/");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Login failed");
    } finally { setBusy(false); }
  };

  const quick = (e, p) => { setEmail(e); setPassword(p); };

  return (
    <div className="min-h-screen gradient-hero flex items-center justify-center p-6">
      <Toaster position="top-right" />
      <div className="w-full max-w-5xl grid grid-cols-1 lg:grid-cols-2 gap-8 items-center">
        {/* HERO */}
        <div className="hidden lg:block">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-11 h-11 rounded-md flex items-center justify-center" style={{background:"var(--brand-soft)", border:"1px solid var(--brand)"}}>
              <Command className="w-5 h-5" style={{color:"var(--brand)"}} />
            </div>
            <div>
              <div className="font-display font-bold text-xl tracking-tight">Metaphora AI</div>
              <div className="font-mono text-[10px] uppercase tracking-widest" style={{color:"var(--text-3)"}}>Freight Operations OS</div>
            </div>
          </div>
          <h1 className="font-display font-black text-4xl xl:text-5xl leading-tight tracking-tight mb-4">
            Metaphora Control Tower
          </h1>
          <p className="text-lg mb-6" style={{color:"var(--text-2)"}}>
            AI Operating System for Freight Operations. Make smarter load decisions, manage dispatch execution, track safety compliance, and control profitability — from one command center.
          </p>
          <div className="grid grid-cols-1 gap-3">
            {[
              { icon: TrendingUp, title: "Load decisions in seconds", body: "Book, Negotiate, or Reject with AI-computed margin and target rate."},
              { icon: ShieldCheck, title: "Compliance protection", body: "CDL, medical, MVR, insurance, registration — dispatch is blocked when it should be."},
              { icon: Zap, title: "Dispatch execution", body: "Every load moves through 12 stages with alerts, docs, and one-click actions."},
            ].map((f,i)=>(
              <div key={i} className="terminal-card p-3 flex items-start gap-3">
                <f.icon className="w-4 h-4 mt-0.5" style={{color:"var(--brand)"}} />
                <div>
                  <div className="text-sm font-semibold">{f.title}</div>
                  <div className="text-xs" style={{color:"var(--text-2)"}}>{f.body}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* FORM */}
        <div className="terminal-card p-6 w-full max-w-md mx-auto">
          <div className="lg:hidden flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-md flex items-center justify-center" style={{background:"var(--brand-soft)", border:"1px solid var(--brand)"}}>
              <Command className="w-5 h-5" style={{color:"var(--brand)"}} />
            </div>
            <div>
              <div className="font-display font-bold text-xl tracking-tight">Metaphora AI</div>
              <div className="font-mono text-[10px] uppercase tracking-widest" style={{color:"var(--text-3)"}}>Control Tower</div>
            </div>
          </div>
          <div className="font-mono text-[10px] uppercase tracking-widest mb-1" style={{color:"var(--text-3)"}}>// Access Terminal</div>
          <h2 className="text-2xl font-display font-bold mb-6">Open Control Tower</h2>

          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="text-xs font-mono uppercase tracking-widest" style={{color:"var(--text-3)"}}>Email</label>
              <input
                data-testid="login-email"
                value={email} onChange={(e)=>setEmail(e.target.value)}
                className="mt-1 w-full rounded px-3 py-2 text-sm outline-none"
                style={{background:"var(--surface-2)", border:"1px solid var(--border)", color:"var(--text)"}}
              />
            </div>
            <div>
              <label className="text-xs font-mono uppercase tracking-widest" style={{color:"var(--text-3)"}}>Password</label>
              <input type="password"
                data-testid="login-password"
                value={password} onChange={(e)=>setPassword(e.target.value)}
                className="mt-1 w-full rounded px-3 py-2 text-sm outline-none"
                style={{background:"var(--surface-2)", border:"1px solid var(--border)", color:"var(--text)"}}
              />
            </div>
            <button
              type="submit" disabled={busy}
              data-testid="login-submit-btn"
              className="w-full btn-primary rounded px-4 py-2.5 font-medium text-sm flex items-center justify-center gap-2 transition-colors"
            >
              {busy ? "Signing in…" : <>Open Control Tower <ArrowRight className="w-4 h-4" /></>}
            </button>
            <button type="button" className="w-full rounded px-4 py-2 text-xs" style={{border:"1px solid var(--border)", color:"var(--text-2)"}}>Request Demo</button>
          </form>

          <div className="mt-6 pt-4 border-t" style={{borderColor:"var(--border)"}}>
            <div className="font-mono text-[10px] uppercase tracking-widest mb-2" style={{color:"var(--text-3)"}}>Quick sign-in (demo)</div>
            <div className="grid grid-cols-3 gap-1.5 text-[11px]">
              <button data-testid="quick-owner" onClick={()=>quick("owner@dispatch.com","owner123")} className="px-2 py-1.5 rounded font-mono hover:border-brand" style={{background:"var(--surface-2)", border:"1px solid var(--border)"}}>OWNER</button>
              <button data-testid="quick-dispatcher" onClick={()=>quick("dispatcher@dispatch.com","dispatch123")} className="px-2 py-1.5 rounded font-mono" style={{background:"var(--surface-2)", border:"1px solid var(--border)"}}>DISPATCH</button>
              <button data-testid="quick-finance" onClick={()=>quick("finance@dispatch.com","finance123")} className="px-2 py-1.5 rounded font-mono" style={{background:"var(--surface-2)", border:"1px solid var(--border)"}}>FINANCE</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
