import { useState, useEffect } from "react";
import { Wifi, WifiOff, Server, Clock, HardDrive } from "lucide-react";
import { ping } from "../services/api";
import StatusDot from "../components/StatusDot";

const EXCHANGES = [
  { name: "NSE / BSE", code: "NSE", open: "09:15", close: "15:30" },
  { name: "NFO / BFO", code: "NFO", open: "09:15", close: "15:30" },
  { name: "CDS / BCD", code: "CDS", open: "09:00", close: "17:00" },
  { name: "MCX", code: "MCX", open: "09:00", close: "23:55" },
  { name: "NCDEX", code: "NCDEX", open: "10:00", close: "17:00" },
  { name: "DELTA (Crypto)", code: "DELTA", open: "00:00", close: "23:59", is24x7: true },
];

function isExchangeOpen(ex) {
  if (ex.is24x7) return true;
  const now = new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" });
  const ist = new Date(now);
  const hhmm = ist.getHours() * 100 + ist.getMinutes();
  const [oh, om] = ex.open.split(":").map(Number);
  const [ch, cm] = ex.close.split(":").map(Number);
  return hhmm >= oh * 100 + om && hhmm <= ch * 100 + cm;
}

function timeUntil(target, isClose) {
  const now = new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" });
  const ist = new Date(now);
  const [h, m] = target.split(":").map(Number);
  const targetDate = new Date(ist);
  targetDate.setHours(h, m, 0, 0);
  let diff = targetDate - ist;
  if (diff < 0 && !isClose) diff += 86400000;
  if (diff < 0) return "—";
  const hrs = Math.floor(diff / 3600000);
  const mins = Math.floor((diff % 3600000) / 60000);
  return `${hrs}h ${mins}m`;
}

const SERVICES = [
  { name: "OpenAlgo", port: 5000 },
  { name: "nginx", port: 80 },
  { name: "WireGuard", port: null },
  { name: "fail2ban", port: null },
];

const CRON_JOBS = [
  { name: "TOTP Login", schedule: "8:30 AM IST", lastRun: "—", status: "pending" },
  { name: "Health Check", schedule: "Every 5 min", lastRun: "—", status: "pending" },
  { name: "Backup", schedule: "Midnight", lastRun: "—", status: "pending" },
  { name: "Post Market", schedule: "3:45 PM IST", lastRun: "—", status: "pending" },
  { name: "MCX Close", schedule: "11:55 PM IST", lastRun: "—", status: "pending" },
  { name: "DDNS Update", schedule: "Every 10s", lastRun: "—", status: "pending" },
];

export default function SystemStatus() {
  const [openalgoStatus, setOpenalgoStatus] = useState("disconnected");
  const [latency, setLatency] = useState(null);
  const [lastPing, setLastPing] = useState(null);

  useEffect(() => {
    const check = async () => {
      const start = performance.now();
      try {
        await ping();
        setLatency(Math.round(performance.now() - start));
        setOpenalgoStatus("connected");
        setLastPing(new Date().toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" }));
      } catch {
        setOpenalgoStatus("disconnected");
        setLatency(null);
      }
    };
    check();
    const id = setInterval(check, 30000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="space-y-4">
      {/* Connection cards */}
      <div className="grid grid-cols-4 gap-3">
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div className="flex items-center gap-2 mb-2">
            {openalgoStatus === "connected" ? <Wifi size={16} className="text-emerald-400" /> : <WifiOff size={16} className="text-red-400" />}
            <span className="text-sm font-semibold">OpenAlgo API</span>
          </div>
          <div className="space-y-1 text-xs text-gray-400">
            <div>Host: <span className="text-gray-200 font-mono">127.0.0.1:5000</span></div>
            <div className="flex items-center gap-1">Status: <StatusDot status={openalgoStatus} /> <span className="text-gray-200">{openalgoStatus}</span></div>
            <div>Last ping: <span className="text-gray-200">{lastPing || "—"}</span></div>
            <div>Latency: <span className="text-gray-200 font-mono">{latency != null ? `${latency}ms` : "—"}</span></div>
          </div>
        </div>
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Server size={16} className="text-gray-400" />
            <span className="text-sm font-semibold">WebSocket</span>
          </div>
          <div className="space-y-1 text-xs text-gray-400">
            <div className="flex items-center gap-1">Status: <StatusDot status="disconnected" /> <span className="text-gray-200">disconnected</span></div>
            <div>Subscriptions: <span className="text-gray-200 font-mono">0</span></div>
            <div>Last tick: <span className="text-gray-200">—</span></div>
          </div>
        </div>
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Server size={16} className="text-gray-400" />
            <span className="text-sm font-semibold">OpenClaw</span>
          </div>
          <div className="space-y-1 text-xs text-gray-400">
            <div>Port: <span className="text-gray-200 font-mono">18789</span></div>
            <div className="flex items-center gap-1">Status: <StatusDot status="disconnected" /> <span className="text-gray-200">disconnected</span></div>
          </div>
        </div>
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Server size={16} className="text-gray-400" />
            <span className="text-sm font-semibold">LM Studio</span>
          </div>
          <div className="space-y-1 text-xs text-gray-400">
            <div className="flex items-center gap-1">Status: <StatusDot status="disconnected" /> <span className="text-gray-200">disconnected</span></div>
            <div>Model: <span className="text-gray-200">—</span></div>
          </div>
        </div>
      </div>

      {/* Service health */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-auto">
        <div className="px-3 py-2 border-b border-gray-800 text-xs font-semibold text-gray-400">Service Health</div>
        <table className="w-full text-xs">
          <thead className="bg-gray-800">
            <tr className="text-gray-400">
              <th className="px-3 py-2 text-left">Service</th>
              <th className="px-3 py-2 text-center">Status</th>
              <th className="px-3 py-2 text-right">Uptime</th>
              <th className="px-3 py-2 text-right">Last Restart</th>
            </tr>
          </thead>
          <tbody>
            {SERVICES.map((svc) => (
              <tr key={svc.name} className="border-t border-gray-800 hover:bg-gray-800/30">
                <td className="px-3 py-1.5 font-semibold">{svc.name}</td>
                <td className="px-3 py-1.5 text-center">
                  <StatusDot status={svc.name === "OpenAlgo" ? openalgoStatus : "disconnected"} />
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-gray-400">—</td>
                <td className="px-3 py-1.5 text-right text-gray-400">—</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Disk usage placeholder */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
        <div className="flex items-center gap-2 mb-2">
          <HardDrive size={16} className="text-gray-400" />
          <span className="text-sm font-semibold">Disk Usage</span>
        </div>
        <div className="w-full bg-gray-800 rounded-full h-2 mb-1">
          <div className="bg-emerald-500 h-2 rounded-full" style={{ width: "35%" }} />
        </div>
        <div className="text-xs text-gray-400">~350 GB used / 1 TB total</div>
      </div>

      {/* Market hours */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-auto">
        <div className="px-3 py-2 border-b border-gray-800 text-xs font-semibold text-gray-400 flex items-center gap-2">
          <Clock size={14} /> Market Hours
        </div>
        <table className="w-full text-xs">
          <thead className="bg-gray-800">
            <tr className="text-gray-400">
              <th className="px-3 py-2 text-left">Exchange</th>
              <th className="px-3 py-2 text-center">Hours (IST)</th>
              <th className="px-3 py-2 text-center">Status</th>
              <th className="px-3 py-2 text-right">Countdown</th>
            </tr>
          </thead>
          <tbody>
            {EXCHANGES.map((ex) => {
              const open = isExchangeOpen(ex);
              return (
                <tr key={ex.code} className="border-t border-gray-800 hover:bg-gray-800/30">
                  <td className="px-3 py-1.5 font-semibold">{ex.name}</td>
                  <td className="px-3 py-1.5 text-center font-mono text-gray-400">
                    {ex.is24x7 ? "24/7" : `${ex.open} – ${ex.close}`}
                  </td>
                  <td className="px-3 py-1.5 text-center">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${open ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}`}>
                      {open ? "OPEN" : "CLOSED"}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-gray-400">
                    {ex.is24x7 ? "—" : open ? `Closes in ${timeUntil(ex.close, true)}` : `Opens in ${timeUntil(ex.open, false)}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Cron jobs */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-auto">
        <div className="px-3 py-2 border-b border-gray-800 text-xs font-semibold text-gray-400">Cron Jobs</div>
        <table className="w-full text-xs">
          <thead className="bg-gray-800">
            <tr className="text-gray-400">
              <th className="px-3 py-2 text-left">Job</th>
              <th className="px-3 py-2 text-left">Schedule</th>
              <th className="px-3 py-2 text-right">Last Run</th>
              <th className="px-3 py-2 text-center">Status</th>
            </tr>
          </thead>
          <tbody>
            {CRON_JOBS.map((job) => (
              <tr key={job.name} className="border-t border-gray-800 hover:bg-gray-800/30">
                <td className="px-3 py-1.5 font-semibold">{job.name}</td>
                <td className="px-3 py-1.5 text-gray-400">{job.schedule}</td>
                <td className="px-3 py-1.5 text-right font-mono text-gray-400">{job.lastRun}</td>
                <td className="px-3 py-1.5 text-center">
                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-gray-500/20 text-gray-400">{job.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
