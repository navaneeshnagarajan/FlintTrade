export type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

interface BoundedResponseOptions {
  fetcher: FetchLike;
  init: RequestInit;
  label: string;
  maximumBytes: number;
  signal: AbortSignal;
  timeoutMs: number;
  url: string;
  validateResponse(response: Response): void;
}

function abortReason(signal: AbortSignal, label: string): Error {
  return signal.reason instanceof Error
    ? signal.reason
    : new DOMException(`${label} was cancelled.`, "AbortError");
}

export async function raceWithAbort<T>(operation: Promise<T>, signal: AbortSignal, label: string): Promise<T> {
  // Keep a rejection sink attached when cancellation wins and the underlying
  // operation cannot itself be forcefully stopped.
  void operation.catch(() => undefined);
  if (signal.aborted) throw abortReason(signal, label);
  let onAbort: (() => void) | null = null;
  const aborted = new Promise<never>((_resolve, reject) => {
    onAbort = (): void => reject(abortReason(signal, label));
    signal.addEventListener("abort", onAbort, { once: true });
  });
  try {
    return await Promise.race([operation, aborted]);
  } finally {
    if (onAbort) signal.removeEventListener("abort", onAbort);
  }
}

function cancelResponseBody(response: Response, reason: unknown): void {
  if (!response.body) return;
  try {
    // Never await a peer-controlled cancellation algorithm.
    void response.body.cancel(reason).catch(() => undefined);
  } catch {
    // A locked or hostile body is also non-authoritative for shutdown.
  }
}

const typedArrayTagGetter = Object.getOwnPropertyDescriptor(
  Object.getPrototypeOf(Uint8Array.prototype) as object,
  Symbol.toStringTag,
)?.get;

function asByteView(value: unknown): Uint8Array | null {
  if (
    !ArrayBuffer.isView(value) ||
    !typedArrayTagGetter ||
    typedArrayTagGetter.call(value) !== "Uint8Array"
  ) {
    return null;
  }
  return value instanceof Uint8Array
    ? value
    : new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
}

async function readBoundedBody(
  response: Response,
  maximumBytes: number,
  signal: AbortSignal,
  label: string,
): Promise<Uint8Array> {
  const declared = response.headers.get("content-length");
  if (
    declared !== null &&
    (!/^(?:0|[1-9]\d*)$/.test(declared) || Number(declared) > maximumBytes)
  ) {
    throw new Error(`${label} exceeded its size limit.`);
  }
  if (!response.body) throw new Error(`${label} had no body.`);

  const reader = response.body.getReader();
  const output = new Uint8Array(maximumBytes);
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await raceWithAbort(reader.read(), signal, label);
      if (done) break;
      // Electron net.fetch() exposes Chromium-owned typed arrays whose realm
      // differs from Electron main. `instanceof Uint8Array` is therefore false
      // for valid body chunks. The intrinsic typed-array brand getter accepts
      // those byte arrays without trusting a spoofable own Symbol.toStringTag.
      const bytes = asByteView(value);
      if (!bytes) throw new Error(`${label} yielded a non-byte body.`);
      if (bytes.byteLength > maximumBytes - total) throw new Error(`${label} exceeded its size limit.`);
      output.set(bytes, total);
      total += bytes.byteLength;
    }
  } catch (error) {
    // Cancellation is deliberately fire-and-forget. A hostile stream may never
    // settle its cancel algorithm, but it must not retain application shutdown.
    void reader.cancel(error).catch(() => undefined);
    throw error;
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // A still-pending hostile read keeps its lock until cancellation settles.
    }
  }

  return output.slice(0, total);
}

export async function fetchBoundedResponse(options: BoundedResponseOptions): Promise<Uint8Array> {
  if (!Number.isSafeInteger(options.timeoutMs) || options.timeoutMs <= 0 || options.timeoutMs > 60_000) {
    throw new Error(`${options.label} timeout must be between 1 and 60000 milliseconds.`);
  }
  if (!Number.isSafeInteger(options.maximumBytes) || options.maximumBytes <= 0) {
    throw new Error(`${options.label} size limit must be a positive safe integer.`);
  }

  const controller = new AbortController();
  const forwardAbort = (): void => controller.abort(options.signal.reason);
  if (options.signal.aborted) forwardAbort();
  else options.signal.addEventListener("abort", forwardAbort, { once: true });
  const timeout = setTimeout(
    () => controller.abort(new DOMException(`${options.label} timed out.`, "TimeoutError")),
    options.timeoutMs,
  );

  try {
    const response = await raceWithAbort(
      Promise.resolve().then(() => options.fetcher(options.url, {
        ...options.init,
        signal: controller.signal,
      })),
      controller.signal,
      options.label,
    );
    try {
      options.validateResponse(response);
      return await readBoundedBody(
        response,
        options.maximumBytes,
        controller.signal,
        options.label,
      );
    } catch (error) {
      if (!controller.signal.aborted) controller.abort(error);
      cancelResponseBody(response, error);
      throw error;
    }
  } finally {
    clearTimeout(timeout);
    options.signal.removeEventListener("abort", forwardAbort);
  }
}
