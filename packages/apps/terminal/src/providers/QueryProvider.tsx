import {
  MutationCache,
  MutationObserver,
  QueryClient,
  QueryClientProvider,
  type MutationCacheNotifyEvent,
  type MutationOptions,
  type MutationState,
  type MutateOptions,
} from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useSyncExternalStore, type ReactNode } from "react";
import { registerAuthenticatedQueryCachePurge } from "@/lib/authenticatedQueryCache";
import {
  captureAuthSessionFence,
  isAuthSessionFenceCurrent,
  type AuthSessionFence,
} from "@/stores/authStore";

const mutationOptionFences = new WeakMap<object, AuthSessionFence>();
const RETIRED_MUTATION_MESSAGE =
  "Mutation retired because its authentication session changed";

function assertAuthSessionFenceCurrent(fence: AuthSessionFence): void {
  if (!isAuthSessionFenceCurrent(fence)) {
    throw new Error(RETIRED_MUTATION_MESSAGE);
  }
}

async function runAuthFencedLifecycle<T>(
  fence: AuthSessionFence,
  callback: () => T | Promise<T>,
): Promise<Awaited<T> | undefined> {
  if (!isAuthSessionFenceCurrent(fence)) return undefined;
  try {
    const result = await callback();
    return isAuthSessionFenceCurrent(fence) ? result : undefined;
  } catch (error) {
    if (isAuthSessionFenceCurrent(fence)) throw error;
    return undefined;
  }
}

function withAuthSessionFence<TData, TError, TVariables, TOnMutateResult>(
  options: MutationOptions<TData, TError, TVariables, TOnMutateResult>,
  fence: AuthSessionFence,
): MutationOptions<TData, TError, TVariables, TOnMutateResult> {
  const existingFence = mutationOptionFences.get(options);
  if (
    existingFence?.status === fence.status &&
    existingFence?.principal === fence.principal &&
    existingFence.generation === fence.generation
  ) {
    return options;
  }

  const { mutationFn, onMutate, onSuccess, onError, onSettled } = options;
  // TanStack reuses this observer-owned object for pending mutations. Keep the
  // wrappers on it so a hook re-render cannot restore unfenced callbacks.
  const fencedOptions = options;
  fencedOptions.onMutate = async (variables, context) => {
    assertAuthSessionFenceCurrent(fence);
    const result = onMutate ? await onMutate(variables, context) : undefined;
    assertAuthSessionFenceCurrent(fence);
    return result as TOnMutateResult;
  };
  if (mutationFn) {
    fencedOptions.mutationFn = (variables, context) => {
      assertAuthSessionFenceCurrent(fence);
      return mutationFn(variables, context);
    };
  }
  if (onSuccess) {
    fencedOptions.onSuccess = (data, variables, onMutateResult, context) =>
      runAuthFencedLifecycle(fence, () =>
        onSuccess(data, variables, onMutateResult, context),
      );
  }
  if (onError) {
    fencedOptions.onError = (error, variables, onMutateResult, context) =>
      runAuthFencedLifecycle(fence, () =>
        onError(error, variables, onMutateResult, context),
      );
  }
  if (onSettled) {
    fencedOptions.onSettled = (
      data,
      error,
      variables,
      onMutateResult,
      context,
    ) =>
      runAuthFencedLifecycle(fence, () =>
        onSettled(data, error, variables, onMutateResult, context),
      );
  }
  mutationOptionFences.set(fencedOptions, fence);
  return fencedOptions;
}

function fencePerCallMutationOptions<
  TData,
  TError,
  TVariables,
  TOnMutateResult,
>(
  options: MutateOptions<TData, TError, TVariables, TOnMutateResult>,
  fence: AuthSessionFence,
): MutateOptions<TData, TError, TVariables, TOnMutateResult> {
  const { onSuccess, onError, onSettled } = options;
  return {
    ...options,
    onSuccess: onSuccess
      ? (data, variables, onMutateResult, context) =>
          runAuthFencedLifecycle(fence, () =>
            onSuccess(data, variables, onMutateResult, context),
          )
      : undefined,
    onError: onError
      ? (error, variables, onMutateResult, context) =>
          runAuthFencedLifecycle(fence, () =>
            onError(error, variables, onMutateResult, context),
          )
      : undefined,
    onSettled: onSettled
      ? (data, error, variables, onMutateResult, context) =>
          runAuthFencedLifecycle(fence, () =>
            onSettled(data, error, variables, onMutateResult, context),
          )
      : undefined,
  };
}

const AUTH_FENCED_MUTATE_ORIGINAL = Symbol.for(
  "flinttrade.auth-fenced-mutation-observer",
);
type AnyMutationObserver = MutationObserver<unknown, unknown, unknown, unknown>;
type AuthFencedMutationObserverPrototype = AnyMutationObserver & {
  [AUTH_FENCED_MUTATE_ORIGINAL]?: AnyMutationObserver["mutate"];
};

function installPerCallMutationFence(): void {
  const prototype =
    MutationObserver.prototype as AuthFencedMutationObserverPrototype;
  if (prototype[AUTH_FENCED_MUTATE_ORIGINAL]) return;

  // TanStack stores mutate(..., callbacks) in private observer state, outside
  // MutationCache. Fence the public entry point once so those callbacks carry
  // the same originating auth context as hook-level mutation callbacks.
  const originalMutate = prototype.mutate;
  Object.defineProperty(prototype, AUTH_FENCED_MUTATE_ORIGINAL, {
    configurable: false,
    enumerable: false,
    value: originalMutate,
    writable: false,
  });
  prototype.mutate = function (
    variables: unknown,
    options?: MutateOptions<unknown, unknown, unknown, unknown>,
  ): Promise<unknown> {
    const fence = captureAuthSessionFence();
    return originalMutate.call(
      this,
      variables,
      options ? fencePerCallMutationOptions(options, fence) : options,
    );
  };
}

installPerCallMutationFence();

class AuthFencedMutationCache extends MutationCache {
  private readonly mutationFences = new WeakMap<object, AuthSessionFence>();

  override build<TData, TError, TVariables, TOnMutateResult>(
    client: QueryClient,
    options: MutationOptions<TData, TError, TVariables, TOnMutateResult>,
    state?: MutationState<TData, TError, TVariables, TOnMutateResult>,
  ) {
    const defaultedOptions = client.defaultMutationOptions(options);
    const fence = captureAuthSessionFence();
    const mutation = super.build(
      client,
      withAuthSessionFence(defaultedOptions, fence),
      state,
    );
    this.mutationFences.set(mutation, fence);
    return mutation;
  }

  override notify(event: MutationCacheNotifyEvent): void {
    if (event.type === "observerOptionsUpdated" && event.mutation) {
      const fence = this.mutationFences.get(event.mutation);
      if (fence) {
        event.observer.options = withAuthSessionFence(
          event.observer.options,
          fence,
        );
      }
    }
    super.notify(event);
  }
}

function createQueryClient(): QueryClient {
  return new QueryClient({
    mutationCache: new AuthFencedMutationCache(),
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        gcTime: 300_000,
        retry: 2,
        refetchOnWindowFocus: false,
      },
    },
  });
}

export let queryClient = createQueryClient();
let queryClientEpoch = 0;
let queryClientState = { client: queryClient, epoch: queryClientEpoch };
const queryClientSubscribers = new Set<() => void>();

function subscribeToQueryClient(listener: () => void): () => void {
  queryClientSubscribers.add(listener);
  return () => queryClientSubscribers.delete(listener);
}

function activeQueryClientState(): typeof queryClientState {
  return queryClientState;
}

registerAuthenticatedQueryCachePurge(() => {
  const retiredClient = queryClient;
  queryClient = createQueryClient();
  queryClientEpoch += 1;
  queryClientState = { client: queryClient, epoch: queryClientEpoch };
  retiredClient.clear();
  queryClientSubscribers.forEach((listener) => listener());
});

interface Props {
  children: ReactNode;
}

export function QueryProvider({ children }: Props) {
  const activeState = useSyncExternalStore(
    subscribeToQueryClient,
    activeQueryClientState,
    activeQueryClientState,
  );
  return (
    <QueryClientProvider key={activeState.epoch} client={activeState.client}>
      {children}
      {/* TanStack Query Devtools — enable via console: localStorage.setItem("flinttrade:devtools", "1") then reload */}
      {import.meta.env.DEV &&
        localStorage.getItem("flinttrade:devtools") === "1" && (
          <ReactQueryDevtools initialIsOpen={false} />
        )}
    </QueryClientProvider>
  );
}
