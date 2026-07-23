interface QuitApplication {
  quit(): void;
}

interface QuitEvent {
  preventDefault(): void;
}

interface BootstrapShutdown {
  shutdown(timeoutMs?: number): Promise<void>;
}

export function createBootstrapQuitGate(
  application: QuitApplication,
  bootstrap: BootstrapShutdown,
  timeoutMs = 10_000,
) {
  let allowingQuit = false;
  let settlement: Promise<void> | null = null;

  const requestQuit = (): Promise<void> => {
    if (allowingQuit) return Promise.resolve();
    if (!settlement) {
      const attempt = bootstrap.shutdown(timeoutMs).then(() => {
        allowingQuit = true;
        application.quit();
      });
      let retryable: Promise<void>;
      retryable = attempt.catch((error: unknown) => {
        allowingQuit = false;
        if (settlement === retryable) settlement = null;
        throw error;
      });
      settlement = retryable;
    }
    return settlement;
  };

  const requestQuitFailClosed = (): void => {
    void requestQuit().catch(() => {
      // Keep the application open when containment cannot be proved.
    });
  };

  return {
    handleBeforeQuit(event: QuitEvent): void {
      if (allowingQuit) return;
      event.preventDefault();
      requestQuitFailClosed();
    },
    requestQuit,
    requestQuitFailClosed,
  };
}
