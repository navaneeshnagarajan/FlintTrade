export const layerClassNames = {
  appChrome: "z-40",
  overlayBackdrop: "z-[110]",
  floatingPanel: "z-[120]",
  modal: "z-[130]",
  toast: "z-[140]",
} as const;

export type LayerClassName = keyof typeof layerClassNames;
