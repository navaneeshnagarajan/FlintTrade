import { createContext, useContext, useState, type PropsWithChildren, type RefCallback } from "react";

const HelpFooterTarget = createContext<HTMLElement | null>(null);
const HelpFooterRegistration = createContext<RefCallback<HTMLSpanElement> | undefined>(undefined);

/** The root keeps companion state while mounted app chrome supplies its slot. */
export function HelpFooterProvider({ children }: PropsWithChildren) {
  const [target, setTarget] = useState<HTMLSpanElement | null>(null);
  return <HelpFooterRegistration.Provider value={setTarget}>
    <HelpFooterTarget.Provider value={target}>{children}</HelpFooterTarget.Provider>
  </HelpFooterRegistration.Provider>;
}

export function HelpFooterSlot() {
  const register = useContext(HelpFooterRegistration);
  return <span ref={register} className="flex shrink-0 items-center empty:hidden" />;
}

export function useHelpFooter() {
  return useContext(HelpFooterTarget);
}
