import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { Command, ArrowRight, TrendingUp, ShieldCheck, Zap } from "lucide-react";
import { toast, Toaster } from "sonner";

export default function Login() {
  const { login, signup } = useAuth();
  const nav = useNavigate();
  const [mode, setMode] = useState("login"); // "login" | "signup"
  const [busy, setBusy] = useState(false);

  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [signupForm, setSignupForm] = useState({ name: "", email: "", password: "" });

  const doLogin = async (e) => {
    e.preventDefault();
    if (!loginForm.email || !loginForm.password) { toast.error("Enter email & password"); return; }
    setBusy(true);
    try {
      await login(loginForm.email, loginForm.password);
      toast.success("Welcome to Metaphora Control Tower");
      nav("/");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Login failed");
    } finally { setBusy(false); }
  };

  const doSignup = async (e) => {
    e.preventDefault();
    const { name, email, password } = signupForm;
    if (!name || !email || !password) { toast.error("Name, email, and password required"); return; }
    if (password.length < 12) { toast.error("Password must be at least 12 characters"); return; }
    setBusy(true);
    try {
      await signup({ name, email, password, role: "viewer" });
      toast.success("Account created — welcome to Metaphora");
      nav("/");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Signup failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen gradient-hero flex items-center justify-center p-6">
      <Toaster position="top-right" />
      <div className="w-full max-w-5xl grid grid-cols-1 lg:grid-cols-2 gap-8 items-center">
        {/* HERO */}
        <div className="hidden lg:block">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-11 h-11 rounded-md flex items-center justify-center" style={{background:"rgba(var(--accent-rgb), 0.14)", border:"1px solid var(--accent)"}}>
              <Command className="w-5 h-5" style={{color:"var(--accent-text)"}} />
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
              { icon: TrendingUp, title: "Load decisions in seconds", body: "Book, Negotiate, or Reject with AI-computed margin and target rate." },
              { icon: ShieldCheck, title: "Compliance protection", body: "CDL, medical, MVR, insurance, registration — dispatch is blocked when it should be." },
              { icon: Zap, title: "Dispatch execution", body: "Every load moves through 12 stages with alerts, docs, and one-click actions." },
            ].map((f,i)=>(
              <div key={i} className="terminal-card p-3 flex items-start gap-3">
                <f.icon className="w-4 h-4 mt-0.5" style={{color:"var(--accent-text)"}} />
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
            <div className="w-10 h-10 rounded-md flex items-center justify-center" style={{background:"rgba(var(--accent-rgb), 0.14)", border:"1px solid var(--accent)"}}>
              <Command className="w-5 h-5" style={{color:"var(--accent-text)"}} />
            </div>
            <div>
              <div className="font-display font-bold text-xl tracking-tight">Metaphora AI</div>
              <div className="font-mono text-[10px] uppercase tracking-widest" style={{color:"var(--text-3)"}}>Control Tower</div>
            </div>
          </div>

          {/* Tab toggle */}
          <div className="flex mb-5 p-1" style={{background:"var(--surface-2)", border:"1px solid var(--border)", borderRadius:"var(--r-control)"}}>
            <button
              type="button"
              data-testid="tab-login"
              onClick={()=>setMode("login")}
              className="flex-1 py-1.5 text-xs font-mono uppercase tracking-widest transition-all"
              style={{
                background: mode==="login" ? "var(--accent)" : "transparent",
                color: mode==="login" ? "var(--accent-on)" : "var(--text-2)",
                fontWeight: mode==="login" ? 700 : 400,
                borderRadius: "var(--r-nav)",
              }}
            >Sign In</button>
            <button
              type="button"
              data-testid="tab-signup"
              onClick={()=>setMode("signup")}
              className="flex-1 py-1.5 text-xs font-mono uppercase tracking-widest transition-all"
              style={{
                background: mode==="signup" ? "var(--accent)" : "transparent",
                color: mode==="signup" ? "var(--accent-on)" : "var(--text-2)",
                fontWeight: mode==="signup" ? 700 : 400,
                borderRadius: "var(--r-nav)",
              }}
            >Create Account</button>
          </div>

          {mode === "login" ? (
            <>
              <div className="font-mono text-[10px] uppercase tracking-widest mb-1" style={{color:"var(--text-3)"}}>// Access Terminal</div>
              <h2 className="text-2xl font-display font-bold mb-4">Open Control Tower</h2>
              <form onSubmit={doLogin} className="space-y-3">
                <Field label="Email">
                  <input
                    data-testid="login-email" type="email" autoComplete="email"
                    value={loginForm.email} onChange={(e)=>setLoginForm({...loginForm, email: e.target.value})}
                    placeholder="you@company.com"
                    className="metaphora-input"
                  />
                </Field>
                <Field label="Password">
                  <input
                    data-testid="login-password" type="password" autoComplete="current-password"
                    value={loginForm.password} onChange={(e)=>setLoginForm({...loginForm, password: e.target.value})}
                    placeholder="••••••••"
                    className="metaphora-input"
                  />
                </Field>
                <button type="submit" disabled={busy} data-testid="login-submit-btn"
                  className="btn btn--form btn--primary w-full">
                  {busy ? "Signing in…" : <>Open Control Tower <ArrowRight className="w-4 h-4" /></>}
                </button>
              </form>
              <div className="text-center text-xs mt-4" style={{color:"var(--text-3)"}}>
                No account yet?{" "}
                <button onClick={()=>setMode("signup")} data-testid="switch-to-signup" className="font-semibold" style={{color:"var(--accent-text)"}}>Create one →</button>
              </div>
            </>
          ) : (
            <>
              <div className="font-mono text-[10px] uppercase tracking-widest mb-1" style={{color:"var(--text-3)"}}>// New Viewer Account</div>
              <h2 className="text-2xl font-display font-bold mb-4">Create your account</h2>
              <form onSubmit={doSignup} className="space-y-3">
                <Field label="Full Name">
                  <input
                    data-testid="signup-name" autoComplete="name"
                    value={signupForm.name} onChange={(e)=>setSignupForm({...signupForm, name: e.target.value})}
                    placeholder="Jane Operator"
                    className="metaphora-input"
                  />
                </Field>
                <Field label="Work Email">
                  <input
                    data-testid="signup-email" type="email" autoComplete="email"
                    value={signupForm.email} onChange={(e)=>setSignupForm({...signupForm, email: e.target.value})}
                    placeholder="you@company.com"
                    className="metaphora-input"
                  />
                </Field>
                <Field label="Password">
                  <input
                    data-testid="signup-password" type="password" autoComplete="new-password"
                    value={signupForm.password} onChange={(e)=>setSignupForm({...signupForm, password: e.target.value})}
                    placeholder="minimum 12 characters"
                    className="metaphora-input"
                  />
                </Field>
                <button type="submit" disabled={busy} data-testid="signup-submit-btn"
                  className="btn btn--form btn--primary w-full">
                  {busy ? "Creating account…" : <>Create Account <ArrowRight className="w-4 h-4" /></>}
                </button>
              </form>
              <div className="text-center text-xs mt-4" style={{color:"var(--text-3)"}}>
                Already have an account?{" "}
                <button onClick={()=>setMode("login")} data-testid="switch-to-login" className="font-semibold" style={{color:"var(--accent-text)"}}>Sign in →</button>
              </div>
            </>
          )}
        </div>
      </div>
      <style>{`
        .metaphora-input{
          width:100%;
          background: var(--bg);
          border: 1px solid var(--border-strong);
          border-radius: var(--r-control-lg);
          height: var(--h-form);
          padding: 0 14px;
          font-size: 14px;
          font-family: var(--font-ui);
          color: var(--text);
          outline: none;
          transition: border-color .15s, box-shadow .15s;
        }
        .metaphora-input::placeholder { color: var(--text-4); }
        .metaphora-input:focus{ border-color: var(--border-focus); box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.11); }
      `}</style>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="micro-label" style={{display:"block", marginBottom:"7px"}}>{label}</label>
      {children}
    </div>
  );
}
