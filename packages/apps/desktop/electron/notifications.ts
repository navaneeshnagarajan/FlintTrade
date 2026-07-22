const MAX_NOTIFICATION_TITLE = 128;
const MAX_NOTIFICATION_BODY = 1_024;
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f]/u;

export interface ParsedNotificationEvent {
  body: string;
  title: string;
  type: "notification";
}

export interface NativeNotificationDependencies {
  isSupported(): boolean;
  onFailure?(error: Error): void;
  show(notification: { body: string; title: string }): void;
}

function bounded(value: string, limit: number): string {
  return Array.from(value.trim()).slice(0, limit).join("");
}

export function createNativeNotificationRelay(dependencies: NativeNotificationDependencies) {
  return {
    publish(event: unknown): boolean {
      if (
        typeof event !== "object" ||
        event === null ||
        (event as { type?: unknown }).type !== "notification" ||
        typeof (event as { title?: unknown }).title !== "string" ||
        typeof (event as { body?: unknown }).body !== "string"
      ) {
        return false;
      }
      const parsed = event as ParsedNotificationEvent;
      const title = bounded(parsed.title, MAX_NOTIFICATION_TITLE);
      const body = bounded(parsed.body, MAX_NOTIFICATION_BODY);
      if (!title || CONTROL_CHARACTER.test(title) || CONTROL_CHARACTER.test(body) || !dependencies.isSupported()) {
        return false;
      }
      try {
        dependencies.show({ body, title });
        return true;
      } catch (error) {
        dependencies.onFailure?.(
          error instanceof Error ? error : new Error("Native notification delivery failed.", { cause: error }),
        );
        return false;
      }
    },
  };
}
