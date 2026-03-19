import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useNavigate } from "react-router-dom";

export default function SetupRoute() {
  const navigate = useNavigate();
  return (
    <div className="min-h-screen bg-surface-base flex items-center justify-center p-4">
      <div className="max-w-3xl w-full space-y-6">
        <div className="text-center space-y-2">
          <h1 className="text-3xl font-bold text-text-primary">Welcome to FlintTrade</h1>
          <p className="text-text-secondary">Choose your setup experience</p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card className="bg-surface-card border-border-default cursor-pointer hover:border-accent transition-colors" onClick={() => navigate("/terminal")}>
            <CardHeader>
              <CardTitle className="text-text-primary">Quick Setup</CardTitle>
              <CardDescription>2 steps — connect and go</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-text-muted text-sm">OpenAlgo URL + API key, pick persona, start trading.</p>
            </CardContent>
          </Card>
          <Card className="bg-surface-card border-border-default cursor-pointer hover:border-accent transition-colors" onClick={() => navigate("/terminal")}>
            <CardHeader>
              <CardTitle className="text-text-primary">Guided Setup</CardTitle>
              <CardDescription>5 steps — personalized</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-text-muted text-sm">Persona, connection, experience level, trading defaults, done.</p>
            </CardContent>
          </Card>
          <Card className="bg-surface-card border-border-default cursor-pointer hover:border-accent transition-colors" onClick={() => navigate("/terminal")}>
            <CardHeader>
              <CardTitle className="text-text-primary">Advanced Setup</CardTitle>
              <CardDescription>7 steps — full control</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-text-muted text-sm">Everything above plus LLM config, Telegram, data paths, risk limits.</p>
            </CardContent>
          </Card>
        </div>
        <div className="text-center">
          <Button variant="ghost" className="text-text-muted" onClick={() => navigate("/terminal")}>
            Skip setup
          </Button>
        </div>
      </div>
    </div>
  );
}
