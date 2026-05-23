export interface Props {
  onClose?: () => void;
}

/** Discriminated union for tilt detection state. */
export type TiltStatus =
  | { level: "calm"; reason: null }
  | { level: "warning"; reason: string }
  | { level: "tilted"; reason: string };
