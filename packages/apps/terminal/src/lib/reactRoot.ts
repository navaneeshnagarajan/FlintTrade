import type { ReactNode } from "react";
import { createRoot as createReactRoot } from "react-dom/client";
import type { Root } from "react-dom/client";

type RenderRoot = Pick<Root, "render">;
type CreateRoot = (container: Element | DocumentFragment) => RenderRoot;

const roots = new WeakMap<Element | DocumentFragment, RenderRoot>();

export function renderReactRoot(
  container: Element | DocumentFragment,
  element: ReactNode,
  createRoot: CreateRoot = createReactRoot,
): RenderRoot {
  let root = roots.get(container);
  if (!root) {
    root = createRoot(container);
    roots.set(container, root);
  }

  root.render(element);
  return root;
}
