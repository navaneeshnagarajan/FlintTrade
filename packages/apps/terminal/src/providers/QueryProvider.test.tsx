import {
  useMutation,
  useQuery,
  useQueryClient,
  type MutateOptions,
  type QueryClient,
} from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { QueryProvider, queryClient } from "./QueryProvider";

interface ProbeState {
  client: QueryClient;
  refetch: () => Promise<unknown>;
  mutate: (value: string) => Promise<string>;
}

function QueryObserverProbe({
  onReady,
}: {
  onReady: (state: ProbeState) => void;
}) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["auth-epoch-probe"],
    queryFn: async () => "query-result",
  });
  const mutation = useMutation({
    mutationFn: async (value: string) => value,
  });

  useEffect(() => {
    onReady({
      client,
      refetch: query.refetch,
      mutate: mutation.mutateAsync,
    });
  }, [client, mutation.mutateAsync, onReady, query.refetch]);

  return null;
}

function MutationCallbackProbe({
  mutationFn,
  onReady,
  onSuccess,
}: {
  mutationFn: () => Promise<string>;
  onReady: (
    mutate: (
      options?: MutateOptions<string, Error, void, unknown>,
    ) => Promise<string>,
  ) => void;
  onSuccess: (value: string) => void;
}) {
  const mutation = useMutation({ mutationFn, onSuccess });
  const { mutateAsync } = mutation;

  useEffect(() => {
    onReady((options) => mutateAsync(undefined, options));
  }, [mutateAsync, onReady]);

  return <span data-testid="mutation-status">{mutation.status}</span>;
}

describe("QueryProvider auth cache boundaries", () => {
  const authRetirements = [
    ["logout", () => useAuthStore.getState().setLoggedOut()],
    ["principal replacement", () => useAuthStore.setState({ username: "bob" })],
    [
      "generation change",
      () =>
        useAuthStore.setState((state) => ({
          sessionGeneration: state.sessionGeneration + 1,
        })),
    ],
  ] as const;

  beforeEach(() => {
    useAuthStore.setState({
      status: "unknown",
      token: null,
      reauthToken: null,
      username: null,
      expiresAt: null,
      sessionGeneration: 0,
      _expiryTimerId: null,
    });
    queryClient.clear();
  });

  afterEach(() => {
    const timerId = useAuthStore.getState()._expiryTimerId;
    if (timerId !== null) clearTimeout(timerId);
    cleanup();
  });

  it("rebinds mounted query and mutation observers after consecutive auth transitions", async () => {
    let activeProbe: ProbeState | null = null;
    const onReady = (state: ProbeState) => {
      activeProbe = state;
    };

    render(
      <QueryProvider>
        <QueryObserverProbe onReady={onReady} />
      </QueryProvider>,
    );
    const firstClient = queryClient;
    await waitFor(() => {
      expect(activeProbe?.client).toBe(firstClient);
      expect(firstClient.getQueryData(["auth-epoch-probe"])).toBe(
        "query-result",
      );
    });

    act(() => useAuthStore.getState().setLoggedIn("token", "alice", ""));
    const secondClient = queryClient;
    expect(secondClient).not.toBe(firstClient);
    await waitFor(() => {
      expect(activeProbe?.client).toBe(secondClient);
      expect(secondClient.getQueryData(["auth-epoch-probe"])).toBe(
        "query-result",
      );
    });
    expect(firstClient.getQueryCache().getAll()).toHaveLength(0);

    act(() => useAuthStore.getState().setPinRequired());
    const thirdClient = queryClient;
    expect(thirdClient).not.toBe(secondClient);
    await waitFor(() => {
      expect(activeProbe?.client).toBe(thirdClient);
      expect(thirdClient.getQueryData(["auth-epoch-probe"])).toBe(
        "query-result",
      );
    });

    await act(async () => {
      await activeProbe?.refetch();
      await activeProbe?.mutate("current-session");
    });

    expect(thirdClient.getQueryData(["auth-epoch-probe"])).toBe("query-result");
    expect(thirdClient.getMutationCache().getAll()).toHaveLength(1);
    expect(firstClient.getQueryCache().getAll()).toHaveLength(0);
    expect(firstClient.getMutationCache().getAll()).toHaveLength(0);
    expect(secondClient.getQueryCache().getAll()).toHaveLength(0);
    expect(secondClient.getMutationCache().getAll()).toHaveLength(0);
  });

  it("runs external mutation callbacks while the authenticated session is current", async () => {
    act(() => useAuthStore.getState().setLoggedIn("token", "alice", ""));
    const onSuccess = vi.fn();
    const onSettled = vi.fn();
    const mutation = queryClient
      .getMutationCache()
      .build<string, Error, string, unknown>(queryClient, {
        mutationFn: async (value) => value,
        onSuccess,
        onSettled,
      });

    await mutation.execute("same-session");

    expect(onSuccess).toHaveBeenCalledOnce();
    expect(onSettled).toHaveBeenCalledOnce();
  });

  it("does not invoke onMutate or mutationFn after the originating fence is already retired", async () => {
    act(() => useAuthStore.getState().setLoggedIn("token-1", "alice", ""));
    const onMutate = vi.fn();
    const mutationFn = vi.fn(async () => "should-not-run");
    const mutation = queryClient
      .getMutationCache()
      .build<string, Error, void, unknown>(queryClient, {
        mutationFn,
        onMutate,
      });
    act(() =>
      useAuthStore.setState((state) => ({
        sessionGeneration: state.sessionGeneration + 1,
      })),
    );

    await expect(mutation.execute(undefined)).rejects.toThrow(
      "Mutation retired because its authentication session changed",
    );

    expect(onMutate).not.toHaveBeenCalled();
    expect(mutationFn).not.toHaveBeenCalled();
  });

  it.each(authRetirements)(
    "does not start mutationFn when %s occurs during asynchronous onMutate",
    async (_label, retireAuth) => {
      act(() => useAuthStore.getState().setLoggedIn("token-1", "alice", ""));
      let finishOnMutate: ((value: { snapshot: string }) => void) | undefined;
      const onMutate = vi.fn(
        () =>
          new Promise<{ snapshot: string }>((resolve) => {
            finishOnMutate = resolve;
          }),
      );
      const mutationFn = vi.fn(async () => "should-not-run");
      const onError = vi.fn();
      const onSettled = vi.fn();
      const originatingClient = queryClient;
      const mutation = originatingClient
        .getMutationCache()
        .build<string, Error, void, { snapshot: string }>(originatingClient, {
          mutationFn,
          onMutate,
          onError,
          onSettled,
        });
      const completion = mutation
        .execute(undefined)
        .catch((error: unknown) => error);
      await waitFor(() => expect(onMutate).toHaveBeenCalledOnce());

      act(() => retireAuth());
      finishOnMutate?.({ snapshot: "retired" });
      const failure = await completion;

      expect(failure).toBeInstanceOf(Error);
      expect((failure as Error).message).toBe(
        "Mutation retired because its authentication session changed",
      );
      expect(mutationFn).not.toHaveBeenCalled();
      expect(onError).not.toHaveBeenCalled();
      expect(onSettled).not.toHaveBeenCalled();
    },
  );

  it.each(authRetirements)(
    "suppresses downstream publication when %s occurs during asynchronous onSuccess",
    async (_label, retireAuth) => {
      act(() => useAuthStore.getState().setLoggedIn("token-1", "alice", ""));
      let finishSuccess: (() => void) | undefined;
      const successStarted = vi.fn();
      const publishUi = vi.fn();
      const originatingClient = queryClient;
      const mutation = originatingClient
        .getMutationCache()
        .build<string, Error, void, unknown>(originatingClient, {
          mutationFn: async () => "retired-result",
          onSuccess: async () => {
            successStarted();
            await new Promise<void>((resolve) => {
              finishSuccess = resolve;
            });
          },
          onSettled: () => {
            publishUi();
            queryClient.setQueryData(["retired-publication"], true);
          },
        });
      const completion = mutation.execute(undefined);
      await waitFor(() => expect(successStarted).toHaveBeenCalledOnce());

      act(() => retireAuth());
      finishSuccess?.();
      await completion;

      expect(publishUi).not.toHaveBeenCalled();
      expect(queryClient.getQueryData(["retired-publication"])).toBeUndefined();
    },
  );

  it("suppresses downstream publication after auth changes during asynchronous onError", async () => {
    act(() => useAuthStore.getState().setLoggedIn("token-1", "alice", ""));
    let finishError: (() => void) | undefined;
    const errorStarted = vi.fn();
    const publishUi = vi.fn();
    const originatingClient = queryClient;
    const mutation = originatingClient
      .getMutationCache()
      .build<string, Error, void, unknown>(originatingClient, {
        mutationFn: async () => {
          throw new Error("original mutation failure");
        },
        onError: async () => {
          errorStarted();
          await new Promise<void>((resolve) => {
            finishError = resolve;
          });
        },
        onSettled: publishUi,
      });
    const completion = mutation
      .execute(undefined)
      .catch((error: unknown) => error);
    await waitFor(() => expect(errorStarted).toHaveBeenCalledOnce());

    act(() =>
      useAuthStore.setState((state) => ({
        sessionGeneration: state.sessionGeneration + 1,
      })),
    );
    finishError?.();
    const failure = await completion;

    expect(failure).toBeInstanceOf(Error);
    expect((failure as Error).message).toBe("original mutation failure");
    expect(publishUi).not.toHaveBeenCalled();
  });

  it("swallows a retired asynchronous onSettled failure instead of publishing error state", async () => {
    act(() => useAuthStore.getState().setLoggedIn("token-1", "alice", ""));
    let finishSettled: (() => void) | undefined;
    const settledStarted = vi.fn();
    const originatingClient = queryClient;
    const mutation = originatingClient
      .getMutationCache()
      .build<string, Error, void, unknown>(originatingClient, {
        mutationFn: async () => "successful-result",
        onSettled: async () => {
          settledStarted();
          await new Promise<void>((resolve) => {
            finishSettled = resolve;
          });
          throw new Error("retired settled failure");
        },
      });
    const completion = mutation.execute(undefined);
    await waitFor(() => expect(settledStarted).toHaveBeenCalledOnce());

    act(() =>
      useAuthStore.setState((state) => ({
        sessionGeneration: state.sessionGeneration + 1,
      })),
    );
    finishSettled?.();

    await expect(completion).resolves.toBe("successful-result");
  });

  it.each([
    ["unknown", null],
    ["logged-out", null],
    ["pin-required", "alice"],
    ["setup-required", null],
    ["transitioning", "alice"],
  ] as const)(
    "suppresses callbacks from a retired %s auth context",
    async (status, username) => {
      act(() =>
        useAuthStore.setState({ status, username, sessionGeneration: 12 }),
      );
      const onSuccess = vi.fn();
      const onSettled = vi.fn();
      let finishMutation: ((value: string) => void) | undefined;
      const mutation = queryClient
        .getMutationCache()
        .build<string, Error, void, unknown>(queryClient, {
          mutationFn: () =>
            new Promise<string>((resolve) => {
              finishMutation = resolve;
            }),
          onSuccess,
          onSettled,
        });
      const completion = mutation.execute(undefined);
      await Promise.resolve();

      act(() => useAuthStore.setState({ sessionGeneration: 13 }));
      finishMutation?.("retired-result");
      await completion;

      expect(onSuccess).not.toHaveBeenCalled();
      expect(onSettled).not.toHaveBeenCalled();
    },
  );

  it("suppresses external success callbacks after the authenticated identity changes", async () => {
    act(() => useAuthStore.getState().setLoggedIn("token-1", "alice", ""));
    const retiredClient = queryClient;
    const onSuccess = vi.fn();
    const onSettled = vi.fn();
    let finishMutation: ((value: string) => void) | undefined;
    const mutation = retiredClient
      .getMutationCache()
      .build<string, Error, void, unknown>(retiredClient, {
        mutationFn: () =>
          new Promise<string>((resolve) => {
            finishMutation = resolve;
          }),
        onSuccess,
        onSettled,
      });
    const completion = mutation.execute(undefined);
    await Promise.resolve();

    act(() => useAuthStore.getState().setLoggedIn("token-2", "bob", ""));
    finishMutation?.("alice-result");
    await completion;

    expect(onSuccess).not.toHaveBeenCalled();
    expect(onSettled).not.toHaveBeenCalled();
  });

  it("keeps hook-level callbacks fenced after a pending mutation re-renders", async () => {
    act(() => useAuthStore.getState().setLoggedIn("token-1", "alice", ""));
    const onSuccess = vi.fn();
    let finishMutation: ((value: string) => void) | undefined;
    let mutate: (() => Promise<string>) | undefined;
    render(
      <QueryProvider>
        <MutationCallbackProbe
          mutationFn={() =>
            new Promise<string>((resolve) => {
              finishMutation = resolve;
            })
          }
          onReady={(nextMutate) => {
            mutate = nextMutate;
          }}
          onSuccess={onSuccess}
        />
      </QueryProvider>,
    );
    await waitFor(() => expect(mutate).toBeTypeOf("function"));

    let completion: Promise<string> | undefined;
    act(() => {
      completion = mutate?.();
    });
    await waitFor(() =>
      expect(screen.getByTestId("mutation-status")).toHaveTextContent(
        "pending",
      ),
    );
    const pendingMutation = queryClient.getMutationCache().getAll()[0];
    expect(pendingMutation?.options.onSuccess).not.toBe(onSuccess);

    act(() => useAuthStore.getState().setLoggedIn("token-2", "bob", ""));
    await act(async () => {
      finishMutation?.("alice-result");
      await completion;
    });

    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("runs per-call callbacks while their originating generation is current", async () => {
    act(() =>
      useAuthStore.setState({ status: "logged-out", sessionGeneration: 20 }),
    );
    const onSuccess = vi.fn();
    const onSettled = vi.fn();
    let mutate:
      | ((
          options?: MutateOptions<string, Error, void, unknown>,
        ) => Promise<string>)
      | undefined;
    render(
      <QueryProvider>
        <MutationCallbackProbe
          mutationFn={async () => "current-result"}
          onReady={(nextMutate) => {
            mutate = nextMutate;
          }}
          onSuccess={vi.fn()}
        />
      </QueryProvider>,
    );
    await waitFor(() => expect(mutate).toBeTypeOf("function"));

    await act(async () => {
      await mutate?.({ onSuccess, onSettled });
    });

    expect(onSuccess).toHaveBeenCalledOnce();
    expect(onSettled).toHaveBeenCalledOnce();
  });

  it("suppresses per-call callbacks after any auth generation change", async () => {
    act(() =>
      useAuthStore.setState({ status: "logged-out", sessionGeneration: 30 }),
    );
    const onSuccess = vi.fn();
    const onSettled = vi.fn();
    let finishMutation: ((value: string) => void) | undefined;
    let mutate:
      | ((
          options?: MutateOptions<string, Error, void, unknown>,
        ) => Promise<string>)
      | undefined;
    render(
      <QueryProvider>
        <MutationCallbackProbe
          mutationFn={() =>
            new Promise<string>((resolve) => {
              finishMutation = resolve;
            })
          }
          onReady={(nextMutate) => {
            mutate = nextMutate;
          }}
          onSuccess={vi.fn()}
        />
      </QueryProvider>,
    );
    await waitFor(() => expect(mutate).toBeTypeOf("function"));

    let completion: Promise<string> | undefined;
    act(() => {
      completion = mutate?.({ onSuccess, onSettled });
    });
    await waitFor(() =>
      expect(screen.getByTestId("mutation-status")).toHaveTextContent(
        "pending",
      ),
    );
    act(() => useAuthStore.setState({ sessionGeneration: 31 }));
    await act(async () => {
      finishMutation?.("retired-result");
      await completion;
    });

    expect(onSuccess).not.toHaveBeenCalled();
    expect(onSettled).not.toHaveBeenCalled();
  });

  it("suppresses external error callbacks after the authenticated identity changes", async () => {
    act(() => useAuthStore.getState().setLoggedIn("token-1", "alice", ""));
    const retiredClient = queryClient;
    const onError = vi.fn();
    const onSettled = vi.fn();
    let failMutation: ((error: Error) => void) | undefined;
    const mutation = retiredClient
      .getMutationCache()
      .build<string, Error, void, unknown>(retiredClient, {
        mutationFn: () =>
          new Promise<string>((_resolve, reject) => {
            failMutation = reject;
          }),
        onError,
        onSettled,
      });
    const completion = mutation.execute(undefined).catch(() => undefined);
    await Promise.resolve();

    act(() => useAuthStore.getState().setLoggedIn("token-2", "bob", ""));
    failMutation?.(new Error("alice failure"));
    await completion;

    expect(onError).not.toHaveBeenCalled();
    expect(onSettled).not.toHaveBeenCalled();
  });
});
