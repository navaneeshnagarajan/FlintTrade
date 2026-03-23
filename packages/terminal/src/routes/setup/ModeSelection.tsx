/**
 * ModeSelection — initial screen letting the user pick Quick / Guided / Advanced setup.
 */

import { Zap, BookOpen, Settings2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
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
      className="bg-surface-card border border-border-default rounded-lg p-6 shadow-sm cursor-pointer hover:border-accent/40 hover:bg-surface-hover transition-all duration-200 group"
      onClick={onClick}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between mb-2">
          <div className="p-2 rounded-lg bg-accent/15 text-accent group-hover:bg-accent/20 transition-colors">
            {icon}
          </div>
          <Badge variant="outline" className="text-xxs text-text-muted bg-surface-elevated px-2 py-0.5 rounded border-border-default">
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
    <main aria-label="Setup wizard" className="min-h-screen bg-surface-base flex items-center justify-center p-4">
      <div className="max-w-3xl w-full space-y-8">
        <div className="text-center space-y-3">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-accent/40 bg-accent/15 text-accent text-xxs font-medium mb-2">
            First Time Setup
          </div>
          <h1 className="font-heading font-bold text-2xl text-text-primary tracking-tight">
            Welcome to FlintTrade
          </h1>
          <p className="text-sm text-text-secondary max-w-md mx-auto">
            Connect to OpenAlgo and configure your workspace. Takes under two minutes.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <ModeCard
            title="Quick Setup"
            subtitle="2 steps — connect and go"
            description="Enter your OpenAlgo URL and API key, pick your persona, start trading immediately."
            badge="~1 min"
            icon={<Zap className="size-5" />}
            onClick={() => onSelect("quick")}
          />
          <ModeCard
            title="Guided Setup"
            subtitle="7 steps — personalized"
            description="Persona, connection, experience, interests, and trading defaults for a tailored workspace."
            badge="~2 min"
            icon={<BookOpen className="size-5" />}
            onClick={() => onSelect("guided")}
          />
          <ModeCard
            title="Advanced Setup"
            subtitle="9 steps — full control"
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
            onClick={() => navigate("/trade")}
          >
            Skip setup — use defaults
          </Button>
        </div>
      </div>
    </main>
  );
}
