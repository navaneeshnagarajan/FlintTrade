/**
 * focus-cards.tsx
 * Aceternity UI — Cards that blur siblings when one is hovered.
 * Adapted: React 19, TypeScript strict, no `any`, no Next.js deps.
 */
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/* Types                                                                */
/* ------------------------------------------------------------------ */

export interface FocusCard {
  title: string;
  /** URL for a background image OR a ReactNode (icon / custom content). */
  src?: string;
  content?: ReactNode;
}

interface FocusCardsProps {
  cards: FocusCard[];
  className?: string;
  cardClassName?: string;
}

/* ------------------------------------------------------------------ */
/* Card                                                                 */
/* ------------------------------------------------------------------ */

function Card({
  card,
  index,
  hovered,
  setHovered,
  cardClassName,
}: {
  card: FocusCard;
  index: number;
  hovered: number | null;
  setHovered: (index: number | null) => void;
  cardClassName?: string;
}) {
  const isBlurred = hovered !== null && hovered !== index;

  return (
    <div
      onMouseEnter={() => setHovered(index)}
      onMouseLeave={() => setHovered(null)}
      className={cn(
        "relative h-60 w-full cursor-pointer overflow-hidden rounded-glass-card",
        "bg-glass-l1 border border-glass-l1 backdrop-glass",
        "transition-all duration-300 ease-out",
        isBlurred ? "scale-[0.98] blur-sm opacity-60" : "opacity-100",
        cardClassName,
      )}
    >
      {/* Background image */}
      {card.src && (
        <div
          className="absolute inset-0 bg-cover bg-center"
          style={{ backgroundImage: `url(${card.src})` }}
          aria-hidden="true"
        />
      )}

      {/* Gradient overlay */}
      <div
        className={cn(
          "absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent",
          "transition-opacity duration-300",
          hovered === index ? "opacity-100" : "opacity-70",
        )}
        aria-hidden="true"
      />

      {/* Custom content */}
      {card.content && (
        <div className="absolute inset-0 flex items-center justify-center p-4">
          {card.content}
        </div>
      )}

      {/* Title */}
      <div className="absolute bottom-0 left-0 right-0 p-4">
        <p className="text-sm font-semibold text-white drop-shadow-md">{card.title}</p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Container                                                            */
/* ------------------------------------------------------------------ */

export function FocusCards({ cards, className, cardClassName }: FocusCardsProps) {
  const [hovered, setHovered] = useState<number | null>(null);

  return (
    <div
      className={cn(
        "mx-auto grid w-full grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3",
        className,
      )}
    >
      {cards.map((card, i) => (
        <Card
          key={card.title}
          card={card}
          index={i}
          hovered={hovered}
          setHovered={setHovered}
          cardClassName={cardClassName}
        />
      ))}
    </div>
  );
}
