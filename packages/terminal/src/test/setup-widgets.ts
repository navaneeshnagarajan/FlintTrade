/**
 * setup-widgets.ts
 *
 * Shared test setup for widget/component tests.
 *
 * Problem: shadcn/ui components are built on Radix UI primitives. In JSDOM
 * (CI), Radix renders additional wrapper elements and portal containers that
 * differ from local browser environments. This causes queries like
 * `getByRole('button', { name: 'X' })` to find duplicate matches or fail to
 * find any match at all because Radix injects hidden elements and portals.
 *
 * Solution: Replace every shadcn/ui component with a minimal HTML equivalent
 * for all test files that include this setup. Tests exercise component
 * behaviour and accessibility semantics without Radix runtime overhead.
 *
 * Usage: included via `setupFiles` in vite.config.ts, or imported explicitly
 * in a test file that needs isolated mocking:
 *   import "@/test/setup-widgets";
 */

import { vi } from "vitest";
import React from "react";

// ---------------------------------------------------------------------------
// Type helpers — keep TypeScript strict and avoid `any`
// ---------------------------------------------------------------------------

type ReactChildren = { children?: React.ReactNode };
type WithClassName = { className?: string };
type HTMLProps = React.HTMLAttributes<HTMLElement>;

// ---------------------------------------------------------------------------
// button
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    asChild: _asChild,
    variant: _variant,
    size: _size,
    ...props
  }: ReactChildren & { asChild?: boolean; variant?: string; size?: string } & React.ButtonHTMLAttributes<HTMLButtonElement>) =>
    React.createElement("button", props, children),
}));

// ---------------------------------------------------------------------------
// input
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/input", () => ({
  Input: (props: React.InputHTMLAttributes<HTMLInputElement>) =>
    React.createElement("input", props),
}));

// ---------------------------------------------------------------------------
// textarea
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/textarea", () => ({
  Textarea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) =>
    React.createElement("textarea", props),
}));

// ---------------------------------------------------------------------------
// label
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/label", () => ({
  Label: ({ children, ...props }: ReactChildren & React.LabelHTMLAttributes<HTMLLabelElement>) =>
    React.createElement("label", props, children),
}));

// ---------------------------------------------------------------------------
// badge
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, variant: _variant, ...props }: ReactChildren & { variant?: string } & HTMLProps) =>
    React.createElement("span", props, children),
}));

// ---------------------------------------------------------------------------
// select
// — Radix Select renders a hidden native <select> plus floating content portal
// — Replace with a simple native <select> group
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/select", () => {
  // Internal context to wire SelectValue placeholder and SelectTrigger display
  const SelectContext = React.createContext<{
    value: string;
    onValueChange: (v: string) => void;
  }>({ value: "", onValueChange: () => undefined });

  const Select = ({
    children,
    value = "",
    onValueChange = () => undefined,
    defaultValue: _dv,
    open: _open,
    onOpenChange: _ooc,
  }: ReactChildren & {
    value?: string;
    onValueChange?: (v: string) => void;
    defaultValue?: string;
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
  }) =>
    React.createElement(
      SelectContext.Provider,
      { value: { value, onValueChange } },
      children,
    );

  const SelectTrigger = ({
    children,
    ...props
  }: ReactChildren & HTMLProps) =>
    React.createElement("button", { role: "combobox", ...props }, children);

  const SelectValue = ({
    placeholder,
  }: {
    placeholder?: string;
  }) => {
    const ctx = React.useContext(SelectContext);
    return React.createElement("span", null, ctx.value || placeholder || "");
  };

  const SelectContent = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", { role: "listbox", ...props }, children);

  const SelectItem = ({
    children,
    value,
    ...props
  }: ReactChildren & { value: string } & HTMLProps) => {
    const ctx = React.useContext(SelectContext);
    return React.createElement(
      "div",
      {
        role: "option",
        "data-value": value,
        "aria-selected": ctx.value === value,
        onClick: () => ctx.onValueChange(value),
        ...props,
      },
      children,
    );
  };

  const SelectGroup = ({ children }: ReactChildren) =>
    React.createElement("div", { role: "group" }, children);

  const SelectLabel = ({ children }: ReactChildren) =>
    React.createElement("span", null, children);

  const SelectSeparator = () => React.createElement("hr", null);

  return {
    Select,
    SelectTrigger,
    SelectValue,
    SelectContent,
    SelectItem,
    SelectGroup,
    SelectLabel,
    SelectSeparator,
  };
});

// ---------------------------------------------------------------------------
// switch
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/switch", () => ({
  Switch: ({
    checked,
    onCheckedChange,
    ...props
  }: {
    checked?: boolean;
    onCheckedChange?: (checked: boolean) => void;
  } & React.ButtonHTMLAttributes<HTMLButtonElement>) =>
    React.createElement("button", {
      role: "switch",
      "aria-checked": checked,
      onClick: () => onCheckedChange?.(!checked),
      ...props,
    }),
}));

// ---------------------------------------------------------------------------
// dialog
// — Radix Dialog uses portals. Replace with a minimal conditional wrapper.
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/dialog", () => {
  const Dialog = ({
    children,
    open,
    onOpenChange: _ooc,
  }: ReactChildren & { open?: boolean; onOpenChange?: (open: boolean) => void }) =>
    open ? React.createElement(React.Fragment, null, children) : null;

  const DialogTrigger = ({ children, asChild: _asChild, ...props }: ReactChildren & { asChild?: boolean } & HTMLProps) =>
    React.createElement("div", props, children);

  const DialogContent = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", { role: "dialog", ...props }, children);

  const DialogHeader = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children);

  const DialogFooter = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children);

  const DialogTitle = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("h2", props, children);

  const DialogDescription = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("p", props, children);

  const DialogClose = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("button", props, children);

  return {
    Dialog,
    DialogTrigger,
    DialogContent,
    DialogHeader,
    DialogFooter,
    DialogTitle,
    DialogDescription,
    DialogClose,
  };
});

// ---------------------------------------------------------------------------
// alert-dialog
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/alert-dialog", () => {
  const AlertDialog = ({
    children,
    open,
    onOpenChange: _ooc,
  }: ReactChildren & { open?: boolean; onOpenChange?: (open: boolean) => void }) =>
    open ? React.createElement(React.Fragment, null, children) : null;

  const AlertDialogTrigger = ({ children, asChild: _asChild, ...props }: ReactChildren & { asChild?: boolean } & HTMLProps) =>
    React.createElement("div", props, children);

  const AlertDialogContent = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", { role: "alertdialog", ...props }, children);

  const AlertDialogHeader = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children);

  const AlertDialogFooter = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children);

  const AlertDialogTitle = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("h2", props, children);

  const AlertDialogDescription = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("p", props, children);

  const AlertDialogAction = ({ children, ...props }: ReactChildren & React.ButtonHTMLAttributes<HTMLButtonElement>) =>
    React.createElement("button", props, children);

  const AlertDialogCancel = ({ children, ...props }: ReactChildren & React.ButtonHTMLAttributes<HTMLButtonElement>) =>
    React.createElement("button", props, children);

  return {
    AlertDialog,
    AlertDialogTrigger,
    AlertDialogContent,
    AlertDialogHeader,
    AlertDialogFooter,
    AlertDialogTitle,
    AlertDialogDescription,
    AlertDialogAction,
    AlertDialogCancel,
  };
});

// ---------------------------------------------------------------------------
// tooltip
// — Radix Tooltip portals content. Render inline so tests can query it.
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/tooltip", () => {
  const TooltipProvider = ({ children }: ReactChildren) =>
    React.createElement(React.Fragment, null, children);

  const Tooltip = ({
    children,
    open: _open,
    onOpenChange: _ooc,
    defaultOpen: _do,
    delayDuration: _dd,
  }: ReactChildren & {
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
    defaultOpen?: boolean;
    delayDuration?: number;
  }) => React.createElement(React.Fragment, null, children);

  const TooltipTrigger = ({
    children,
    asChild: _asChild,
    ...props
  }: ReactChildren & { asChild?: boolean } & HTMLProps) =>
    React.createElement("div", props, children);

  const TooltipContent = ({ children, side: _side, ...props }: ReactChildren & { side?: string } & HTMLProps) =>
    React.createElement("div", { role: "tooltip", ...props }, children);

  return { TooltipProvider, Tooltip, TooltipTrigger, TooltipContent };
});

// ---------------------------------------------------------------------------
// popover
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/popover", () => {
  const Popover = ({
    children,
    open: _open,
    onOpenChange: _ooc,
  }: ReactChildren & { open?: boolean; onOpenChange?: (open: boolean) => void }) =>
    React.createElement(React.Fragment, null, children);

  const PopoverTrigger = ({
    children,
    asChild: _asChild,
    ...props
  }: ReactChildren & { asChild?: boolean } & HTMLProps) =>
    React.createElement("button", props, children);

  const PopoverContent = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children);

  return { Popover, PopoverTrigger, PopoverContent };
});

// ---------------------------------------------------------------------------
// dropdown-menu
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/dropdown-menu", () => {
  const DropdownMenu = ({
    children,
    open: _open,
    onOpenChange: _ooc,
  }: ReactChildren & { open?: boolean; onOpenChange?: (open: boolean) => void }) =>
    React.createElement(React.Fragment, null, children);

  const DropdownMenuTrigger = ({
    children,
    asChild: _asChild,
    ...props
  }: ReactChildren & { asChild?: boolean } & HTMLProps) =>
    React.createElement("button", { "aria-haspopup": "menu", ...props }, children);

  const DropdownMenuContent = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", { role: "menu", ...props }, children);

  const DropdownMenuItem = ({ children, onSelect, ...props }: ReactChildren & { onSelect?: () => void } & HTMLProps) =>
    React.createElement(
      "div",
      { role: "menuitem", onClick: onSelect, ...props },
      children,
    );

  const DropdownMenuLabel = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children);

  const DropdownMenuSeparator = (props: HTMLProps) =>
    React.createElement("hr", props);

  const DropdownMenuGroup = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", { role: "group", ...props }, children);

  const DropdownMenuCheckboxItem = ({
    children,
    checked,
    onCheckedChange,
    ...props
  }: ReactChildren & { checked?: boolean; onCheckedChange?: (checked: boolean) => void } & HTMLProps) =>
    React.createElement(
      "div",
      {
        role: "menuitemcheckbox",
        "aria-checked": checked,
        onClick: () => onCheckedChange?.(!checked),
        ...props,
      },
      children,
    );

  const DropdownMenuRadioGroup = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", { role: "radiogroup", ...props }, children);

  const DropdownMenuRadioItem = ({
    children,
    value: _value,
    ...props
  }: ReactChildren & { value?: string } & HTMLProps) =>
    React.createElement("div", { role: "menuitemradio", ...props }, children);

  const DropdownMenuSub = ({ children }: ReactChildren) =>
    React.createElement(React.Fragment, null, children);

  const DropdownMenuSubTrigger = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", { role: "menuitem", ...props }, children);

  const DropdownMenuSubContent = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", { role: "menu", ...props }, children);

  const DropdownMenuShortcut = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("span", props, children);

  return {
    DropdownMenu,
    DropdownMenuTrigger,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuGroup,
    DropdownMenuCheckboxItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSub,
    DropdownMenuSubTrigger,
    DropdownMenuSubContent,
    DropdownMenuShortcut,
  };
});

// ---------------------------------------------------------------------------
// tabs
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/tabs", () => {
  const TabsContext = React.createContext<{
    value: string;
    onValueChange: (v: string) => void;
  }>({ value: "", onValueChange: () => undefined });

  const Tabs = ({
    children,
    value = "",
    onValueChange = () => undefined,
    defaultValue: _dv,
    ...props
  }: ReactChildren & {
    value?: string;
    onValueChange?: (v: string) => void;
    defaultValue?: string;
  } & HTMLProps) =>
    React.createElement(
      TabsContext.Provider,
      { value: { value, onValueChange } },
      React.createElement("div", props, children),
    );

  const TabsList = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", { role: "tablist", ...props }, children);

  const TabsTrigger = ({
    children,
    value,
    ...props
  }: ReactChildren & { value: string } & React.ButtonHTMLAttributes<HTMLButtonElement>) => {
    const ctx = React.useContext(TabsContext);
    return React.createElement(
      "button",
      {
        role: "tab",
        "aria-selected": ctx.value === value,
        onClick: () => ctx.onValueChange(value),
        ...props,
      },
      children,
    );
  };

  const TabsContent = ({
    children,
    value,
    ...props
  }: ReactChildren & { value: string } & HTMLProps) => {
    const ctx = React.useContext(TabsContext);
    return ctx.value === value
      ? React.createElement("div", { role: "tabpanel", ...props }, children)
      : null;
  };

  return { Tabs, TabsList, TabsTrigger, TabsContent };
});

// ---------------------------------------------------------------------------
// card
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/card", () => ({
  Card: ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children),
  CardHeader: ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children),
  CardTitle: ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("h3", props, children),
  CardDescription: ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("p", props, children),
  CardContent: ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children),
  CardFooter: ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children),
}));

// ---------------------------------------------------------------------------
// scroll-area
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children),
  ScrollBar: (props: HTMLProps & WithClassName) =>
    React.createElement("div", props),
}));

// ---------------------------------------------------------------------------
// separator
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/separator", () => ({
  Separator: (props: HTMLProps & { orientation?: string; decorative?: boolean }) =>
    React.createElement("hr", { role: props.decorative ? "none" : "separator", ...props }),
}));

// ---------------------------------------------------------------------------
// skeleton
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/skeleton", () => ({
  Skeleton: ({ className, ...props }: WithClassName & HTMLProps) =>
    React.createElement("div", {
      "aria-hidden": "true",
      "data-testid": "skeleton",
      className,
      ...props,
    }),
}));

// ---------------------------------------------------------------------------
// sheet
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/sheet", () => {
  const Sheet = ({
    children,
    open,
    onOpenChange: _ooc,
  }: ReactChildren & { open?: boolean; onOpenChange?: (open: boolean) => void }) =>
    open ? React.createElement(React.Fragment, null, children) : null;

  const SheetTrigger = ({ children, asChild: _asChild, ...props }: ReactChildren & { asChild?: boolean } & HTMLProps) =>
    React.createElement("button", props, children);

  const SheetContent = ({ children, side: _side, ...props }: ReactChildren & { side?: string } & HTMLProps) =>
    React.createElement("div", { role: "dialog", ...props }, children);

  const SheetHeader = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children);

  const SheetFooter = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children);

  const SheetTitle = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("h2", props, children);

  const SheetDescription = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("p", props, children);

  const SheetClose = ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("button", props, children);

  return {
    Sheet,
    SheetTrigger,
    SheetContent,
    SheetHeader,
    SheetFooter,
    SheetTitle,
    SheetDescription,
    SheetClose,
  };
});

// ---------------------------------------------------------------------------
// command
// — cmdk Command renders a full-featured combobox. Replace with a simple div.
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/command", () => ({
  Command: ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", { role: "combobox", ...props }, children),
  CommandInput: (props: React.InputHTMLAttributes<HTMLInputElement>) =>
    React.createElement("input", props),
  CommandList: ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", { role: "listbox", ...props }, children),
  CommandEmpty: ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children),
  CommandGroup: ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", { role: "group", ...props }, children),
  CommandItem: ({
    children,
    onSelect,
    ...props
  }: ReactChildren & { onSelect?: () => void } & HTMLProps) =>
    React.createElement(
      "div",
      { role: "option", onClick: onSelect, ...props },
      children,
    ),
  CommandSeparator: (props: HTMLProps) =>
    React.createElement("hr", props),
  CommandShortcut: ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("span", props, children),
}));

// ---------------------------------------------------------------------------
// Custom FlintTrade UI helpers (not shadcn, but often mocked alongside)
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/GlassCard", () => ({
  GlassCard: ({ children, ...props }: ReactChildren & HTMLProps) =>
    React.createElement("div", props, children),
}));

vi.mock("@/components/ui/GlossaryTooltip", () => ({
  GlossaryTooltip: ({ children }: ReactChildren) =>
    React.createElement(React.Fragment, null, children),
}));

vi.mock("@/components/ui/DemoBanner", () => ({
  DemoBanner: () => null,
}));
