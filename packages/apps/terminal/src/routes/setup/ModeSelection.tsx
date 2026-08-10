/**
 * ModeSelection — initial screen letting the user pick Quick / Guided / Advanced setup.
 */

import { Zap, BookOpen, Settings2 } from "lucide-react";
import { useNavigate } from "react-router";
import { personaDefaultRoute } from "@/lib/personaDefaultRoute";
import { useSettingsStore } from "@/stores/settingsStore";
import PublicRouteShell from "@/components/layout/PublicRouteShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export type SetupMode = "quick" | "guided" | "advanced";

interface ModeCardProps {
  title: string;
  subtitle: string;
  description: string;
  badge: string;
  icon: React.ReactNode;
  onClick: () => void;
}

function ModeCard({ title, subtitle, description, badge, icon, onClick }: ModeCardProps) {
  return (
    <Card
      role="button"
      tabIndex={0}
      className="group cursor-pointer rounded-xl border border-border-default/70 bg-surface-card/60 p-4 shadow-xl shadow-black/10 backdrop-blur-xl transition-all duration-200 hover:-translate-y-0.5 hover:border-accent/45 hover:bg-surface-card/75 hover:shadow-[0_0_36px_rgba(34,197,94,0.12)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
    >
      <CardHeader className="pb-3">
        <div className="mb-2 flex items-start justify-between">
          <div className="rounded-lg bg-accent/15 p-2 text-accent transition-colors group-hover:bg-accent/20">
            {icon}
          </div>
          <Badge variant="outline" className="rounded-full border-border-default/70 bg-surface-elevated/70 px-2 py-0.5 text-xxs text-text-muted">
            {badge}
          </Badge>
        </div>
        <CardTitle className="font-heading font-bold text-lg text-text-primary">{title}</CardTitle>
        <CardDescription className="text-sm text-text-muted">{subtitle}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-text-muted leading-relaxed">{description}</p>
      </CardContent>
    </Card>
  );
}

interface ModeSelectionProps {
  onSelect: (mode: SetupMode) => void;
}

export function ModeSelection({ onSelect }: ModeSelectionProps) {
  const navigate = useNavigate();

  return (
    <PublicRouteShell
      mainLabel="Setup wizard"
      maxWidth="lg"
      eyebrow="First Time Setup"
      title="Welcome to FlintTrade"
      subtitle="Connect the recommended OpenAlgo bridge, or use a verified native broker. Takes under two minutes."
    >
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <ModeCard
            title="Quick Setup"
            subtitle="2 steps - connect and go"
            description="Choose OpenAlgo or a verified native broker, pick your persona, then start trading."
            badge="~1 min"
            icon={<Zap className="size-5" />}
            onClick={() => onSelect("quick")}
          />
          <ModeCard
            title="Guided Setup"
            subtitle="7 steps - personalised"
            description="Persona, connection, experience, interests, and trading defaults for a tailored workspace."
            badge="~2 min"
            icon={<BookOpen className="size-5" />}
            onClick={() => onSelect("guided")}
          />
          <ModeCard
            title="Advanced Setup"
            subtitle="9 steps - full control"
            description="Everything in Guided plus LLM provider, risk limits, and workspace preview."
            badge="~4 min"
            icon={<Settings2 className="size-5" />}
            onClick={() => onSelect("advanced")}
          />
        </div>

        <div className="text-center">
          <Button
            variant="ghost"
            className="text-sm text-text-muted hover:text-text-primary"
            onClick={() => {
              const persona = useSettingsStore.getState().persona;
              navigate(personaDefaultRoute(persona));
            }}
          >
            Skip setup - use defaults
          </Button>
        </div>
      </div>
    </PublicRouteShell>
  );
}
