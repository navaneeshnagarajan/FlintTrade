import { isPublicDemoBuild } from "@/lib/demoSession";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useLocation } from "react-router";
import { BookOpen } from "lucide-react";
import { APPS, appForPath } from "@/layout/appCatalog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogTrigger, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { TOGGLE_AI_TUTOR_EVENT } from "@/lib/aiTutorEvents";
import { useAuthStore } from "@/stores/authStore";
import { useAdvisorLlmStatus } from "@/hooks/useAdvisorLlmStatus";
import { AITutorPill } from "./AITutorPill";
import { useHelpFooter } from "./HelpFooter";
export function LocalHelp() {
  const [open, setOpen] = useState(false);
  const footer = useHelpFooter();
  const location = useLocation();
  const app = APPS.find(item => item.id === appForPath(location.pathname));
  useEffect(() => { const toggle = () => setOpen(value => !value); window.addEventListener(TOGGLE_AI_TUTOR_EVENT, toggle); return () => window.removeEventListener(TOGGLE_AI_TUTOR_EVENT, toggle); }, []);
  const trigger = <DialogTrigger asChild><Button variant="outline" size="sm" className={footer ? "h-6 shrink-0" : "fixed bottom-12 right-4 z-30"} aria-label="Open local help" onClick={() => setOpen(true)}><BookOpen size={14} />Help</Button></DialogTrigger>;
  return <>
    <Dialog open={open} onOpenChange={setOpen}>
      {footer ? createPortal(trigger, footer) : trigger}
      <DialogContent><DialogTitle>Local help · not an AI response</DialogTitle><DialogDescription>No model is ready. Navigation, documentation and manual safety controls remain available without AI.</DialogDescription>
      {app && <p className="text-sm">{app.name}: {app.description}.</p>}
      <p className="text-xs text-text-secondary">App switching and instrument linking never arm trading or change execution accounts. Testing must use its own practice run. Unknown order outcomes require reconciliation, not retry.</p>
      <nav aria-label="Local help destinations" className="grid grid-cols-3 gap-2">{APPS.map(item => <Link className="rounded border border-border-default p-2 text-sm" key={item.id} to={item.path} onClick={() => setOpen(false)}>{item.name}</Link>)}</nav>
      <Link to="/automation" state={{ openWidget: { widgetId: "model-routing" } }} onClick={() => setOpen(false)}>Core model connections and tasks</Link>
      <Link to="/settings#llm" onClick={() => setOpen(false)}>Configure AI</Link>
    </DialogContent></Dialog>
  </>;
}
function ReadyCompanion() {
  const readiness = useAdvisorLlmStatus();
  return readiness.configured ? <AITutorPill /> : <LocalHelp />;
}
export function AppCompanion() {
  const status = useAuthStore(state => state.status);
  return isPublicDemoBuild() ? <LocalHelp /> : status === "logged-in" ? <ReadyCompanion /> : null;
}
