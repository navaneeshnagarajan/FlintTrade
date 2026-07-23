import { describe, expect, it, vi } from "vitest"

import type { BootstrapDependencies } from "./bootstrap"
import { createSourceUpdateIdentityDependencies } from "./source-update-identity"
import type { WindowsSourceFilesystemBoundary } from "./windows-source-filesystem"

const nativeIdentity = "0000000000000001:00000000000000000000000000000002"
const changedNativeIdentity = "0000000000000001:00000000000000000000000000000003"

function fixture(platform: NodeJS.Platform = "win32") {
  const assertDirectoryIdentity = vi.fn<BootstrapDependencies["fileSystem"]["assertDirectoryIdentity"]>(
    async () => undefined,
  )
  const directoryIdentity = vi.fn<BootstrapDependencies["fileSystem"]["directoryIdentity"]>(
    async () => ({ dev: 1, ino: 2 }),
  )
  const directoryMetadata = vi.fn<BootstrapDependencies["fileSystem"]["directoryMetadata"]>(async () => ({
    ctimeMs: 3,
    dev: 1,
    ino: 2,
    mtimeMs: 4,
    size: 5,
  }))
  const dependencies = {
    fileSystem: { assertDirectoryIdentity, directoryIdentity, directoryMetadata },
  } as unknown as BootstrapDependencies
  const inspectDirectory = vi.fn<WindowsSourceFilesystemBoundary["inspectDirectory"]>(
    async () => ({ nativeIdentity, status: "present" as const }),
  )
  const operationLease = {
    assertHeld: vi.fn(async () => undefined),
    target: "C:\\managed\\src\\.flinttrade-bootstrap-operation.lock",
  }
  const bound = createSourceUpdateIdentityDependencies({
    dependencies,
    operationLease,
    platform,
    windowsSourceFilesystem: { inspectDirectory },
  })
  return {
    assertDirectoryIdentity,
    bound,
    dependencies,
    directoryIdentity,
    directoryMetadata,
    inspectDirectory,
    operationLease,
  }
}

describe("source-update native identity dependencies", () => {
  it("brackets Node identity and metadata capture with stable lease-bound Windows File IDs", async () => {
    const test = fixture()
    const target = "C:\\managed\\src\\FlintTrade"

    await expect(test.bound.fileSystem.directoryIdentity(target)).resolves.toEqual({
      dev: 1,
      ino: 2,
      nativeIdentity,
    })
    await expect(test.bound.fileSystem.directoryMetadata(target)).resolves.toEqual({
      ctimeMs: 3,
      dev: 1,
      ino: 2,
      mtimeMs: 4,
      nativeIdentity,
      size: 5,
    })

    expect(test.inspectDirectory).toHaveBeenCalledTimes(4)
    expect(test.inspectDirectory).toHaveBeenNthCalledWith(1, target)
    expect(test.inspectDirectory).toHaveBeenNthCalledWith(2, target)
    expect(test.inspectDirectory).toHaveBeenNthCalledWith(3, target)
    expect(test.inspectDirectory).toHaveBeenNthCalledWith(4, target)
    expect(test.operationLease.assertHeld).toHaveBeenCalledTimes(4)
    expect(test.inspectDirectory.mock.invocationCallOrder[0]!).toBeLessThan(
      test.directoryIdentity.mock.invocationCallOrder[0]!,
    )
    expect(test.directoryIdentity.mock.invocationCallOrder[0]!).toBeLessThan(
      test.inspectDirectory.mock.invocationCallOrder[1]!,
    )
    expect(test.inspectDirectory.mock.invocationCallOrder[2]!).toBeLessThan(
      test.directoryMetadata.mock.invocationCallOrder[0]!,
    )
    expect(test.directoryMetadata.mock.invocationCallOrder[0]!).toBeLessThan(
      test.inspectDirectory.mock.invocationCallOrder[3]!,
    )
  })

  it.each([
    ["missing before", [{ status: "missing" as const }]],
    [
      "missing after",
      [
        { nativeIdentity, status: "present" as const },
        { status: "missing" as const },
      ],
    ],
    [
      "changed after",
      [
        { nativeIdentity, status: "present" as const },
        { nativeIdentity: changedNativeIdentity, status: "present" as const },
      ],
    ],
  ])("rejects %s native proof", async (_label, observations) => {
    const test = fixture()
    test.inspectDirectory.mockReset()
    for (const observation of observations) test.inspectDirectory.mockResolvedValueOnce(observation)

    await expect(test.bound.fileSystem.directoryIdentity("C:\\managed\\src\\FlintTrade"))
      .rejects.toThrow(/native (?:directory )?(?:evidence|identity)/i)
  })

  it("rejects a Node capture carrying conflicting native proof", async () => {
    const test = fixture()
    test.directoryIdentity.mockResolvedValueOnce({ dev: 1, ino: 2, nativeIdentity: changedNativeIdentity })

    await expect(test.bound.fileSystem.directoryIdentity("C:\\managed\\src\\FlintTrade"))
      .rejects.toThrow(/native directory identity changed/i)
  })

  it("brackets Node directory assertions with the expected native identity and preserves requireEmpty", async () => {
    const test = fixture()
    const target = "C:\\managed\\src\\FlintTrade"
    const expected = { dev: 1, ino: 2, nativeIdentity }

    await expect(test.bound.fileSystem.assertDirectoryIdentity(target, expected, true)).resolves.toBeUndefined()

    expect(test.assertDirectoryIdentity).toHaveBeenCalledWith(target, expected, true)
    expect(test.inspectDirectory).toHaveBeenCalledTimes(2)
    expect(test.inspectDirectory.mock.invocationCallOrder[0]!).toBeLessThan(
      test.assertDirectoryIdentity.mock.invocationCallOrder[0]!,
    )
    expect(test.assertDirectoryIdentity.mock.invocationCallOrder[0]!).toBeLessThan(
      test.inspectDirectory.mock.invocationCallOrder[1]!,
    )
    expect(test.operationLease.assertHeld).toHaveBeenCalledTimes(2)
  })

  it("rejects a Windows directory assertion without expected native proof", async () => {
    const test = fixture()

    await expect(test.bound.fileSystem.assertDirectoryIdentity(
      "C:\\managed\\src\\FlintTrade",
      { dev: 1, ino: 2 },
      true,
    )).rejects.toThrow(/requires an exact expected native identity/i)
    expect(test.assertDirectoryIdentity).not.toHaveBeenCalled()
    expect(test.inspectDirectory).not.toHaveBeenCalled()
  })

  it("rejects changed native proof across a Node directory assertion", async () => {
    const test = fixture()
    test.inspectDirectory
      .mockResolvedValueOnce({ nativeIdentity, status: "present" })
      .mockResolvedValueOnce({ nativeIdentity: changedNativeIdentity, status: "present" })

    await expect(test.bound.fileSystem.assertDirectoryIdentity(
      "C:\\managed\\src\\FlintTrade",
      { dev: 1, ino: 2, nativeIdentity },
      false,
    )).rejects.toThrow(/native directory identity changed/i)
  })

  it("leaves non-Windows dependencies untouched", () => {
    const test = fixture("darwin")
    expect(test.bound).toBe(test.dependencies)
    expect(test.inspectDirectory).not.toHaveBeenCalled()
  })
})
