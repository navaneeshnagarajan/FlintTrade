/** Canonical settings destinations for automation operators. */

import { Link } from "react-router";
import { ArrowUpRight, Send, ShieldAlert } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";

export default function SettingsSection() {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <GlassCard className="space-y-3 p-6">
        <ShieldAlert size={20} className="text-warning" />
        <h3 className="font-heading text-lg font-semibold text-text-primary">Risk &amp; Safety</h3>
        <p className="text-sm text-text-secondary">
          Manage the process-wide kill switch, global safety limits, and account daily-loss controls in Settings.
        </p>
        <Link to="/settings#risk" className="inline-flex items-center gap-1.5 text-sm text-accent hover:underline">
          Open Risk &amp; Safety <ArrowUpRight size={14} aria-hidden="true" />
        </Link>
      </GlassCard>
      <GlassCard className="space-y-3 p-6">
        <Send size={20} className="text-accent" />
        <h3 className="font-heading text-lg font-semibold text-text-primary">Telegram</h3>
        <p className="text-sm text-text-secondary">
          Configure Telegram notifications and send a custom test message from Settings.
        </p>
        <Link to="/settings#telegram" className="inline-flex items-center gap-1.5 text-sm text-accent hover:underline">
          Open Telegram <ArrowUpRight size={14} aria-hidden="true" />
        </Link>
      </GlassCard>
    </div>
  );
}
