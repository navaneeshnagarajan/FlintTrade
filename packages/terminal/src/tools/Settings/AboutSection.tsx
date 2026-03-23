/**
 * AboutSection — version info, links, and build details.
 */

import { Settings, Github, ExternalLink } from "lucide-react";
import { SectionTitle } from "./shared";

export function AboutSection() {
  return (
    <div className="space-y-5">
      <SectionTitle>About</SectionTitle>

      <div className="flex items-center gap-3 p-4 rounded-lg bg-surface-card border border-border-default">
        <div className="flex-none w-10 h-10 rounded-lg bg-accent/10 border border-accent/20 flex items-center justify-center">
          <Settings size={18} className="text-accent" />
        </div>
        <div>
          <div className="text-sm font-semibold text-text-primary">FlintTrade</div>
          <div className="text-xs text-text-muted">Version 0.1.0-alpha</div>
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">Description</p>
        <p className="text-xs text-text-secondary leading-relaxed">
          Open-source modular trading and investment platform for Indian F&amp;O, commodities, and crypto.
          Built on OpenAlgo (30+ broker gateway). Monorepo with 12 packages (11 Python + 1 React).
        </p>
      </div>

      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">Links</p>
        <div className="space-y-1.5">
          <a
            href="https://github.com/navaneeshnagarajan/FlintTrade"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-3 py-2 rounded border border-border-default bg-surface-card hover:bg-surface-hover text-xs text-text-secondary hover:text-text-primary transition-colors"
          >
            <Github size={12} className="flex-none text-text-muted" />
            <span>GitHub — navaneeshnagarajan/FlintTrade</span>
            <ExternalLink size={10} className="ml-auto text-text-muted flex-none" />
          </a>
          <a
            href="https://github.com/navaneeshnagarajan/openalgo"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-3 py-2 rounded border border-border-default bg-surface-card hover:bg-surface-hover text-xs text-text-secondary hover:text-text-primary transition-colors"
          >
            <ExternalLink size={12} className="flex-none text-text-muted" />
            <span>OpenAlgo — Broker Gateway</span>
            <ExternalLink size={10} className="ml-auto text-text-muted flex-none" />
          </a>
          <a
            href="https://www.gnu.org/licenses/agpl-3.0.html"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-3 py-2 rounded border border-border-default bg-surface-card hover:bg-surface-hover text-xs text-text-secondary hover:text-text-primary transition-colors"
          >
            <ExternalLink size={12} className="flex-none text-text-muted" />
            <span>License — GNU AGPL-3.0</span>
            <ExternalLink size={10} className="ml-auto text-text-muted flex-none" />
          </a>
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">Build Info</p>
        <div className="rounded border border-border-default overflow-hidden">
          <table className="w-full text-xs">
            <tbody>
              {[
                ["Version",  "0.1.0-alpha"],
                ["React",    "19"          ],
                ["Dockview", "5.1"         ],
                ["License",  "AGPL-3.0"   ],
              ].map(([key, val]) => (
                <tr key={key} className="border-b border-border-default last:border-0">
                  <td className="px-3 py-1.5 text-text-muted w-32">{key}</td>
                  <td className="px-3 py-1.5 text-text-primary font-mono">{val}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
