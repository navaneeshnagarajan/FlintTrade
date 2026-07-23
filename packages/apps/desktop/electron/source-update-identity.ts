import type {
  BootstrapDependencies,
  FileSystemDirectoryMetadata,
  FileSystemIdentity,
} from "./bootstrap"
import type { SourceOperationLeaseProof } from "./source-operation"
import {
  WINDOWS_NATIVE_IDENTITY_PATTERN,
  type WindowsSourceFilesystemBoundary,
} from "./windows-source-filesystem"

export interface SourceUpdateIdentityDependenciesOptions {
  dependencies: BootstrapDependencies
  operationLease: SourceOperationLeaseProof
  platform: NodeJS.Platform
  windowsSourceFilesystem?: Pick<WindowsSourceFilesystemBoundary, "inspectDirectory">
}

/**
 * Add exact Windows File-ID evidence only to source-update provenance and staging.
 * The native helper itself is lease-bound; the explicit proofs here also keep an
 * injected boundary fail-closed and bracket the corresponding Node metadata read.
 */
export function createSourceUpdateIdentityDependencies(
  options: SourceUpdateIdentityDependenciesOptions,
): BootstrapDependencies {
  if (options.platform !== "win32") return options.dependencies
  if (!options.windowsSourceFilesystem) {
    throw new Error("Windows source-update identity capture requires the packaged native filesystem helper.")
  }

  const bindNativeIdentity = async <Identity extends FileSystemIdentity>(
    target: string,
    capture: () => Promise<Identity>,
  ): Promise<Identity> => {
    await options.operationLease.assertHeld()
    const before = await options.windowsSourceFilesystem!.inspectDirectory(target)
    if (
      before.status !== "present" ||
      !WINDOWS_NATIVE_IDENTITY_PATTERN.test(before.nativeIdentity)
    ) {
      throw new Error("Windows source-update identity capture requires present exact native evidence.")
    }

    const identity = await capture()
    const after = await options.windowsSourceFilesystem!.inspectDirectory(target)
    await options.operationLease.assertHeld()
    if (
      after.status !== "present" ||
      !WINDOWS_NATIVE_IDENTITY_PATTERN.test(after.nativeIdentity) ||
      after.nativeIdentity !== before.nativeIdentity ||
      (identity.nativeIdentity !== undefined && identity.nativeIdentity !== before.nativeIdentity)
    ) {
      throw new Error("Windows source-update native directory identity changed during Node inspection.")
    }
    return { ...identity, nativeIdentity: before.nativeIdentity }
  }

  const fileSystem = options.dependencies.fileSystem
  return {
    ...options.dependencies,
    fileSystem: {
      ...fileSystem,
      async assertDirectoryIdentity(target, identity, requireEmpty): Promise<void> {
        if (!WINDOWS_NATIVE_IDENTITY_PATTERN.test(identity.nativeIdentity ?? "")) {
          throw new Error("Windows source-update directory assertion requires an exact expected native identity.")
        }
        await options.operationLease.assertHeld()
        const before = await options.windowsSourceFilesystem!.inspectDirectory(target)
        if (before.status !== "present" || before.nativeIdentity !== identity.nativeIdentity) {
          throw new Error("Windows source-update directory assertion does not match its expected native identity.")
        }
        await fileSystem.assertDirectoryIdentity(target, identity, requireEmpty)
        const after = await options.windowsSourceFilesystem!.inspectDirectory(target)
        await options.operationLease.assertHeld()
        if (after.status !== "present" || after.nativeIdentity !== identity.nativeIdentity) {
          throw new Error("Windows source-update native directory identity changed during Node assertion.")
        }
      },
      directoryIdentity(target): Promise<FileSystemIdentity> {
        return bindNativeIdentity(target, () => fileSystem.directoryIdentity(target))
      },
      directoryMetadata(target): Promise<FileSystemDirectoryMetadata> {
        return bindNativeIdentity(target, () => fileSystem.directoryMetadata(target))
      },
    },
  }
}
