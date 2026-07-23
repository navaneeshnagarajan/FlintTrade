import { StringDecoder } from "node:string_decoder";

const APPLICATION_PID_LINE = /^FLINTTRADE_BACKEND_PID pid=([1-9][0-9]*)$/;
const READY_LINE = /^FLINTTRADE_BACKEND_READY port=([1-9][0-9]*)$/;
const BLOCKED_LINE = /^FLINTTRADE_BACKEND_BLOCKED reason=([a-z0-9]+(?:-[a-z0-9]+)*)$/;
const PENDING_EXIT_ACK_LINE =
  /^FLINTTRADE_BACKEND_PENDING_EXIT_ACK token=([0-9a-fA-F]{64}) reason=(promotion-failed|force-exit)$/;
const CLEANUP_COMPLETE_LINE = /^FLINTTRADE_BACKEND_CLEANUP_COMPLETE token=([0-9a-fA-F]{64})$/;
const NOTIFICATION_PREFIX = "FLINTTRADE_NOTIFY\t";

const DEFAULT_MAX_RAW_TAIL_BYTES = 4_096;
const DEFAULT_MAX_LINE_BYTES = 64 * 1_024;
const MAX_PROCESS_ID = 0xffff_ffff;

export type GuardianPendingExitReason = "force-exit" | "promotion-failed";

export type GuardianEvent =
  | { type: "application-pid"; pid: number }
  | { type: "ready"; port: number }
  | { type: "blocked"; reason: string }
  | { type: "pending-exit-ack"; reason: GuardianPendingExitReason; token: string }
  | { type: "cleanup-complete"; token: string }
  | { type: "notification"; body: string; title: string };

export interface GuardianProtocolOptions {
  maxLineBytes?: number;
  maxRawTailBytes?: number;
}

function parseBoundedPositiveInteger(raw: string, maximum: number): number | null {
  const value = Number(raw);
  return Number.isSafeInteger(value) && value >= 1 && value <= maximum ? value : null;
}

/** Parse one complete guardian stdout line without trimming or prefix recovery. */
export function parseGuardianLine(line: string): GuardianEvent | null {
  if (line.includes("\n") || line.includes("\r")) return null;

  let match = APPLICATION_PID_LINE.exec(line);
  if (match) {
    const pid = parseBoundedPositiveInteger(match[1]!, MAX_PROCESS_ID);
    return pid === null ? null : { type: "application-pid", pid };
  }

  match = READY_LINE.exec(line);
  if (match) {
    const port = parseBoundedPositiveInteger(match[1]!, 65_535);
    return port === null ? null : { type: "ready", port };
  }

  match = BLOCKED_LINE.exec(line);
  if (match) return { type: "blocked", reason: match[1]! };

  match = PENDING_EXIT_ACK_LINE.exec(line);
  if (match) {
    return {
      type: "pending-exit-ack",
      reason: match[2]! as GuardianPendingExitReason,
      token: match[1]!,
    };
  }

  match = CLEANUP_COMPLETE_LINE.exec(line);
  if (match) return { type: "cleanup-complete", token: match[1]! };

  if (!line.startsWith(NOTIFICATION_PREFIX)) return null;
  const fields = line.slice(NOTIFICATION_PREFIX.length).split("\t");
  if (fields.length !== 2) return null;
  const [title, body] = fields as [string, string];
  if (title.length === 0 || title.trim() !== title || body.trim() !== body) return null;
  return { type: "notification", body, title };
}

function assertPositiveByteLimit(label: string, value: number): void {
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new RangeError(`${label} must be a positive safe integer.`);
  }
}

function utf8Tail(value: string, maximumBytes: number): string {
  if (Buffer.byteLength(value, "utf8") <= maximumBytes) return value;
  const codePoints = Array.from(value);
  let bytes = 0;
  let start = codePoints.length;
  while (start > 0) {
    const size = Buffer.byteLength(codePoints[start - 1]!, "utf8");
    if (bytes + size > maximumBytes) break;
    bytes += size;
    start -= 1;
  }
  return codePoints.slice(start).join("");
}

/**
 * Incrementally decodes guardian stdout while emitting only newline-terminated
 * protocol lines. Oversized logical lines are discarded as a whole so a
 * retained suffix can never be mistaken for an exact sentinel.
 */
export class GuardianProtocol {
  private readonly decoder = new StringDecoder("utf8");
  private readonly maxLineBytes: number;
  private readonly maxRawTailBytes: number;
  private currentLine = "";
  private currentLineBytes = 0;
  private droppingCurrentLine = false;
  private tail = "";

  constructor(options: GuardianProtocolOptions = {}) {
    this.maxLineBytes = options.maxLineBytes ?? DEFAULT_MAX_LINE_BYTES;
    this.maxRawTailBytes = options.maxRawTailBytes ?? DEFAULT_MAX_RAW_TAIL_BYTES;
    assertPositiveByteLimit("Guardian protocol line limit", this.maxLineBytes);
    assertPositiveByteLimit("Guardian protocol raw-tail limit", this.maxRawTailBytes);
  }

  get rawTail(): string {
    return this.tail;
  }

  feed(chunk: Buffer): GuardianEvent[] {
    return this.consume(this.decoder.write(chunk));
  }

  /** Flush decoder state without treating an unterminated final fragment as a line. */
  end(chunk?: Buffer): GuardianEvent[] {
    const decoded = chunk === undefined ? this.decoder.end() : this.decoder.end(chunk);
    const events = this.consume(decoded);
    this.currentLine = "";
    this.currentLineBytes = 0;
    this.droppingCurrentLine = false;
    return events;
  }

  private consume(decoded: string): GuardianEvent[] {
    if (decoded.length === 0) return [];
    this.tail = utf8Tail(this.tail + decoded, this.maxRawTailBytes);
    const events: GuardianEvent[] = [];

    for (const character of decoded) {
      if (character === "\n") {
        if (!this.droppingCurrentLine) {
          const line = this.currentLine.endsWith("\r") ? this.currentLine.slice(0, -1) : this.currentLine;
          const event = parseGuardianLine(line);
          if (event) events.push(event);
        }
        this.currentLine = "";
        this.currentLineBytes = 0;
        this.droppingCurrentLine = false;
        continue;
      }

      if (this.droppingCurrentLine) continue;
      const byteLength = Buffer.byteLength(character, "utf8");
      if (this.currentLineBytes + byteLength > this.maxLineBytes) {
        this.currentLine = "";
        this.currentLineBytes = 0;
        this.droppingCurrentLine = true;
        continue;
      }
      this.currentLine += character;
      this.currentLineBytes += byteLength;
    }
    return events;
  }
}
