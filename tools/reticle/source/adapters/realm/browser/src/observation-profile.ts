/** Opt-in observation capacity; never an application assertion/request budget. */
export interface ObservationProfile {
  /** Semantic events per mutation batch, independently for additions/removals/changes. */
  domMaxPerBatch: number;
}

/** Omission retains the published behaviour. Reject mistakes, never clamp or coerce. */
export function observationProfile(value: unknown): Readonly<ObservationProfile> | undefined {
  if (value === undefined) return undefined;
  if (value === null || typeof value !== 'object' || Array.isArray(value) ||
      ![Object.prototype, null].includes(Object.getPrototypeOf(value) as object | null) ||
      Reflect.ownKeys(value).length !== 1 || !Object.hasOwn(value, 'domMaxPerBatch')) {
    throw new Error('invalid observationProfile');
  }
  const count = (value as Record<string, unknown>)['domMaxPerBatch'];
  if (typeof count !== 'number' || !Number.isSafeInteger(count) || count < 1 || count > 512) {
    throw new Error('observationProfile.domMaxPerBatch must be an integer in 1..512');
  }
  return Object.freeze({ domMaxPerBatch: count });
}
