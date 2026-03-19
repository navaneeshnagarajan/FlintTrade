import { Outlet } from "react-router-dom";
import { useWsBridge } from "@/hooks/useWsBridge";

export default function RootLayout() {
  useWsBridge(); // WebSocket connection shared across all routes
  return <Outlet />;
}
