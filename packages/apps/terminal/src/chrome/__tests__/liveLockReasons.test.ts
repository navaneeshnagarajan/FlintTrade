/**
 * Live stays locked for every reason the desk can already name.
 * Qualification is optional until the Laya place gate reports it.
 */

import { describe, expect, it } from "vitest";
import {
  CREATE_A_PIN,
  ENROL_2FA_AND_CONNECT_BROKER,
  NOT_QUALIFIED_FOR_LIVE,
  liveMenuLockReasons,
  type LiveMenuLockStatus,
} from "../liveLockReasons";

const ready: LiveMenuLockStatus = {
  brokerConnected: true,
  totpEnrolled: true,
  hasPin: true,
};

describe("liveMenuLockReasons", () => {
  it("names the 2FA and broker lock when either is missing", () => {
    expect(liveMenuLockReasons({ brokerConnected: false, totpEnrolled: false, hasPin: true })).toEqual([
      ENROL_2FA_AND_CONNECT_BROKER,
    ]);
    expect(liveMenuLockReasons({ brokerConnected: true, totpEnrolled: false, hasPin: true })).toEqual([
      ENROL_2FA_AND_CONNECT_BROKER,
    ]);
    expect(liveMenuLockReasons({ brokerConnected: false, totpEnrolled: true, hasPin: true })).toEqual([
      ENROL_2FA_AND_CONNECT_BROKER,
    ]);
  });

  it("keeps Live locked when no PIN has been created", () => {
    expect(liveMenuLockReasons({
      brokerConnected: true,
      totpEnrolled: true,
      hasPin: false,
    })).toEqual([CREATE_A_PIN]);
  });

  it("does not invent a Laya qualification lock when the field is absent", () => {
    expect(liveMenuLockReasons(ready)).toEqual([]);
    expect(liveMenuLockReasons({ ...ready, layaQualifiedForLive: undefined })).toEqual([]);
    expect(liveMenuLockReasons({
      brokerConnected: false,
      totpEnrolled: false,
      hasPin: true,
    })).not.toContain(NOT_QUALIFIED_FOR_LIVE);
  });

  it("shows Not qualified for Live beside the 2FA and broker reason", () => {
    expect(liveMenuLockReasons({
      brokerConnected: false,
      totpEnrolled: false,
      hasPin: true,
      layaQualifiedForLive: false,
    })).toEqual([
      ENROL_2FA_AND_CONNECT_BROKER,
      NOT_QUALIFIED_FOR_LIVE,
    ]);
  });

  it("locks Live on qualification alone when 2FA and a broker are already in place", () => {
    expect(liveMenuLockReasons({
      ...ready,
      layaQualifiedForLive: false,
    })).toEqual([NOT_QUALIFIED_FOR_LIVE]);
  });

  it("adds nothing when Laya reports the operator is qualified", () => {
    expect(liveMenuLockReasons({
      ...ready,
      layaQualifiedForLive: true,
    })).toEqual([]);
  });
});
