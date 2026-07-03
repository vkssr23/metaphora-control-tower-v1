import React, { useEffect, useRef, useState } from "react";
import Topbar from "../components/Topbar";
import api, { API } from "../lib/api";
import { Sparkles, Send } from "lucide-react";

const SUGGESTIONS = [
  "Which load is at risk?",
  "Which truck is most profitable?",
  "Which driver is underperforming?",
  "Which invoices are pending?",
  "Which delivered loads are missing POD?",
  "Which loads lost money?",
  "Give me today's owner report.",
  "Predict which load may get delayed.",
];

export default function AIAssistant() {
  const [messages, setMessages] = useState([
    { role:"assistant", text:"I'm your Dispatch.RR assistant. Ask me about at-risk loads, driver performance, invoices, profitability, or ask for today's owner report." }
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef(null);

  useEffect(()=>{ bottomRef.current?.scrollIntoView({behavior:"smooth"}); }, [messages]);

  const send = async (text) => {
    const q = text ?? input;
    if (!q.trim() || busy) return;
    setInput("");
    setMessages(m => [...m, { role:"user", text: q }, { role:"assistant", text: "" }]);
    setBusy(true);
    try {
      const res = await fetch(`${API}/ai/chat`, {
        method:"POST", headers:{ "Content-Type":"application/json" },
        body: JSON.stringify({ session_id: "web", message: q })
      });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let acc = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        acc += decoder.decode(value, { stream: true });
        setMessages(m => {
          const copy = [...m];
          copy[copy.length-1] = { role:"assistant", text: acc };
          return copy;
        });
      }
    } catch (e) {
      setMessages(m => {
        const copy = [...m];
        copy[copy.length-1] = { role:"assistant", text: "[Connection error] "+e.message };
        return copy;
      });
    } finally { setBusy(false); }
  };

  return (
    <div className="flex flex-col h-screen">
      <Topbar title="AI Assistant" subtitle="Claude Sonnet · Live Data" />
      <div className="flex-1 overflow-y-auto p-6 space-y-4 max-w-4xl mx-auto w-full">
        {messages.map((m,i)=>(
          <div key={i} className={`flex ${m.role==="user"?"justify-end":"justify-start"}`} data-testid={`ai-msg-${i}`}>
            <div className={`${m.role==="user"?"bg-sky-500/20 border-sky-500/40":"bg-zinc-900 border-zinc-800"} border rounded-lg px-4 py-3 max-w-[80%] text-sm`}>
              {m.role==="assistant" && <div className="flex items-center gap-1.5 mb-1"><Sparkles className="w-3 h-3 text-sky-400" /><span className="text-[10px] font-mono uppercase text-sky-400 tracking-widest">Dispatch AI</span></div>}
              <div className="whitespace-pre-wrap font-mono text-[13px] leading-relaxed">{m.text || (busy && i===messages.length-1 ? "…" : "")}</div>
            </div>
          </div>
        ))}
        <div ref={bottomRef}></div>
      </div>

      <div className="border-t border-zinc-800 p-4 bg-[#0A0A0C]">
        <div className="max-w-4xl mx-auto">
          <div className="flex flex-wrap gap-1.5 mb-3">
            {SUGGESTIONS.map(s => (
              <button key={s} onClick={()=>send(s)} data-testid={`ai-suggest-${s.slice(0,20)}`} className="text-[11px] font-mono bg-zinc-900 border border-zinc-800 hover:border-sky-500 rounded px-2.5 py-1 text-zinc-400 hover:text-zinc-100 transition-colors">{s}</button>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>e.key==="Enter"&&send()}
              placeholder="Ask about loads, drivers, trucks, invoices, risk…"
              data-testid="ai-input"
              className="flex-1 bg-zinc-900 border border-zinc-800 rounded px-3 py-2.5 text-sm outline-none focus:border-sky-500 font-mono"
            />
            <button onClick={()=>send()} disabled={busy} data-testid="ai-send-btn" className="bg-sky-500 hover:bg-sky-600 text-white rounded px-4 py-2.5 text-sm flex items-center gap-1.5 disabled:opacity-60"><Send className="w-4 h-4" /> Send</button>
          </div>
        </div>
      </div>
    </div>
  );
}
