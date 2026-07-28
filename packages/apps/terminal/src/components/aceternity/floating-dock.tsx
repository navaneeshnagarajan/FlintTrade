/**
 * floating-dock.tsx
 * Aceternity UI — macOS-style floating dock navigation.
 * Adapted: next/link → react-router Link, next/image → lucide-react icons,
 *          framer-motion v12, TypeScript strict, no `any`.
 */
import { useRef, useState } from "react";
import { Link, useLocation } from "react-router";
import {
  motion,
  useMotionValue,
  useSpring,
  useTransform,
  AnimatePresence,
} from "framer-motion";
import { type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface DockItem {
  title: string;
  icon: LucideIcon;
  href: string;
}

interface FloatingDockProps {
  items: DockItem[];
  className?: string;
  /** Desktop: rendered as a vertical or horizontal rail. Default: horizontal. */
  orientation?: "horizontal" | "vertical";
}

export function FloatingDock({
  items,
  className,
  orientation = "horizontal",
}: FloatingDockProps) {
  return (
    <>
      {/* Mobile: bottom bar */}
      <FloatingDockMobile items={items} className={cn("block md:hidden", className)} />
      {/* Desktop: dock */}
      <FloatingDockDesktop
        items={items}
        orientation={orientation}
        className={cn("hidden md:flex", className)}
      />
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Mobile variant                                                       */
/* ------------------------------------------------------------------ */

function FloatingDockMobile({
  items,
  className,
}: {
  items: DockItem[];
  className?: string;
}) {
  const location = useLocation();
  const [open, setOpen] = useState(false);

  return (
    <div className={cn("relative block md:hidden", className)}>
      <AnimatePresence>
        {open && (
          <motion.div
            layoutId="nav"
            className="absolute inset-x-0 bottom-full mb-2 flex flex-col gap-2"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
          >
            {items.map((item, i) => {
              const Icon = item.icon;
              const isActive = location.pathname === item.href;
              return (
                <motion.div
                  key={item.title}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 8, transition: { delay: i * 0.05 } }}
                  transition={{ delay: (items.length - 1 - i) * 0.05 }}
                >
                  <Link
                    to={item.href}
                    aria-label={item.title}
                    className={cn(
                      "flex h-10 w-10 items-center justify-center rounded-full",
                      "bg-glass-chrome border border-glass-chrome backdrop-glass",
                      isActive && "border-white/10 bg-white/10",
                    )}
                    onClick={() => setOpen(false)}
                  >
                    <Icon className="h-5 w-5 text-text-primary" />
                  </Link>
                </motion.div>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
      <button
        onClick={() => setOpen(!open)}
        aria-label="Toggle navigation"
        className={cn(
          "flex h-10 w-10 items-center justify-center rounded-full",
          "bg-glass-chrome border border-glass-chrome backdrop-glass",
        )}
      >
        {/* Hamburger / close icon */}
        <svg
          className="h-5 w-5 text-text-primary"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          aria-hidden="true"
        >
          {open ? (
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          ) : (
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
          )}
        </svg>
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Desktop variant with magnification                                  */
/* ------------------------------------------------------------------ */

function FloatingDockDesktop({
  items,
  orientation,
  className,
}: {
  items: DockItem[];
  orientation: "horizontal" | "vertical";
  className?: string;
}) {
  const mousePos = useMotionValue(Infinity);

  return (
    <motion.div
      onMouseMove={(e) =>
        mousePos.set(orientation === "horizontal" ? e.pageX : e.pageY)
      }
      onMouseLeave={() => mousePos.set(Infinity)}
      className={cn(
        "mx-auto hidden items-center gap-4 rounded-2xl px-4 py-3 md:flex",
        "bg-glass-chrome border border-glass-chrome backdrop-glass",
        orientation === "vertical" && "flex-col",
        className,
      )}
    >
      {items.map((item) => (
        <IconContainer
          key={item.title}
          mousePos={mousePos}
          item={item}
          orientation={orientation}
        />
      ))}
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/* Single dock icon with spring magnification                          */
/* ------------------------------------------------------------------ */

function IconContainer({
  mousePos,
  item,
  orientation,
}: {
  mousePos: ReturnType<typeof useMotionValue<number>>;
  item: DockItem;
  orientation: "horizontal" | "vertical";
}) {
  const ref = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const [hovered, setHovered] = useState(false);
  const isActive = location.pathname === item.href;

  const distance = useTransform(mousePos, (val) => {
    const bounds = ref.current?.getBoundingClientRect() ?? { x: 0, y: 0, width: 0, height: 0 };
    const center =
      orientation === "horizontal"
        ? bounds.x + bounds.width / 2
        : bounds.y + bounds.height / 2;
    return val - center;
  });

  const widthTransform = useTransform(distance, [-150, 0, 150], [40, 80, 40]);
  const heightTransform = useTransform(distance, [-150, 0, 150], [40, 80, 40]);
  const widthIconTransform = useTransform(distance, [-150, 0, 150], [20, 40, 20]);
  const heightIconTransform = useTransform(distance, [-150, 0, 150], [20, 40, 20]);

  const width = useSpring(widthTransform, { mass: 0.1, stiffness: 150, damping: 12 });
  const height = useSpring(heightTransform, { mass: 0.1, stiffness: 150, damping: 12 });
  const widthIcon = useSpring(widthIconTransform, { mass: 0.1, stiffness: 150, damping: 12 });
  const heightIcon = useSpring(heightIconTransform, { mass: 0.1, stiffness: 150, damping: 12 });

  const Icon = item.icon;

  return (
    <Link to={item.href} aria-label={item.title}>
      <motion.div
        ref={ref}
        style={{ width, height }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        className={cn(
          "relative flex aspect-square items-center justify-center rounded-full",
          "bg-glass-l2 border border-glass-l2",
          isActive && "border-white/12 bg-white/8",
          "transition-colors duration-150",
        )}
      >
        {/* Tooltip */}
        <AnimatePresence>
          {hovered && (
            <motion.div
              initial={{ opacity: 0, y: orientation === "vertical" ? 0 : 10, x: orientation === "vertical" ? 10 : 0 }}
              animate={{ opacity: 1, y: 0, x: 0 }}
              exit={{ opacity: 0, y: orientation === "vertical" ? 0 : 2, x: orientation === "vertical" ? 2 : 0 }}
              className={cn(
                "absolute whitespace-pre rounded-md px-2 py-0.5 text-xs text-text-primary",
                "bg-glass-chrome border border-glass-chrome",
                orientation === "vertical"
                  ? "left-full ml-2"
                  : "-top-8 left-1/2 -translate-x-1/2",
              )}
            >
              {item.title}
            </motion.div>
          )}
        </AnimatePresence>
        <motion.div style={{ width: widthIcon, height: heightIcon }} className="flex items-center justify-center">
          <Icon className="h-full w-full text-text-secondary" />
        </motion.div>
        {/* Active indicator dot */}
        {isActive && (
          <span className="absolute bottom-0.5 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full bg-profit" />
        )}
      </motion.div>
    </Link>
  );
}
