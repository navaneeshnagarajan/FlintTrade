/**
 * Vitest 5 reads custom matchers from Matchers<R, T> (return type first,
 * then received type). @testing-library/jest-dom@7 still augments the
 * Vitest 4 Assertion<T> slot, so tsc drops toBeInTheDocument and friends.
 * Re-declare the DOM matchers on the Vitest 5 interface.
 */
import type { TestingLibraryMatchers } from "@testing-library/jest-dom/matchers";
import "vitest";

declare module "vitest" {
  interface Matchers<R, T> extends TestingLibraryMatchers<unknown, R> {}
}
