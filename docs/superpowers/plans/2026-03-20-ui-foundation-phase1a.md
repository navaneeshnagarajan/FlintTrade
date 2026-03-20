# UI Foundation Overhaul — Phase 1A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the amateur design system with professional trading terminal aesthetics — new design tokens, font pairing (Geist + Inter + JetBrains Mono), updated shadcn/ui components, and elimination of all arbitrary text sizes.

**Architecture:** Update `index.css` design tokens (single source of truth), then modify 6 shadcn/ui base components, then run global find-and-replace across ~40 files to remove arbitrary sizes. Each step produces a passing build. Sub-commits at each task boundary.

**Tech Stack:** React 19, Tailwind CSS v4 (`@tailwindcss/vite`), shadcn/ui, Geist font (npm), CSS custom properties

**Spec:** `docs/superpowers/specs/2026-03-20-ui-foundation-overhaul-design.md`

---

## File Structure

### Modified files
| File | Responsibility |
|------|---------------|
| `package.json` | Add `geist` dependency |
| `src/index.css` | Design tokens, font imports, utilities, Dockview overrides, scrollbars, density modes |
| `src/components/ui/button.tsx` | Add shadow, improve hover/active |
| `src/components/ui/input.tsx` | Fix placeholder contrast |
| `src/components/ui/card.tsx` | rounded-lg, shadow-sm, p-4 defaults |
| `src/components/ui/table.tsx` | Striped rows, hover, improved padding |
| `src/components/ui/badge.tsx` | Add trading signal variants (bullish/bearish/atm/neutral) |
| `src/chrome/TopBar.tsx` | font-heading for titles, Logo component |
| `src/chrome/TickerBar.tsx` | Spacing, change% pill styling |
| `src/chrome/WidgetPicker.tsx` | Card sizing, font-heading |
| All widgets/tools/routes (~30 files) | Replace arbitrary text-[Npx] and text-[#color] |

### New files
| File | Responsibility |
|------|---------------|
| `src/components/brand/Logo.tsx` | SVG logo + wordmark React component |

---

## Task 1: Install Geist Font + Update Design Tokens

**Files:**
- Modify: `packages/terminal/package.json`
- Modify: `packages/terminal/src/index.css`

- [ ] **Step 1: Install geist font package**

```bash
cd packages/terminal && npm install geist
```

- [ ] **Step 2: Rewrite `src/index.css` with new design tokens**

Replace the ENTIRE file with the new design system. Key changes:
- Add `@import 'geist/font/sans.css'` for Geist font
- Register `--font-heading` in `@theme inline`
- Add `@utility text-xxs` for Tailwind v4
- Update all surface colors: card `#12121a` → `#16161f`
- Update all border colors: `#1e1e2e` → `#2a2a3a`
- Update text-muted: `#52525b` → `#6b6b78`
- Add semantic trading colors (bullish/bearish/atm/neutral/itm/otm)
- Add density mode CSS rules
- Update Dockview overrides to use CSS variables
- Update scrollbar colors to use tokens

The new `index.css`:
```css
@import "tailwindcss";
@import "geist/font/sans.css";

/* ---------- text-xxs utility (Tailwind v4) ---------- */
@utility text-xxs {
  font-size: 10px;
  line-height: 14px;
}

/* ---------- Base variables (shadcn/ui compat) ---------- */
@layer base {
  :root {
    --radius: 0.5rem;
    --background: 240 10% 3.9%;
    --foreground: 240 5% 89%;
    --card: 240 8% 8.5%;
    --card-foreground: 240 5% 89%;
    --popover: 240 8% 11%;
    --popover-foreground: 240 5% 89%;
    --primary: 217 91% 60%;
    --primary-foreground: 0 0% 100%;
    --secondary: 240 5% 15%;
    --secondary-foreground: 240 5% 89%;
    --muted: 240 5% 15%;
    --muted-foreground: 240 4% 46%;
    --accent: 240 5% 15%;
    --accent-foreground: 240 5% 89%;
    --destructive: 0 84% 60%;
    --destructive-foreground: 0 0% 100%;
    --border: 240 8% 18%;
    --input: 240 8% 18%;
    --ring: 217 91% 60%;
    --chart-1: 217 91% 60%;
    --chart-2: 142 71% 45%;
    --chart-3: 0 84% 60%;
    --chart-4: 48 96% 53%;
    --chart-5: 280 65% 60%;
  }
}

/* ---------- Theme tokens ---------- */
@theme inline {
  /* shadcn/ui standard tokens */
  --color-background: hsl(var(--background));
  --color-foreground: hsl(var(--foreground));
  --color-card: hsl(var(--card));
  --color-card-foreground: hsl(var(--card-foreground));
  --color-popover: hsl(var(--popover));
  --color-popover-foreground: hsl(var(--popover-foreground));
  --color-primary: hsl(var(--primary));
  --color-primary-foreground: hsl(var(--primary-foreground));
  --color-secondary: hsl(var(--secondary));
  --color-secondary-foreground: hsl(var(--secondary-foreground));
  --color-muted: hsl(var(--muted));
  --color-muted-foreground: hsl(var(--muted-foreground));
  --color-accent: hsl(var(--accent));
  --color-accent-foreground: hsl(var(--accent-foreground));
  --color-destructive: hsl(var(--destructive));
  --color-destructive-foreground: hsl(var(--destructive-foreground));
  --color-border: hsl(var(--border));
  --color-input: hsl(var(--input));
  --color-ring: hsl(var(--ring));
  --color-chart-1: hsl(var(--chart-1));
  --color-chart-2: hsl(var(--chart-2));
  --color-chart-3: hsl(var(--chart-3));
  --color-chart-4: hsl(var(--chart-4));
  --color-chart-5: hsl(var(--chart-5));
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);

  /* --- Fonts (3-tier: heading / body / data) --- */
  --font-heading: 'Geist', system-ui, sans-serif;
  --font-sans: 'Inter', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;

  /* --- Surface colors --- */
  --color-surface-base: #0a0a0f;
  --color-surface-card: #16161f;
  --color-surface-elevated: #1e1e28;
  --color-surface-hover: #24242e;
  --color-surface-active: #2e2e3a;
  --color-surface-stripe: #0e0e16;

  /* --- Border colors --- */
  --color-border-default: #2a2a3a;
  --color-border-subtle: #1e1e2e;
  --color-border-strong: #3a3a4a;

  /* --- Text colors --- */
  --color-text-primary: #e4e4e7;
  --color-text-secondary: #8b8b95;
  --color-text-muted: #6b6b78;
  --color-text-disabled: #45454f;

  /* --- Trading semantic colors --- */
  --color-profit: #22c55e;
  --color-loss: #ef4444;
  --color-warning: #eab308;

  --color-bullish-bg: rgba(34, 197, 94, 0.10);
  --color-bullish-border: rgba(34, 197, 94, 0.30);
  --color-bullish-text: #22c55e;

  --color-bearish-bg: rgba(239, 68, 68, 0.10);
  --color-bearish-border: rgba(239, 68, 68, 0.30);
  --color-bearish-text: #ef4444;

  --color-atm-bg: rgba(234, 179, 8, 0.08);
  --color-atm-border: rgba(234, 179, 8, 0.30);
  --color-atm-text: #eab308;

  --color-neutral-bg: rgba(59, 130, 246, 0.10);
  --color-neutral-border: rgba(59, 130, 246, 0.30);
  --color-neutral-text: #3b82f6;

  --color-itm-text: #22c55e;
  --color-otm-text: #f97315;
}

/* ---------- Fluid typography ---------- */
@layer base {
  :root {
    --text-2xl: clamp(20px, 2vw, 24px);
    --text-lg: clamp(16px, 1.5vw, 18px);
  }
}

/* ---------- Responsive breakpoints ---------- */
@media (max-width: 1279px) {
  html { --card-padding: 12px; --widget-padding: 12px; }
}
@media (min-width: 1920px) {
  html { --widget-padding: 24px; }
}

/* ---------- Global resets ---------- */
* {
  scrollbar-width: thin;
  scrollbar-color: var(--color-border-default) transparent;
}
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--color-border-default); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--color-border-strong); }

body {
  margin: 0;
  overflow: hidden;
  background-color: var(--color-surface-base);
  color: var(--color-text-primary);
  font-family: var(--font-sans);
}

/* ---------- Density modes ---------- */
html, html.density-comfortable {
  --table-cell-px: 12px;
  --table-cell-py: 10px;
  --card-padding: 16px;
  --widget-padding: 16px;
  --input-height: 36px;
  --button-height: 36px;
}

html.density-compact {
  --table-cell-px: 8px;
  --table-cell-py: 6px;
  --card-padding: 12px;
  --widget-padding: 12px;
  --input-height: 32px;
  --button-height: 32px;
}

/* ---------- Dockview theme overrides ---------- */
.dockview-theme-dark {
  --dv-activegroup-visiblepanel-tab-background-color: var(--color-surface-card);
  --dv-activegroup-hiddenpanel-tab-background-color: var(--color-surface-base);
  --dv-inactivegroup-visiblepanel-tab-background-color: var(--color-surface-card);
  --dv-inactivegroup-hiddenpanel-tab-background-color: var(--color-surface-base);
  --dv-tab-divider-color: var(--color-border-subtle);
  --dv-activegroup-visiblepanel-tab-color: var(--color-text-primary);
  --dv-activegroup-hiddenpanel-tab-color: var(--color-text-muted);
  --dv-inactivegroup-visiblepanel-tab-color: var(--color-text-secondary);
  --dv-inactivegroup-hiddenpanel-tab-color: var(--color-text-muted);
  --dv-separator-border: var(--color-border-default);
  --dv-paneview-header-border-color: var(--color-border-default);
  --dv-background-color: var(--color-surface-base);
  --dv-group-view-background-color: var(--color-surface-base);
}
```

- [ ] **Step 3: Verify build**

```bash
cd packages/terminal && npx tsc --noEmit && npm run build
```
Expected: 0 errors, clean build.

- [ ] **Step 4: Commit**

```bash
git add packages/terminal/package.json packages/terminal/package-lock.json packages/terminal/src/index.css
git commit -m "feat(terminal): install Geist font + update design tokens

- 3-tier font stack: Geist (headings) + Inter (body) + JetBrains Mono (data)
- Surface colors: card #16161f, elevated #1e1e28, stripe #0e0e16
- Borders: default #2a2a3a, subtle #1e1e2e, strong #3a3a4a
- Text: secondary #8b8b95, muted #6b6b78 (WCAG AA fix)
- Trading semantics: bullish/bearish/atm/neutral bg+border+text
- Density modes: comfortable (default) + compact via html class
- Dockview overrides use CSS variables
- text-xxs utility (10px) for uppercase labels"
```

---

## Task 2: Update shadcn/ui Base Components

**Files:**
- Modify: `src/components/ui/button.tsx`
- Modify: `src/components/ui/input.tsx`
- Modify: `src/components/ui/card.tsx`
- Modify: `src/components/ui/table.tsx`
- Modify: `src/components/ui/badge.tsx`
- Modify: `src/components/ui/textarea.tsx`

- [ ] **Step 1: Update `button.tsx` — add shadow, improve ghost hover**

Change the `default` variant to include `shadow-sm`:
```
default: "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90",
```

Change the `outline` variant:
```
outline: "border border-border-default bg-surface-card shadow-xs hover:bg-surface-hover hover:text-accent-foreground",
```

Change the `ghost` variant:
```
ghost: "hover:bg-surface-hover hover:text-accent-foreground",
```

- [ ] **Step 2: Update `card.tsx` — rounded-lg, shadow-sm**

Change Card className from:
```
"flex flex-col gap-6 rounded-xl border bg-card py-6 text-card-foreground shadow-sm"
```
To:
```
"flex flex-col gap-4 rounded-lg border border-border-default bg-surface-card p-4 text-card-foreground shadow-sm"
```

Change CardHeader px-6 → px-4, CardContent px-6 → px-4, CardFooter px-6 → px-4.

- [ ] **Step 3: Update `table.tsx` — striped rows, hover, padding**

Update `TableRow` to add striped rows:
```
"border-b border-border-subtle transition-colors hover:bg-surface-hover data-[state=selected]:bg-surface-active even:bg-surface-stripe"
```

Update `TableHead` padding from `px-2` to `px-3 py-2.5`:
```
"h-10 px-3 py-2.5 text-left align-middle font-medium whitespace-nowrap text-xxs uppercase tracking-wider text-text-secondary ..."
```

Update `TableCell` padding from `p-2` to `px-3 py-2.5`:
```
"px-3 py-2.5 align-middle whitespace-nowrap text-sm ..."
```

- [ ] **Step 4: Update `badge.tsx` — add trading signal variants**

Add these variants to `badgeVariants`:
```typescript
bullish: "bg-bullish-bg border-bullish-border text-bullish-text",
bearish: "bg-bearish-bg border-bearish-border text-bearish-text",
atm: "bg-atm-bg border-atm-border text-atm-text",
neutral: "bg-neutral-bg border-neutral-border text-neutral-text",
```

Keep `rounded-full` as default. Add `rounded` only to the new trading variants so existing badges are unaffected.

- [ ] **Step 5: Verify build**

```bash
cd packages/terminal && npx tsc --noEmit && npx vitest run
```
Expected: 0 errors, 26/26 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/components/ui/
git commit -m "feat(terminal): update shadcn base components for trading UI

- button: shadow-sm on default, surface-hover on ghost/outline
- card: rounded-lg (from xl), p-4 (from p-6), border-border-default
- table: striped rows (even:bg-surface-stripe), hover, px-3 py-2.5, uppercase headers
- badge: add bullish/bearish/atm/neutral trading variants (rounded), keep rounded-full for existing
- input: border-border-default, adjusted focus ring
- textarea: replace hardcoded colors with design tokens"
```

---

## Task 3: Global Text-Size Migration

This is the biggest task — ~813 arbitrary values across ~30 files. Split into sub-tasks by file group.

**Important:** Some `text-[#hex]` values are arbitrary COLORS, not sizes. These need to be replaced with design token colors (`text-text-primary`, `text-text-secondary`, `text-text-muted`), NOT size classes.

- [ ] **Step 1: Replace arbitrary text SIZES**

Run these replacements across all `.tsx` and `.ts` files in `src/`:
```
text-[8px]  → text-xxs
text-[9px]  → text-xxs
text-[10px] → text-xs
text-[11px] → text-xs
text-[12px] → text-xs
text-[13px] → text-sm
text-[14px] → text-sm
text-[15px] → text-sm
text-[16px] → text-base
```

Use editor find-and-replace or sed. Verify each file compiles after replacement.

- [ ] **Step 2: Replace arbitrary text COLORS**

Common patterns to replace:
```
text-[#e0e0f0] → text-text-primary
text-[#c0c0d0] → text-text-primary
text-[#a0a0b0] → text-text-secondary
text-[#8a8a9a] → text-text-secondary
text-[#6b6b8a] → text-text-muted
text-[#4a4a6a] → text-text-muted
text-[#3a3a5a] → text-text-disabled
```

Also replace arbitrary bg colors with tokens:
```
bg-[#0a0a0f] → bg-surface-base
bg-[#12121a] → bg-surface-card (now #16161f via token)
bg-[#1e1e2e] → bg-border-default
```

Also replace arbitrary border colors (~172 occurrences across 11 files):
```
border-[#1e1e2e] → border-border-default (now #2a2a3a via token)
border-[#16161f] → border-border-subtle
border-[#2a2a3a] → border-border-default
border-[#3a3a4a] → border-border-strong
border-[#12121a] → border-border-subtle
```

Also update `textarea.tsx` — replace hardcoded `border-[#1e1e2e]`, `bg-[#12121a]`, `text-[#e0e0f0]`, `placeholder:text-[#4a4a6a]`, `ring-[#3b82f6]` with design tokens.

- [ ] **Step 3: Replace `h-5` on inputs/buttons with `h-8` or `h-9`**

Find all `h-5` on interactive elements (inputs, buttons, selects) and replace with `h-8` (compact) or `h-9` (standard).

- [ ] **Step 4: Replace tight widget padding**

Find widget wrapper divs using `p-2` and replace with `p-3` or `p-4`.

- [ ] **Step 5: Verify zero arbitrary values remain**

```bash
cd packages/terminal
grep -rn 'text-\[' src/ --include='*.tsx' --include='*.ts' | grep -v node_modules | grep -v '.test.' | wc -l
```
Expected: 0 (or very close — some may be legitimate one-off overrides in Glide grid)

- [ ] **Step 6: Full verify**

```bash
npx tsc --noEmit && npx vitest run && npm run build
```

- [ ] **Step 7: Commit**

```bash
git add -u src/
git commit -m "refactor(terminal): replace all arbitrary text sizes and colors with design tokens

- ~813 arbitrary text-[Npx] and text-[#hex] replaced
- text-[10px]/text-[11px] → text-xs
- text-[9px] → text-xxs
- text-[13px]/text-[14px] → text-sm
- Arbitrary colors → text-text-primary/secondary/muted
- Widget padding p-2 → p-3/p-4
- Input/button h-5 → h-8/h-9"
```

---

## Task 4: Create Logo SVG Component

**Files:**
- Create: `src/components/brand/Logo.tsx`

- [ ] **Step 1: Create Logo component**

Create `src/components/brand/Logo.tsx` with:
- `LogoIcon` — standalone geometric "F" with spark motif (SVG)
- `LogoWordmark` — "FlintTrade" text in Geist 700
- `Logo` — combined icon + wordmark
- Props: `size`, `variant` ("full" | "icon" | "wordmark"), `className`

- [ ] **Step 2: Verify component renders**

```bash
npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add src/components/brand/
git commit -m "feat(terminal): add SVG Logo component with icon, wordmark, and full variants"
```

---

## Task 5: Update Chrome Components

**Files:**
- Modify: `src/chrome/TopBar.tsx`
- Modify: `src/chrome/TickerBar.tsx`
- Modify: `src/chrome/WidgetPicker.tsx`

- [ ] **Step 1: Update TopBar**

- Replace FT image with `<LogoIcon />` component
- Use `font-heading` for workspace tab titles
- Improve connection indicator: larger dot (w-2 h-2), ring glow when connected
- Use design token colors throughout

- [ ] **Step 2: Update TickerBar**

- Replace arbitrary text sizes with `text-xs`
- Add pill background for change% (`bg-bullish-bg` / `bg-bearish-bg`)
- Use `font-mono tabular-nums` for all numbers
- Tighten spacing: `px-3` instead of `px-4`

- [ ] **Step 3: Update WidgetPicker**

- Use `font-heading` for category headers
- Use `text-sm` for widget names, `text-xs text-text-muted` for descriptions
- Improve card hover: `bg-surface-hover` transition

- [ ] **Step 4: Verify**

```bash
npx tsc --noEmit && npx vitest run && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add src/chrome/ src/components/brand/
git commit -m "feat(terminal): update chrome with Logo, font-heading, and token colors

- TopBar: SVG LogoIcon, font-heading tab titles, improved connection indicator
- TickerBar: font-mono numbers, change% pill backgrounds, text-xs labels
- WidgetPicker: font-heading headers, improved hover states"
```

---

## Task 6: Final Verification

- [ ] **Step 1: TypeScript check**
```bash
npx tsc --noEmit
```
Expected: 0 errors.

- [ ] **Step 2: Tests**
```bash
npx vitest run
```
Expected: 26/26 pass.

- [ ] **Step 3: Production build**
```bash
npm run build
```
Expected: clean build, no warnings.

- [ ] **Step 4: Grep for remaining arbitrary values**
```bash
grep -rn 'text-\[' src/ --include='*.tsx' --include='*.ts' | grep -v '.test.' | wc -l
```
Expected: 0 or near-0.

- [ ] **Step 5: Visual verification via Playwright**

Navigate to all 4 routes and take screenshots:
- http://localhost:5173/terminal (Dashboard + Option Chain)
- http://localhost:5173/setup
- http://localhost:5173/invest
- http://localhost:5173/learn

Verify: cards have visible borders, text is readable, numbers are monospace, no visual regressions.

- [ ] **Step 6: Update ACTIVE_SESSION.md**

Mark all Phase 1A steps as complete. Update DEVLOG.md.
