import React, { useEffect, useState } from "react";
import Topbar from "../components/Topbar";
import api from "../lib/api";
import { FileText } from "lucide-react";
import { useNavigate } from "react-router-dom";

export default function Documents() {
  const [docs, setDocs] = useState([]);
  const [loads, setLoads] = useState([]);
  const nav = useNavigate();
  useEffect(()=>{
    api.get("/documents").then(r=>setDocs(r.data.sort((a,b)=>b.uploaded_at.localeCompare(a.uploaded_at))));
    api.get("/loads").then(r=>setLoads(r.data));
  },[]);

  const loadMap = Object.fromEntries(loads.map(l=>[l.id,l]));

  // Docs pending: loads that are delivered but missing POD
  const pending = loads.filter(l => ["Delivered","Docs Pending"].includes(l.stage) && l.pod_status === "Pending");

  return (
    <div>
      <Topbar title="Documents" subtitle={`${docs.length} uploaded · ${pending.length} pending`} />
      <div className="p-6 space-y-4">
        {pending.length>0 && (
          <div className="terminal-card p-4 border-amber-500/40">
            <div className="kpi-label text-amber-400 mb-2">Docs Pending — Delivered loads missing POD</div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              {pending.map(l => (
                <div key={l.id} onClick={()=>nav(`/loads/${l.id}`)} className="cursor-pointer text-xs font-mono bg-zinc-900 border border-zinc-800 hover:border-amber-500 rounded p-2" data-testid={`docpending-${l.id}`}>
                  <div className="text-sky-400">{l.id}</div>
                  <div>{l.customer}</div>
                  <div className="text-zinc-500">{l.pickup_city} → {l.delivery_city}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="terminal-card overflow-hidden">
          <div className="overflow-auto">
            <table className="dispatch-table">
              <thead><tr>
                <th>Type</th><th>Load</th><th>Customer</th><th>Filename</th><th>Uploaded By</th><th>Uploaded</th>
              </tr></thead>
              <tbody>
                {docs.map(d => (
                  <tr key={d.id} className="cursor-pointer" onClick={()=>nav(`/loads/${d.load_id}`)} data-testid={`doc-row-${d.id}`}>
                    <td className="text-sky-400"><FileText className="inline w-3 h-3 mr-1" />{d.doc_type}</td>
                    <td>{d.load_id}</td>
                    <td>{loadMap[d.load_id]?.customer || "—"}</td>
                    <td className="text-zinc-500">{d.filename}</td>
                    <td>{d.uploaded_by}</td>
                    <td className="text-[10px] text-zinc-500">{d.uploaded_at?.slice(0,16).replace("T"," ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
