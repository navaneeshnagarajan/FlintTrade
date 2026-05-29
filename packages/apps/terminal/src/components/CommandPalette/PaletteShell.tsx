// PaletteShell.tsx
import { useCallback, type ReactNode } from "react";
import { layerClassNames } from "@flinttrade/design-system";
import { cn } from "@/lib/utils";

interface PaletteShellProps {
  isOpen: boolean;
  onClose: () => void;
  children: ReactNode;
}

export function PaletteShell({ isOpen, onClose, children }: PaletteShellProps) {
  const handleOverlayClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (e.target === e.currentTarget) onClose();
    },
    [onClose],
  );

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      onClick={handleOverlayClick}
      className={cn(
        "fixed inset-0 flex items-start justify-center pt-[12vh] bg-black/50 backdrop-blur-sm animate-in fade-in duration-150",
        layerClassNames.modal,
      )}
    >
      <div
        className={cn(
          "w-full max-w-xl mx-4 flex flex-col",
          "glass-surface-l1 rounded-glass-card shadow-2xl overflow-hidden",
          "animate-in fade-in slide-in-from-top-4 duration-200",
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
