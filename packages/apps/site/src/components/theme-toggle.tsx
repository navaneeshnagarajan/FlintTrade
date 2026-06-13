'use client';

/**
 * ThemeToggle — dark / light / system pill, identical in behaviour and
 * look to the terminal WelcomeRoute's ThemeToggle. Backed by next-themes
 * (provided by the fumadocs RootProvider).
 */

import { Monitor, Moon, Sun } from 'lucide-react';
import { useTheme } from 'next-themes';
import { useEffect, useState } from 'react';

const MODES = [
  { id: 'dark', label: 'Switch to dark mode', icon: Moon },
  { id: 'light', label: 'Switch to light mode', icon: Sun },
  { id: 'system', label: 'Switch to system mode', icon: Monitor },
] as const;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <div className="theme-toggle" role="group" aria-label="Theme mode">
      {MODES.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          aria-label={label}
          aria-pressed={mounted ? theme === id : undefined}
          onClick={() => setTheme(id)}
        >
          <Icon aria-hidden="true" />
        </button>
      ))}
    </div>
  );
}
