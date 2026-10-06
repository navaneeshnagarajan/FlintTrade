/** Synthetic component fixture. Never part of the production entry point. */
import { createRoot } from "react-dom/client";
import { AboutSection } from "../src/tools/Settings/AboutSection";
import { useAuthStore } from "../src/stores/authStore";
import "../src/index.css";
const mode = new URLSearchParams(window.location.search).get("mode");
useAuthStore.setState({ token: mode === "demo" ? "demo-user" : "synthetic-about-session" });
createRoot(document.getElementById("root")!).render(
  <main className="dark bg-surface-base text-text-primary min-h-screen p-6 max-w-4xl mx-auto"><AboutSection /></main>,
);
