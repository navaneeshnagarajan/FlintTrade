# FlintTrade UI Foundation Overhaul — Phase 1 Design Spec

**Date:** 2026-03-20
**Direction:** Hybrid — Groww 915 clean dark base + OiPulse data-rich features
**Scope:** Design tokens, spacing, typography, font pairing, color system, base components, table styling, responsive rules, logo/wordmark redesign
**Out of scope:** Individual widget redesigns (Phase 2), route pages (Phase 3)

> **CLAUDE.md override:** This spec intentionally changes the locked theme decision ("Inter UI, JetBrains Mono numbers, #12121a cards, #1e1e2e borders"). The user approved the overhaul on 2026-03-20. CLAUDE.md will be updated after implementation to reflect the new design system.

---

## Problem

The current UI uses arbitrary font sizes (~324x `text-[10px]`, ~178x `text-[11px]`, ~76x other arbitrary sizes), inconsistent spacing, low-contrast borders (#1e1e2e barely visible on #12121a), flat cards with no elevation, and tables without striped rows or hover states. Compared to Groww 915 and OiPulse, the terminal looks amateur.

## Goal

Establish a design token system in `index.css` and a set of base component patterns that every widget inherits automatically. Fix once at the foundation level — every surface improves.

---

## 1. Spacing Scale

Replace all arbitrary padding/margin with a 4px-based scale. Uses standard Tailwind spacing utilities (no custom CSS variables needed — Tailwind v4 has these built in).

| Tailwind | Value | Usage |
|----------|-------|-------|
| `gap-1` / `p-1` | 4px | Icon gaps, inline spacing |
| `gap-2` / `p-2` | 8px | Badge padding, tight table cells |
| `gap-3` / `p-3` | 12px | Button padding, card inner gaps, compact mode |
| `gap-4` / `p-4` | 16px | Card padding, section gaps (default) |
| `gap-5` / `p-5` | 20px | Intermediate spacing where 16 is too tight, 24 too wide |
| `gap-6` / `p-6` | 24px | Widget padding (wide mode), major section gaps |
| `gap-8` / `p-8` | 32px | Page-level margins |

**Rules:**
- Widget wrappers: `p-4` default, `p-3` compact, `p-6` wide
- Table cells: `px-3 py-2.5` (12px × 10px)
- Buttons: `px-4 py-2` standard, `px-3 py-1.5` compact

---

## 2. Font Pairing

Three-tier font stack. **This overrides the previous "Inter for everything" decision.**

Install Geist: `npm install geist`

| Tier | Font | Weight Range | Usage |
|------|------|-------------|-------|
| **Heading** | Geist Sans | 500–700 | Wordmark, page titles, section headers, nav items, widget titles |
| **Body** | Inter | 400–600 | Labels, descriptions, form text, tooltips, body copy, buttons |
| **Data** | JetBrains Mono | 400–600 | ALL numbers: LTP, OI, ₹ amounts, strikes, %, quantities |

**Tailwind v4 registration in `index.css`:**
```css
@theme inline {
  --font-heading: 'Geist', system-ui, sans-serif;
  --font-sans: 'Inter', sans-serif;
  --font-mono: 'JetBrains Mono', monospace;
}
```

Usage: `font-heading` for headings, `font-sans` for body, `font-mono` for data.

**Font import in `index.css`:**
```css
@import 'geist/font/sans.css';
/* Inter and JetBrains Mono already loaded via existing @import or Google Fonts */
```

**Rules:**
- Wordmark "FlintTrade": `font-heading font-bold tracking-tight` (Geist 700, -0.5px)
- Widget tab titles: `font-heading font-medium`
- Numbers NEVER use Geist or Inter — always `font-mono tabular-nums`
- Body text: `font-sans` (Inter)
- Buttons: `font-sans font-medium`

---

## 3. Typography Scale

Replace ALL arbitrary `text-[Npx]` with semantic sizes. Six levels plus one custom utility.

| Class | Size | Usage | Replaces |
|-------|------|-------|----------|
| `text-2xl` | 24px | Page titles, hero numbers (₹ funds total) | — |
| `text-lg` | 18px | Widget titles, LTP in index cards | — |
| `text-base` | 16px | Prominent body text, dialog content | `text-[16px]` |
| `text-sm` | 14px | Body text, table cells, form inputs | `text-[13px]`, `text-[14px]` |
| `text-xs` | 12px | Labels, timestamps, footnotes, table data | `text-[10px]`, `text-[11px]`, `text-[12px]` |
| `text-xxs` | 10px | Uppercase section labels ONLY (FUNDS, MARGIN) | `text-[8px]`, `text-[9px]` |

**`text-xxs` Tailwind v4 utility in `index.css`:**
```css
@utility text-xxs {
  font-size: 10px;
  line-height: 14px;
}
```

**Migration rules (Step 3):**
| Find | Replace with |
|------|-------------|
| `text-[8px]` | `text-xxs` |
| `text-[9px]` | `text-xxs` |
| `text-[10px]` | `text-xs` |
| `text-[11px]` | `text-xs` |
| `text-[12px]` | `text-xs` |
| `text-[13px]` | `text-sm` |
| `text-[14px]` | `text-sm` |

After migration, grep confirms zero `text-\[\d+px\]` matches.

---

## 4. Color System — Surfaces

Increase contrast between layers. The current card (#12121a) is L*=7.2, base (#0a0a0f) is L*=3.4 — only 3.8 units apart. New card (#16161f) is L*=9.0, giving 5.6 units of separation.

| Token | Current | New | Purpose |
|-------|---------|-----|---------|
| `--color-surface-base` | #0a0a0f | #0a0a0f | Page background (keep) |
| `--color-surface-card` | #12121a | #16161f | Card backgrounds — more distinct |
| `--color-surface-elevated` | (none) | #1e1e28 | Dropdowns, popovers, dialogs |
| `--color-surface-hover` | #1a1a26 | #24242e | Row hover, button hover |
| `--color-surface-active` | (none) | #2e2e3a | Active/pressed states |
| `--color-surface-stripe` | (none) | #0e0e16 | Alternating table rows |

---

## 5. Color System — Borders

Increase visibility. Current #1e1e2e is barely visible on the new card #16161f.

| Token | Current | New |
|-------|---------|-----|
| `--color-border-default` | #1e1e2e | #2a2a3a |
| `--color-border-subtle` | #16161f | #1e1e2e |
| `--color-border-strong` | (none) | #3a3a4a |

Also update scrollbar colors in `index.css` to use `--color-border-default` token instead of hardcoded #1e1e2e.

---

## 6. Color System — Text

Fix contrast. `text-muted` (#52525b) fails WCAG AA on dark backgrounds.

| Token | Current | New |
|-------|---------|-----|
| `--color-text-primary` | #e4e4e7 | #e4e4e7 (keep) |
| `--color-text-secondary` | #71717a | #8b8b95 |
| `--color-text-muted` | #52525b | #6b6b78 |
| `--color-text-disabled` | (none) | #45454f |

---

## 7. Semantic Colors — Trading States

New tokens for OI interpretation badges, moneyness tags, and trading signals. Each has bg (10-15% opacity) + border (30-40% opacity) + text variant.

```css
/* Bullish signals */
--color-bullish-bg: rgba(34, 197, 94, 0.10);
--color-bullish-border: rgba(34, 197, 94, 0.30);
--color-bullish-text: #22c55e;

/* Bearish signals */
--color-bearish-bg: rgba(239, 68, 68, 0.10);
--color-bearish-border: rgba(239, 68, 68, 0.30);
--color-bearish-text: #ef4444;

/* ATM / Warning */
--color-atm-bg: rgba(234, 179, 8, 0.08);
--color-atm-border: rgba(234, 179, 8, 0.30);
--color-atm-text: #eab308;

/* Neutral */
--color-neutral-bg: rgba(59, 130, 246, 0.10);
--color-neutral-border: rgba(59, 130, 246, 0.30);
--color-neutral-text: #3b82f6;

/* ITM / OTM */
--color-itm-text: #22c55e;
--color-otm-text: #f97315;
```

---

## 8. Component Patterns

### Buttons
- Min height: `h-9` (36px) standard, `h-8` (32px) compact
- Padding: `px-4 py-2` standard, `px-3 py-1.5` compact
- Border radius: `rounded-md` (6px)
- Shadow: `shadow-sm` on default variant
- Hover: bg `surface-hover` + shadow increase
- Active: bg `surface-active`, shadow removed (pressed)

### Inputs
- Height: `h-9` (36px) standard, `h-8` (32px) compact
- Padding: `px-3` (12px)
- Font size: `text-sm` (14px)
- Border: `border-border-default`, focus: `border-accent ring-1 ring-accent/20`
- Placeholder: `text-text-muted` (#6b6b78)

### Cards
- Background: `surface-card` (#16161f)
- Border: `border-border-default` (#2a2a3a)
- Padding: `p-4` (16px) minimum
- Border radius: `rounded-lg` (8px) — **change from current `rounded-xl`**
- Shadow: `shadow-sm` (`0 1px 2px rgba(0,0,0,0.2)`)
- Header: title + value right-aligned, separated by `border-b`
- **Migration:** Update `card.tsx` — change `rounded-xl` → `rounded-lg`, `px-6 py-6` → `p-4`

### Tables
All tables must use shadcn `<Table>`, `<TableRow>`, etc. — **migrate raw `<table>` elements.**

- Header: `surface-card` bg, uppercase `text-xxs` labels, `border-b border-border-default`
- Rows: Alternating `surface-base` / `surface-stripe`
- Hover: `surface-hover` transition 150ms
- Cell padding: `px-3 py-2.5` (12px × 10px)
- Numeric columns: `text-right font-mono tabular-nums`
- Symbol columns: `text-left font-sans font-medium`
- P&L values: colored text + pill bg (`bullish-bg` / `bearish-bg`)

### Badges (OI Signals, Moneyness)
- Pattern: `bg-{signal}-bg border border-{signal}-border text-{signal}-text`
- Padding: `px-2 py-0.5`
- Font: `text-xs font-semibold`
- Border radius: `rounded` (4px)

---

## 9. Responsive & Multi-Resolution

### Fluid typography
```css
--text-2xl: clamp(20px, 2vw, 24px);
--text-lg: clamp(16px, 1.5vw, 18px);
```

### Breakpoints
| Name | Width | Behavior |
|------|-------|----------|
| compact | < 1280px | Card padding p-3, hide secondary labels |
| standard | 1280–1920px | Default token values |
| wide | > 1920px | Widget padding p-6, larger charts |

### Density modes
Applied via CSS class on `<html>`:

```css
/* Default = comfortable */
html.density-compact {
  --table-cell-px: 8px;
  --table-cell-py: 6px;
  --card-padding: 12px;
  --input-height: 32px;
  --button-height: 32px;
}

html, html.density-comfortable {
  --table-cell-px: 12px;
  --table-cell-py: 10px;
  --card-padding: 16px;
  --input-height: 36px;
  --button-height: 36px;
}
```

Components read these via `var(--card-padding)` etc. Font sizes stay the same across densities — only spacing changes.

### High-DPI
- All icons: SVG (Lucide) — scale natively
- Logo/wordmark: SVG — infinite resolution
- Charts: Canvas (LWC + Glide) — respect `devicePixelRatio`

---

## 10. Dockview Theme Overrides

Update all Dockview CSS variables in `index.css` to use the new tokens:

```css
--dv-activegroup-visiblepanel-tab-background-color: var(--color-surface-card);
--dv-activegroup-hiddenpanel-tab-background-color: var(--color-surface-base);
--dv-inactivegroup-visiblepanel-tab-background-color: var(--color-surface-card);
--dv-inactivegroup-hiddenpanel-tab-background-color: var(--color-surface-base);
--dv-tab-divider-color: var(--color-border-subtle);
--dv-activegroup-visiblepanel-tab-color: var(--color-text-primary);
--dv-activegroup-hiddenpanel-tab-color: var(--color-text-muted);
--dv-separator-border: var(--color-border-default);
--dv-paneview-header-border-color: var(--color-border-default);
--dv-background-color: var(--color-surface-base);
--dv-group-view-background-color: var(--color-surface-base);
```

---

## 11. Logo & Wordmark Redesign

### Current
- "FT" text in a small image, no SVG, no scalability

### New Design
- **Icon mark:** Geometric "F" + upward spark/flint motif — trading + ignition
- **Wordmark:** "FlintTrade" in Geist 700, `tracking-tight`, capital T
- **Color:** Accent green (#22c55e) for spark, `text-primary` for text
- **Formats:** SVG (primary), PNG fallbacks at 16/32/64/128/256/512px
- **Usage:** Icon alone for favicon/TopBar, full wordmark for Setup/About

### SVG Requirements
- Single `<svg>`, no external references
- Viewbox scaling (no fixed width/height)
- Works on dark (#0a0a0f) and light backgrounds
- Monochrome variant for print

Implementation: `src/components/brand/Logo.tsx` (inline SVG React component)

---

## 12. Implementation Strategy

### Step 1: Install Geist + update `index.css`
- `npm install geist`
- Add `@import 'geist/font/sans.css'`
- Register `--font-heading` in `@theme inline`
- Add `@utility text-xxs`
- Update all surface, border, text color tokens
- Add semantic trading color tokens
- Add density mode CSS rules
- Update Dockview overrides to use tokens
- Update scrollbar colors to use tokens

### Step 2: Update shadcn/ui components
- `button.tsx`: h-9, shadow-sm, hover/active states
- `input.tsx`: h-9, text-sm, placeholder contrast
- `card.tsx`: rounded-lg (from rounded-xl), p-4 (from p-6), shadow-sm
- `table.tsx`: striped rows, hover, right-align numbers
- `badge.tsx`: add bullish/bearish/atm/neutral/itm/otm variants

### Step 3: Global text-size migration
| Find | Replace |
|------|---------|
| `text-[8px]` | `text-xxs` |
| `text-[9px]` | `text-xxs` |
| `text-[10px]` | `text-xs` |
| `text-[11px]` | `text-xs` |
| `text-[12px]` | `text-xs` |
| `text-[13px]` | `text-sm` |
| `text-[14px]` | `text-sm` |

Also:
- Replace `p-2` on widget wrappers → `p-4`
- Replace `h-5` on inputs → `h-9` (or `h-8` compact)
- Migrate raw `<table>` elements to shadcn `<Table>` components

### Step 4: Create Logo component
- Design SVG icon mark + wordmark
- Create `src/components/brand/Logo.tsx`
- Replace current FT image in TopBar

### Step 5: Verify
- `npx tsc --noEmit` — zero errors
- `npx vitest run` — 26/26 pass
- `npm run build` — clean
- `grep -r 'text-\[' src/` — zero matches
- Playwright visual check on all 4 routes

---

## 13. Files Modified

| File | Change |
|------|--------|
| `package.json` | Add `geist` dependency |
| `src/index.css` | Tokens, Dockview overrides, text-xxs, density, scrollbars |
| `src/components/ui/button.tsx` | h-9, shadow, hover/active |
| `src/components/ui/input.tsx` | h-9, text-sm, placeholder |
| `src/components/ui/card.tsx` | rounded-lg, p-4, shadow-sm |
| `src/components/ui/table.tsx` | Striped rows, hover, right-align |
| `src/components/ui/badge.tsx` | Trading signal variants |
| `src/components/brand/Logo.tsx` | NEW — SVG logo component |
| All 21 widgets (~21 files) | Replace arbitrary text sizes, fix padding |
| All 7 tools (~7 files) | Same text/padding fixes |
| All 4 routes (~4 files) | Same text/padding fixes |
| `src/chrome/TopBar.tsx` | Spacing, font-heading, Logo component |
| `src/chrome/TickerBar.tsx` | Spacing, change% pill styling |
| `src/chrome/WidgetPicker.tsx` | Card sizing, search, descriptions |

**Total: ~40 files touched**

---

## 14. Rollback Strategy

Given the blast radius (~40 files), create a checkpoint before starting:

```bash
git stash  # or commit current state
```

Implementation proceeds in sub-commits:
1. Commit: `chore(terminal): install geist font`
2. Commit: `feat(terminal): update design tokens in index.css`
3. Commit: `feat(terminal): update shadcn base components`
4. Commit: `refactor(terminal): replace arbitrary text sizes`
5. Commit: `feat(terminal): add Logo SVG component`
6. Commit: `feat(terminal): update chrome (TopBar, TickerBar, WidgetPicker)`

Each commit must pass tsc + build. If visual regressions appear, revert the specific commit.

---

## 15. Success Criteria

- Zero `text-[Npx]` arbitrary font sizes in codebase (`grep -r 'text-\[' src/` = 0)
- All tables: striped rows + hover highlights + right-aligned numbers
- All numeric columns: `font-mono tabular-nums`
- Card backgrounds (#16161f) visibly distinct from page (#0a0a0f)
- Borders (#2a2a3a) visible on all cards/sections
- Buttons: shadow + clear hover/active feedback
- Inputs: minimum 36px height (h-9)
- P&L values: colored pill backgrounds
- WCAG AA contrast: 4.5:1 minimum for all small text
- Geist font loads and renders for headings
- SVG logo renders in TopBar at all sizes
- tsc clean, vitest 26/26, build clean
- Density toggle in Settings switches compact/comfortable correctly
