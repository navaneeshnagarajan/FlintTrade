const COLORS = {
  connected: "bg-emerald-400",
  disconnected: "bg-red-400",
  connecting: "bg-yellow-400 animate-pulse",
};

export default function StatusDot({ status = "disconnected" }) {
  return <span className={`inline-block w-2 h-2 rounded-full ${COLORS[status] || COLORS.disconnected}`} />;
}
