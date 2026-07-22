using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Win32.SafeHandles;

internal static class Program
{
    private const uint FILE_READ_ATTRIBUTES = 0x00000080;
    private const uint GENERIC_READ = 0x80000000;
    private const uint GENERIC_WRITE = 0x40000000;
    private const uint DELETE = 0x00010000;
    private const uint SYNCHRONIZE = 0x00100000;
    private const uint FILE_SHARE_READ = 0x00000001;
    private const uint FILE_SHARE_WRITE = 0x00000002;
    private const uint FILE_SHARE_DELETE = 0x00000004;
    private const uint OPEN_EXISTING = 3;
    private const uint FILE_FLAG_BACKUP_SEMANTICS = 0x02000000;
    private const uint FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000;
    private const uint FILE_ATTRIBUTE_DIRECTORY = 0x00000010;
    private const uint FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400;
    private const uint INVALID_FILE_ATTRIBUTES = 0xffffffff;
    private const int FILE_ID_INFO_CLASS = 18;
    private const int FILE_RENAME_INFO_CLASS = 3;
    private const int FILE_DISPOSITION_INFO_CLASS = 4;
    private const int ERROR_FILE_NOT_FOUND = 2;
    private const int ERROR_PATH_NOT_FOUND = 3;
    private const int ERROR_ACCESS_DENIED = 5;
    private const int ERROR_SHARING_VIOLATION = 32;
    private const int ERROR_LOCK_VIOLATION = 33;
    private const int ERROR_ALREADY_EXISTS = 183;
    private const int ERROR_FILE_EXISTS = 80;
    private const int MAX_JOURNAL_BYTES = 128 * 1024;

    private static readonly IntPtr InvalidHandle = new IntPtr(-1);

    private static int Main(string[] args)
    {
        try
        {
            Options options = Options.Parse(args);
            if (options.Command == "inspect")
                return Inspect(options);
            if (options.Command == "inspect-journal")
                return InspectJournal(options);
            if (options.Command == "inspect-journal-entry")
                return InspectJournalEntry(options);
            if (options.Command == "rename")
                return RenameDirectory(options);
            if (options.Command == "commit-journal")
                return CommitJournal(options);
            if (options.Command == "remove-journal")
                return RemoveJournal(options);
            if (options.Command == "quarantine-directory")
                return QuarantineDirectory(options);
            throw new SourceFsException("INVALID_ARGUMENTS", 2);
        }
        catch (SourceFsException error)
        {
            EmitError(error.Code, error.NativeError);
            return error.ExitCode;
        }
        catch (Win32Exception error)
        {
            EmitError(CodeForNativeError(error.NativeErrorCode), error.NativeErrorCode);
            return IsLockError(error.NativeErrorCode) ? 75 : 5;
        }
        catch
        {
            EmitError("FILESYSTEM_ERROR", 0);
            return 5;
        }
    }

    private static int Inspect(Options options)
    {
        PinnedEntry entry = OpenPinned(options.Require("path"), EntryKind.Directory, true);
        if (entry == null)
        {
            Console.Out.WriteLine("{\"ok\":true,\"status\":\"missing\"}");
            return 0;
        }
        using (entry)
        {
            Console.Out.WriteLine(
                "{\"ok\":true,\"status\":\"present\",\"identity\":\"" +
                entry.Identity + "\"}");
        }
        return 0;
    }

    private static int InspectJournal(Options options)
    {
        string target = NormaliseAbsolutePath(options.Require("path"));
        string previous = ChildPath(Path.GetDirectoryName(target), Path.GetFileName(target) + ".previous");
        PinnedEntry entry = OpenPinned(target, EntryKind.File, true);
        PinnedEntry previousEntry = null;
        try
        {
            previousEntry = OpenPinned(previous, EntryKind.File, true);
            if (previousEntry != null)
                throw new SourceFsException("RESERVED_SIDECAR_OCCUPIED", 4);
            if (entry == null)
            {
                Console.Out.WriteLine("{\"ok\":true,\"status\":\"missing\"}");
                return 0;
            }
            Console.Out.WriteLine(
                "{\"ok\":true,\"status\":\"journal-present\",\"identity\":\"" +
                entry.Identity + "\",\"sha256\":\"" + HashOnly(entry) +
                "\",\"location\":\"target\"}");
        }
        finally
        {
            if (entry != null)
                entry.Dispose();
            if (previousEntry != null)
                previousEntry.Dispose();
        }
        return 0;
    }

    private static int InspectJournalEntry(Options options)
    {
        PinnedEntry entry = OpenPinned(options.Require("path"), EntryKind.File, true);
        if (entry == null)
        {
            Console.Out.WriteLine("{\"ok\":true,\"status\":\"missing\"}");
            return 0;
        }
        using (entry)
        {
            Console.Out.WriteLine(
                "{\"ok\":true,\"status\":\"journal-entry-present\",\"identity\":\"" +
                entry.Identity + "\",\"sha256\":\"" + HashOnly(entry) + "\"}");
        }
        return 0;
    }

    private static int RenameDirectory(Options options)
    {
        string parent = RequireTrustedParent(options.Require("parent"));
        string source = ChildPath(parent, options.Require("source"));
        string destination = ChildPath(parent, options.Require("destination"));
        string expected = RequireIdentity(options.Require("expected"));
        if (String.Equals(source, destination, StringComparison.OrdinalIgnoreCase))
            throw new SourceFsException("ENTRY_NAMES_ALIAS", 2);

        using (PinnedEntry parentEntry = RequireMutationPinned(parent, EntryKind.Directory, true))
        using (PinnedEntry sourceEntry = RequireMutationPinned(source, EntryKind.Directory))
        {
            RequireExpected(sourceEntry, expected);
            RequireAbsent(destination);
            RenamePinned(sourceEntry, parentEntry, Path.GetFileName(destination));
            FlushPinnedDirectory(parentEntry);
            RequireAbsent(source);
            using (PinnedEntry destinationEntry = RequirePinned(destination, EntryKind.Directory))
            {
                RequireExpected(destinationEntry, expected);
                RequireExpected(sourceEntry, destinationEntry.Identity);
            }
        }
        EmitSuccess("renamed");
        return 0;
    }

    private static int CommitJournal(Options options)
    {
        string parent = RequireTrustedParent(options.Require("parent"));
        string temporary = ChildPath(parent, options.Require("temporary"));
        string target = ChildPath(parent, options.Require("target"));
        string expectedSha256 = RequireSha256(options.Require("sha256"));
        ExpectedJournalEntry expectedTarget = ExpectedJournalEntry.Parse(
            options.Require("target-identity"),
            options.Require("target-sha256"));
        ExpectedJournalEntry expectedPrevious = ExpectedJournalEntry.Parse(
            options.Require("previous-identity"),
            options.Require("previous-sha256"));
        if (!expectedPrevious.IsMissing)
            throw new SourceFsException("RESERVED_SIDECAR_OCCUPIED", 4);
        if (String.Equals(temporary, target, StringComparison.OrdinalIgnoreCase))
            throw new SourceFsException("ENTRY_NAMES_ALIAS", 2);

        string previous = ChildPath(parent, Path.GetFileName(target) + ".previous");
        using (PinnedEntry parentEntry = RequireMutationPinned(parent, EntryKind.Directory, true))
        using (PinnedEntry temporaryEntry = OpenJournalMutationPinned(temporary, false, true))
        {
            string actualSha256 = HashAndFlush(temporaryEntry);
            if (!String.Equals(actualSha256, expectedSha256, StringComparison.Ordinal))
                throw new SourceFsException("CONTENT_MISMATCH", 4);

            PinnedEntry prior = null;
            PinnedEntry previousEntry = null;
            try
            {
                prior = OpenExpectedJournalEntry(target, expectedTarget);
                previousEntry = OpenExpectedJournalEntry(previous, expectedPrevious);
                if (prior != null)
                {
                    RenamePinned(prior, parentEntry, Path.GetFileName(previous));
                    FlushPinnedDirectory(parentEntry);
                    RequireAbsent(target);
                }
                else
                {
                    RequireAbsent(target);
                }
                RenamePinned(temporaryEntry, parentEntry, Path.GetFileName(target));
                FlushPinnedDirectory(parentEntry);
                RequireAbsent(temporary);
                using (PinnedEntry committed = RequirePinned(target, EntryKind.File))
                {
                    RequireExpected(committed, temporaryEntry.Identity);
                    string committedSha256 = HashOnly(committed);
                    if (!String.Equals(committedSha256, expectedSha256, StringComparison.Ordinal))
                        throw new SourceFsException("CONTENT_MISMATCH", 4);
                }
                if (prior != null)
                {
                    RequireExpectedJournalState(previous, expectedTarget);
                    MarkDelete(prior);
                    prior.Dispose();
                    prior = null;
                    FlushPinnedDirectory(parentEntry);
                }
                RequireAbsent(previous);
            }
            finally
            {
                if (prior != null)
                    prior.Dispose();
                if (previousEntry != null)
                    previousEntry.Dispose();
            }
        }
        EmitSuccess("journal-committed");
        return 0;
    }

    private static int RemoveJournal(Options options)
    {
        string parent = RequireTrustedParent(options.Require("parent"));
        string target = ChildPath(parent, options.Require("target"));
        string previous = ChildPath(parent, Path.GetFileName(target) + ".previous");
        ExpectedJournalEntry expectedTarget = ExpectedJournalEntry.Parse(
            options.Require("target-identity"),
            options.Require("target-sha256"));
        ExpectedJournalEntry expectedPrevious = ExpectedJournalEntry.Parse(
            options.Require("previous-identity"),
            options.Require("previous-sha256"));
        if (!expectedPrevious.IsMissing)
            throw new SourceFsException("RESERVED_SIDECAR_OCCUPIED", 4);

        using (PinnedEntry parentEntry = RequireMutationPinned(parent, EntryKind.Directory, true))
        {
            PinnedEntry targetEntry = null;
            PinnedEntry previousEntry = null;
            try
            {
                targetEntry = OpenExpectedJournalEntry(target, expectedTarget);
                previousEntry = OpenExpectedJournalEntry(previous, expectedPrevious);
                if (targetEntry != null)
                {
                    MarkDelete(targetEntry);
                    targetEntry.Dispose();
                    targetEntry = null;
                    FlushPinnedDirectory(parentEntry);
                    RequireAbsent(target);
                }
                RequireAbsent(previous);
                RequireAbsent(target);
            }
            finally
            {
                if (targetEntry != null)
                    targetEntry.Dispose();
                if (previousEntry != null)
                    previousEntry.Dispose();
            }
        }
        EmitSuccess("journal-removed");
        return 0;
    }

    private static int QuarantineDirectory(Options options)
    {
        string parent = RequireTrustedParent(options.Require("parent"));
        string target = ChildPath(parent, options.Require("target"));
        string quarantine = ChildPath(parent, options.Require("quarantine"));
        string expected = RequireIdentity(options.Require("expected"));
        if (String.Equals(target, quarantine, StringComparison.OrdinalIgnoreCase))
            throw new SourceFsException("ENTRY_NAMES_ALIAS", 2);

        using (PinnedEntry parentEntry = RequireMutationPinned(parent, EntryKind.Directory, true))
        {
            PinnedEntry atTarget = OpenMutationPinned(target, EntryKind.Directory, true);
            PinnedEntry atQuarantine = OpenMutationPinned(quarantine, EntryKind.Directory, true);
            try
            {
                if ((atTarget == null) == (atQuarantine == null))
                    throw new SourceFsException("AMBIGUOUS_EVIDENCE", 4);
                PinnedEntry pinned = atTarget ?? atQuarantine;
                RequireExpected(pinned, expected);
                if (atTarget != null)
                {
                    RenamePinned(pinned, parentEntry, Path.GetFileName(quarantine));
                    FlushPinnedDirectory(parentEntry);
                    RequireAbsent(target);
                }
                RequireExpected(pinned, expected);
                using (PinnedEntry preserved = RequirePinned(quarantine, EntryKind.Directory))
                {
                    RequireExpected(preserved, expected);
                    RequireExpected(pinned, preserved.Identity);
                }
            }
            finally
            {
                if (atTarget != null)
                    atTarget.Dispose();
                if (atQuarantine != null)
                    atQuarantine.Dispose();
            }
        }
        RequireAbsent(target);
        EmitSuccess("quarantined");
        return 0;
    }

    private static string RequireTrustedParent(string supplied)
    {
        string parent = NormaliseAbsolutePath(supplied);
        using (PinnedEntry entry = RequirePinned(parent, EntryKind.Directory))
        {
            string canonical = NormaliseAbsolutePath(entry.CanonicalPath);
            if (!String.Equals(parent, canonical, StringComparison.OrdinalIgnoreCase))
                throw new SourceFsException("ALIASED_PARENT", 4);
        }
        return parent;
    }

    private static string ChildPath(string parent, string name)
    {
        ValidateEntryName(name);
        string child = NormaliseAbsolutePath(Path.Combine(parent, name));
        if (!String.Equals(Path.GetDirectoryName(child), parent, StringComparison.OrdinalIgnoreCase))
            throw new SourceFsException("PATH_ESCAPE", 2);
        return child;
    }

    private static void ValidateEntryName(string name)
    {
        if (String.IsNullOrEmpty(name) || name == "." || name == ".." ||
            name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
            name.IndexOf('/') >= 0 || name.IndexOf('\\') >= 0 || name.IndexOf(':') >= 0)
        {
            throw new SourceFsException("INVALID_ENTRY_NAME", 2);
        }
    }

    private static string NormaliseAbsolutePath(string supplied)
    {
        if (String.IsNullOrEmpty(supplied) || !Path.IsPathRooted(supplied))
            throw new SourceFsException("INVALID_PATH", 2);
        string full = Path.GetFullPath(supplied);
        string root = Path.GetPathRoot(full);
        if (!String.Equals(full, root, StringComparison.OrdinalIgnoreCase))
            full = full.TrimEnd('\\');
        return full;
    }

    private static string ToExtendedPath(string path)
    {
        if (path.StartsWith("\\\\?\\", StringComparison.Ordinal))
            return path;
        if (path.StartsWith("\\\\", StringComparison.Ordinal))
            return "\\\\?\\UNC\\" + path.Substring(2);
        return "\\\\?\\" + path;
    }

    private static string NormaliseFinalPath(string value)
    {
        if (value.StartsWith("\\\\?\\UNC\\", StringComparison.OrdinalIgnoreCase))
            value = "\\\\" + value.Substring(8);
        else if (value.StartsWith("\\\\?\\", StringComparison.OrdinalIgnoreCase))
            value = value.Substring(4);
        return NormaliseAbsolutePath(value);
    }

    private static PinnedEntry RequirePinned(string path, EntryKind kind)
    {
        PinnedEntry entry = OpenPinned(path, kind, false);
        if (entry == null)
            throw new SourceFsException("MISSING_EVIDENCE", 4);
        return entry;
    }

    private static PinnedEntry RequirePinned(string path, EntryKind kind, bool writable)
    {
        PinnedEntry entry = OpenPinned(path, kind, false, writable);
        if (entry == null)
            throw new SourceFsException("MISSING_EVIDENCE", 4);
        return entry;
    }

    private static PinnedEntry RequireMutationPinned(string path, EntryKind kind)
    {
        PinnedEntry entry = OpenMutationPinned(path, kind, false, false);
        if (entry == null)
            throw new SourceFsException("MISSING_EVIDENCE", 4);
        return entry;
    }

    private static PinnedEntry RequireMutationPinned(string path, EntryKind kind, bool writable)
    {
        PinnedEntry entry = OpenMutationPinned(path, kind, false, writable);
        if (entry == null)
            throw new SourceFsException("MISSING_EVIDENCE", 4);
        return entry;
    }

    private static PinnedEntry OpenMutationPinned(string path, EntryKind kind, bool optional)
    {
        return OpenMutationPinned(path, kind, optional, false);
    }

    private static PinnedEntry OpenMutationPinned(
        string path,
        EntryKind kind,
        bool optional,
        bool writable)
    {
        return OpenPinnedCore(path, kind, optional, writable, true, false, true);
    }

    private static PinnedEntry OpenJournalMutationPinned(
        string path,
        bool optional,
        bool writable)
    {
        PinnedEntry entry = OpenPinnedCore(
            path,
            EntryKind.File,
            optional,
            writable,
            true,
            false,
            false);
        if (entry == null && !optional)
            throw new SourceFsException("MISSING_EVIDENCE", 4);
        return entry;
    }

    private static PinnedEntry OpenPinned(string supplied, EntryKind kind, bool optional)
    {
        return OpenPinned(supplied, kind, optional, false);
    }

    private static PinnedEntry OpenPinned(string supplied, EntryKind kind, bool optional, bool writable)
    {
        return OpenPinnedCore(supplied, kind, optional, writable, false, false, true);
    }

    private static PinnedEntry OpenPinnedCore(
        string supplied,
        EntryKind? kind,
        bool optional,
        bool writable,
        bool exclusiveMutation,
        bool allowReparse,
        bool shareWrite)
    {
        string path = NormaliseAbsolutePath(supplied);
        uint access = FILE_READ_ATTRIBUTES | SYNCHRONIZE;
        if (kind == EntryKind.File)
            access |= GENERIC_READ;
        if (writable)
            access |= GENERIC_WRITE;
        if (exclusiveMutation)
            access |= DELETE;
        IntPtr handle = CreateFileW(
            ToExtendedPath(path),
            access,
            FILE_SHARE_READ |
                (shareWrite ? FILE_SHARE_WRITE : 0) |
                (exclusiveMutation ? 0 : FILE_SHARE_DELETE),
            IntPtr.Zero,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
            IntPtr.Zero);
        if (handle == InvalidHandle)
        {
            int native = Marshal.GetLastWin32Error();
            if (optional && IsMissing(native))
                return null;
            throw NativeError("CreateFileW", native);
        }

        try
        {
            BY_HANDLE_FILE_INFORMATION basic;
            if (!GetFileInformationByHandle(handle, out basic))
                throw NativeError("GetFileInformationByHandle");
            bool reparse = (basic.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0;
            if (reparse && !allowReparse)
                throw new SourceFsException("REPARSE_POINT", 4);
            bool directory = (basic.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0;
            if (kind.HasValue &&
                ((kind.Value == EntryKind.Directory && !directory) ||
                 (kind.Value == EntryKind.File && directory)))
                throw new SourceFsException("UNEXPECTED_ENTRY_TYPE", 4);

            FILE_ID_INFO identity = new FILE_ID_INFO();
            identity.FileId = new byte[16];
            if (!GetFileInformationByHandleEx(
                    handle,
                    FILE_ID_INFO_CLASS,
                    ref identity,
                    (uint)Marshal.SizeOf(typeof(FILE_ID_INFO))))
            {
                throw NativeError("GetFileInformationByHandleEx(FileIdInfo)");
            }

            string canonical = FinalPath(handle);
            if (!String.Equals(path, canonical, StringComparison.OrdinalIgnoreCase))
                throw new SourceFsException("ALIASED_PATH", 4);
            string exactIdentity = FormatIdentity(identity);
            PinnedEntry result = new PinnedEntry(handle, canonical, exactIdentity, directory, reparse);
            handle = InvalidHandle;
            return result;
        }
        finally
        {
            if (handle != InvalidHandle)
                CloseHandle(handle);
        }
    }

    private static string FinalPath(IntPtr handle)
    {
        StringBuilder buffer = new StringBuilder(32768);
        uint length = GetFinalPathNameByHandleW(handle, buffer, (uint)buffer.Capacity, 0);
        if (length == 0 || length >= (uint)buffer.Capacity)
            throw NativeError("GetFinalPathNameByHandleW");
        return NormaliseFinalPath(buffer.ToString());
    }

    private static string FormatIdentity(FILE_ID_INFO identity)
    {
        StringBuilder value = new StringBuilder(49);
        value.Append(identity.VolumeSerialNumber.ToString("x16", CultureInfo.InvariantCulture));
        value.Append(':');
        for (int index = 0; index < identity.FileId.Length; index++)
            value.Append(identity.FileId[index].ToString("x2", CultureInfo.InvariantCulture));
        return value.ToString();
    }

    private static string RequireIdentity(string value)
    {
        if (value == null || value.Length != 49 || value[16] != ':')
            throw new SourceFsException("INVALID_IDENTITY", 2);
        for (int index = 0; index < value.Length; index++)
        {
            if (index == 16)
                continue;
            char current = value[index];
            if (!((current >= '0' && current <= '9') || (current >= 'a' && current <= 'f')))
                throw new SourceFsException("INVALID_IDENTITY", 2);
        }
        return value;
    }

    private static string RequireSha256(string value)
    {
        if (value == null || value.Length != 64)
            throw new SourceFsException("INVALID_DIGEST", 2);
        for (int index = 0; index < value.Length; index++)
        {
            char current = value[index];
            if (!((current >= '0' && current <= '9') || (current >= 'a' && current <= 'f')))
                throw new SourceFsException("INVALID_DIGEST", 2);
        }
        return value;
    }

    private static void RequireExpected(PinnedEntry entry, string expected)
    {
        if (!String.Equals(entry.Identity, expected, StringComparison.Ordinal))
            throw new SourceFsException("IDENTITY_MISMATCH", 4);
    }

    private static PinnedEntry OpenExpectedJournalEntry(
        string path,
        ExpectedJournalEntry expected)
    {
        PinnedEntry entry = OpenJournalMutationPinned(path, true, false);
        if (expected.IsMissing)
        {
            if (entry != null)
            {
                entry.Dispose();
                throw new SourceFsException("RESERVED_SIDECAR_OCCUPIED", 4);
            }
            return null;
        }
        if (entry == null)
            throw new SourceFsException("MISSING_EVIDENCE", 4);
        try
        {
            RequireExpected(entry, expected.Identity);
            if (!String.Equals(HashOnly(entry), expected.Sha256, StringComparison.Ordinal))
                throw new SourceFsException("CONTENT_MISMATCH", 4);
            return entry;
        }
        catch
        {
            entry.Dispose();
            throw;
        }
    }

    private static void RequireExpectedJournalState(
        string path,
        ExpectedJournalEntry expected)
    {
        if (expected.IsMissing)
        {
            RequireAbsent(path);
            return;
        }
        using (PinnedEntry entry = RequirePinned(path, EntryKind.File))
        {
            RequireExpected(entry, expected.Identity);
            if (!String.Equals(HashOnly(entry), expected.Sha256, StringComparison.Ordinal))
                throw new SourceFsException("CONTENT_MISMATCH", 4);
        }
    }

    private static void RequireAbsent(string path)
    {
        uint attributes = GetFileAttributesW(ToExtendedPath(path));
        if (attributes != INVALID_FILE_ATTRIBUTES)
            throw new SourceFsException("DESTINATION_OCCUPIED", 4);
        int native = Marshal.GetLastWin32Error();
        if (!IsMissing(native))
            throw NativeError("GetFileAttributesW", native);
    }

    private static void RenamePinned(PinnedEntry source, PinnedEntry parent, string destinationName)
    {
        ValidateEntryName(destinationName);
        byte[] name = Encoding.Unicode.GetBytes(destinationName);
        int headerBytes = IntPtr.Size == 8 ? 20 : 12;
        IntPtr information = Marshal.AllocHGlobal(headerBytes + name.Length);
        try
        {
            for (int index = 0; index < headerBytes; index++)
                Marshal.WriteByte(information, index, 0);
            Marshal.WriteInt32(information, 0, 0);
            Marshal.WriteIntPtr(information, IntPtr.Size == 8 ? 8 : 4, parent.Handle);
            Marshal.WriteInt32(information, IntPtr.Size == 8 ? 16 : 8, name.Length);
            Marshal.Copy(name, 0, IntPtr.Add(information, headerBytes), name.Length);
            if (!SetFileInformationByHandle(
                    source.Handle,
                    FILE_RENAME_INFO_CLASS,
                    information,
                    (uint)(headerBytes + name.Length)))
            {
                throw NativeError("SetFileInformationByHandle(FileRenameInfo)");
            }
        }
        finally
        {
            Marshal.FreeHGlobal(information);
        }
    }

    private static void MarkDelete(PinnedEntry entry)
    {
        IntPtr information = Marshal.AllocHGlobal(1);
        try
        {
            Marshal.WriteByte(information, 0, 1);
            if (!SetFileInformationByHandle(
                    entry.Handle,
                    FILE_DISPOSITION_INFO_CLASS,
                    information,
                    1))
            {
                throw NativeError("SetFileInformationByHandle(FileDispositionInfo)");
            }
        }
        finally
        {
            Marshal.FreeHGlobal(information);
        }
    }

    private static string HashAndFlush(PinnedEntry entry)
    {
        if (!FlushFileBuffers(entry.Handle))
            throw NativeError("FlushFileBuffers(journal)");
        return HashOnly(entry);
    }

    private static string HashOnly(PinnedEntry entry)
    {
        SafeFileHandle safe = new SafeFileHandle(entry.Handle, false);
        using (FileStream stream = new FileStream(safe, FileAccess.Read, 4096, false))
        {
            if (stream.Length > MAX_JOURNAL_BYTES)
                throw new SourceFsException("JOURNAL_TOO_LARGE", 4);
            stream.Position = 0;
            using (SHA256 algorithm = SHA256.Create())
            {
                byte[] digest = algorithm.ComputeHash(stream);
                StringBuilder value = new StringBuilder(64);
                for (int index = 0; index < digest.Length; index++)
                    value.Append(digest[index].ToString("x2", CultureInfo.InvariantCulture));
                return value.ToString();
            }
        }
    }

    private static void FlushPinnedDirectory(PinnedEntry directory)
    {
        if (!directory.IsDirectory || directory.IsReparsePoint)
            throw new SourceFsException("UNEXPECTED_ENTRY_TYPE", 4);
        if (!FlushFileBuffers(directory.Handle))
        {
            int native = Marshal.GetLastWin32Error();
            throw new SourceFsException("DURABILITY_UNAVAILABLE", 4, native);
        }
    }

    private static bool IsMissing(int native)
    {
        return native == ERROR_FILE_NOT_FOUND || native == ERROR_PATH_NOT_FOUND;
    }

    private static bool IsLockError(int native)
    {
        return native == ERROR_ACCESS_DENIED ||
            native == ERROR_SHARING_VIOLATION ||
            native == ERROR_LOCK_VIOLATION;
    }

    private static string CodeForNativeError(int native)
    {
        if (IsLockError(native))
            return "LOCKED";
        if (IsMissing(native))
            return "MISSING_EVIDENCE";
        if (native == ERROR_ALREADY_EXISTS || native == ERROR_FILE_EXISTS)
            return "DESTINATION_OCCUPIED";
        return "FILESYSTEM_ERROR";
    }

    private static Win32Exception NativeError(string operation)
    {
        return NativeError(operation, Marshal.GetLastWin32Error());
    }

    private static Win32Exception NativeError(string operation, int native)
    {
        return new Win32Exception(native, operation + " failed");
    }

    private static void EmitSuccess(string status)
    {
        Console.Out.WriteLine("{\"ok\":true,\"status\":\"" + status + "\"}");
    }

    private static void EmitError(string code, int native)
    {
        Console.Out.WriteLine(
            "{\"ok\":false,\"code\":\"" + code + "\",\"native\":" +
            native.ToString(CultureInfo.InvariantCulture) + "}");
    }

    private enum EntryKind
    {
        Directory,
        File
    }

    private sealed class ExpectedJournalEntry
    {
        internal readonly bool IsMissing;
        internal readonly string Identity;
        internal readonly string Sha256;

        private ExpectedJournalEntry(bool isMissing, string identity, string sha256)
        {
            this.IsMissing = isMissing;
            this.Identity = identity;
            this.Sha256 = sha256;
        }

        internal static ExpectedJournalEntry Parse(string identity, string sha256)
        {
            if (identity == "missing" && sha256 == "missing")
                return new ExpectedJournalEntry(true, null, null);
            if (identity == "missing" || sha256 == "missing")
                throw new SourceFsException("INVALID_EXPECTED_JOURNAL_ENTRY", 2);
            return new ExpectedJournalEntry(
                false,
                RequireIdentity(identity),
                RequireSha256(sha256));
        }
    }

    private sealed class PinnedEntry : IDisposable
    {
        internal readonly IntPtr Handle;
        internal readonly string CanonicalPath;
        internal readonly string Identity;
        internal readonly bool IsDirectory;
        internal readonly bool IsReparsePoint;
        private bool disposed;

        internal PinnedEntry(
            IntPtr handle,
            string canonicalPath,
            string identity,
            bool isDirectory,
            bool isReparsePoint)
        {
            this.Handle = handle;
            this.CanonicalPath = canonicalPath;
            this.Identity = identity;
            this.IsDirectory = isDirectory;
            this.IsReparsePoint = isReparsePoint;
        }

        public void Dispose()
        {
            if (this.disposed)
                return;
            this.disposed = true;
            CloseHandle(this.Handle);
        }
    }

    private sealed class SourceFsException : Exception
    {
        internal readonly string Code;
        internal readonly int ExitCode;
        internal readonly int NativeError;

        internal SourceFsException(string code, int exitCode)
            : this(code, exitCode, 0)
        {
        }

        internal SourceFsException(string code, int exitCode, int nativeError)
            : base(code)
        {
            this.Code = code;
            this.ExitCode = exitCode;
            this.NativeError = nativeError;
        }
    }

    private sealed class Options
    {
        internal string Command;
        private readonly Dictionary<string, string> values;

        private Options(string command, Dictionary<string, string> values)
        {
            this.Command = command;
            this.values = values;
        }

        internal string Require(string key)
        {
            string value;
            if (!this.values.TryGetValue(key, out value))
                throw new SourceFsException("INVALID_ARGUMENTS", 2);
            return value;
        }

        internal static Options Parse(string[] args)
        {
            if (args.Length < 3 || args[0] != "--source-fs" || args[1] != "1")
                throw new SourceFsException("INVALID_ARGUMENTS", 2);
            string command = args[2];
            Dictionary<string, string> values = new Dictionary<string, string>(StringComparer.Ordinal);
            int index = 3;
            while (index < args.Length)
            {
                string option = args[index++];
                if (!option.StartsWith("--", StringComparison.Ordinal) || index >= args.Length)
                    throw new SourceFsException("INVALID_ARGUMENTS", 2);
                string key = option.Substring(2);
                if (key.Length == 0 || values.ContainsKey(key))
                    throw new SourceFsException("INVALID_ARGUMENTS", 2);
                values.Add(key, args[index++]);
            }
            if (command == "inspect" && values.Count == 1 && values.ContainsKey("path"))
                return new Options(command, values);
            if (command == "inspect-journal" && values.Count == 1 && values.ContainsKey("path"))
                return new Options(command, values);
            if (command == "inspect-journal-entry" && values.Count == 1 && values.ContainsKey("path"))
                return new Options(command, values);
            if (command == "rename" && values.Count == 4 &&
                values.ContainsKey("parent") && values.ContainsKey("source") &&
                values.ContainsKey("destination") && values.ContainsKey("expected"))
                return new Options(command, values);
            if (command == "commit-journal" && values.Count == 8 &&
                values.ContainsKey("parent") && values.ContainsKey("temporary") &&
                values.ContainsKey("target") && values.ContainsKey("sha256") &&
                values.ContainsKey("target-identity") && values.ContainsKey("target-sha256") &&
                values.ContainsKey("previous-identity") && values.ContainsKey("previous-sha256"))
                return new Options(command, values);
            if (command == "remove-journal" && values.Count == 6 &&
                values.ContainsKey("parent") && values.ContainsKey("target") &&
                values.ContainsKey("target-identity") && values.ContainsKey("target-sha256") &&
                values.ContainsKey("previous-identity") && values.ContainsKey("previous-sha256"))
                return new Options(command, values);
            if (command == "quarantine-directory" && values.Count == 4 &&
                values.ContainsKey("parent") && values.ContainsKey("target") &&
                values.ContainsKey("quarantine") && values.ContainsKey("expected"))
                return new Options(command, values);
            throw new SourceFsException("INVALID_ARGUMENTS", 2);
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FILETIME
    {
        internal uint dwLowDateTime;
        internal uint dwHighDateTime;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct BY_HANDLE_FILE_INFORMATION
    {
        internal uint dwFileAttributes;
        internal FILETIME ftCreationTime;
        internal FILETIME ftLastAccessTime;
        internal FILETIME ftLastWriteTime;
        internal uint dwVolumeSerialNumber;
        internal uint nFileSizeHigh;
        internal uint nFileSizeLow;
        internal uint nNumberOfLinks;
        internal uint nFileIndexHigh;
        internal uint nFileIndexLow;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FILE_ID_INFO
    {
        internal ulong VolumeSerialNumber;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 16)]
        internal byte[] FileId;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateFileW(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(
        IntPtr file,
        out BY_HANDLE_FILE_INFORMATION information);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandleEx(
        IntPtr file,
        int informationClass,
        ref FILE_ID_INFO information,
        uint bufferSize);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandleW(
        IntPtr file,
        StringBuilder path,
        uint pathLength,
        uint flags);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFileAttributesW(string fileName);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetFileInformationByHandle(
        IntPtr file,
        int informationClass,
        IntPtr information,
        uint bufferSize);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool FlushFileBuffers(IntPtr file);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);
}
