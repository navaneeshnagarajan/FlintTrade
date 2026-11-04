import { createContext, useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";

// The shell owns only the destination. Composition, drafts and handlers remain
// in the retained app. Undefined supports standalone app mounts; null waits for
// the shell's stable destination instead of mounting then reparenting inputs.
export const WorkspaceChromeTarget = createContext<HTMLElement | null | undefined>(undefined);
export function WorkspaceChrome({ children }: { children: ReactNode }) {
  const target = useContext(WorkspaceChromeTarget);
  return target === undefined ? children : target ? createPortal(children, target) : null;
}
