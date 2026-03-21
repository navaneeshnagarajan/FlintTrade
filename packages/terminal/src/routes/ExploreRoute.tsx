import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ArrowRight } from "lucide-react";

/**
 * ExploreRoute -- placeholder for the pre-auth exploration page.
 * Directs users to /setup to configure their workspace.
 */
export default function ExploreRoute() {
  return (
    <div className="min-h-screen bg-surface-base flex items-center justify-center p-4">
      <div className="text-center space-y-6 max-w-md">
        <h1 className="font-heading font-bold text-2xl text-text-primary tracking-tight">
          Explore FlintTrade
        </h1>
        <p className="text-sm text-text-secondary">
          Coming soon. Browse features, strategies, and market tools before signing up.
        </p>
        <Button asChild className="bg-primary hover:bg-primary/90 text-primary-foreground">
          <Link to="/setup">
            Set Up Workspace
            <ArrowRight className="size-4 ml-2" />
          </Link>
        </Button>
      </div>
    </div>
  );
}
