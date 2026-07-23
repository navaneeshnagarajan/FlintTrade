using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
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
    private const uint CREATE_NEW = 1;
    private const uint OPEN_EXISTING = 3;
    private const uint FILE_FLAG_BACKUP_SEMANTICS = 0x02000000;
    private const uint FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000;
    private const uint FILE_ATTRIBUTE_NORMAL = 0x00000080;
    private const uint FILE_ATTRIBUTE_DIRECTORY = 0x00000010;
    private const uint FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400;
    private const uint INVALID_FILE_ATTRIBUTES = 0xffffffff;
    private const int FILE_ID_INFO_CLASS = 18;
    private const int FILE_RENAME_INFO_CLASS = 3;
    private const int FILE_DISPOSITION_INFO_CLASS = 4;
    private const int FILE_DISPOSITION_INFO_EX_CLASS = 21;
    private const uint FILE_DISPOSITION_FLAG_DELETE = 0x00000001;
    private const uint FILE_DISPOSITION_FLAG_IGNORE_READONLY_ATTRIBUTE = 0x00000010;
    private const int ERROR_FILE_NOT_FOUND = 2;
    private const int ERROR_PATH_NOT_FOUND = 3;
    private const int ERROR_ACCESS_DENIED = 5;
    private const int ERROR_SHARING_VIOLATION = 32;
    private const int ERROR_LOCK_VIOLATION = 33;
    private const int ERROR_INVALID_PARAMETER = 87;
    private const int ERROR_ALREADY_EXISTS = 183;
    private const int ERROR_FILE_EXISTS = 80;
    private const int ERROR_NO_MORE_FILES = 18;
    private const int MAX_JOURNAL_BYTES = 128 * 1024;
    private const int MAX_JOURNAL_TRANSACTION_BYTES = 4 * 1024;
    private const int MAX_RECLAMATION_DEPTH = 256;
    private const int MAX_RECLAMATION_ENTRIES = 1000000;

    private static readonly IntPtr InvalidHandle = new IntPtr(-1);
    private static readonly Regex ManagedQuarantineName = new Regex(
        @"^\.FlintTrade\.(?:stale-quarantine-|cleanup-quarantine-(?:candidate-|isolation-|staging-(?:candidate|unpack)-[1-9][0-9]*-))[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        RegexOptions.CultureInvariant | RegexOptions.IgnoreCase);

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
            if (options.Command == "recover-journal")
                return RecoverJournal(options);
            if (options.Command == "rename")
                return RenameDirectory(options);
            if (options.Command == "commit-journal")
                return CommitJournal(options);
            if (options.Command == "remove-journal")
                return RemoveJournal(options);
            if (options.Command == "quarantine-directory")
                return QuarantineDirectory(options);
            if (options.Command == "remove-quarantined-directory")
                return RemoveQuarantinedDirectory(options);
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
        ReconcileJournalTransaction(Path.GetDirectoryName(target), target);
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

    private static int RecoverJournal(Options options)
    {
        string parent = RequireTrustedParent(options.Require("parent"));
        string target = ChildPath(parent, options.Require("target"));
        ReconcileJournalTransaction(parent, target);
        EmitSuccess("journal-recovered");
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
        ReconcileJournalTransaction(parent, target);
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
        string receipt = JournalTransaction.ReceiptPath(parent, Path.GetFileName(target));
        using (PinnedEntry parentEntry = RequireMutationPinned(parent, EntryKind.Directory, true))
        using (PinnedEntry temporaryEntry = OpenJournalMutationPinned(temporary, false, true))
        {
            string actualSha256 = HashAndFlush(temporaryEntry);
            if (!String.Equals(actualSha256, expectedSha256, StringComparison.Ordinal))
                throw new SourceFsException("CONTENT_MISMATCH", 4);

            PinnedEntry prior = null;
            PinnedEntry previousEntry = null;
            PinnedEntry receiptEntry = null;
            try
            {
                prior = OpenExpectedJournalEntry(target, expectedTarget);
                previousEntry = OpenExpectedJournalEntry(previous, expectedPrevious);
                receiptEntry = CreateJournalTransactionReceipt(
                    parentEntry,
                    receipt,
                    Path.GetFileName(target),
                    Path.GetFileName(temporary),
                    expectedTarget,
                    temporaryEntry,
                    expectedSha256);
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
                DeletePinnedEntry(receiptEntry, parentEntry, receipt);
                receiptEntry = null;
            }
            finally
            {
                if (prior != null)
                    prior.Dispose();
                if (previousEntry != null)
                    previousEntry.Dispose();
                if (receiptEntry != null)
                    receiptEntry.Dispose();
            }
        }
        EmitSuccess("journal-committed");
        return 0;
    }

    private static int RemoveJournal(Options options)
    {
        string parent = RequireTrustedParent(options.Require("parent"));
        string target = ChildPath(parent, options.Require("target"));
        ReconcileJournalTransaction(parent, target);
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
        RequireManagedQuarantineName(Path.GetFileName(quarantine));
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

    private static int RemoveQuarantinedDirectory(Options options)
    {
        string parent = RequireTrustedParent(options.Require("parent"));
        string quarantine = ChildPath(parent, options.Require("quarantine"));
        RequireManagedQuarantineName(Path.GetFileName(quarantine));
        string expected = RequireIdentity(options.Require("expected"));

        using (PinnedEntry parentEntry = RequireMutationPinned(parent, EntryKind.Directory, true))
        {
            PinnedEntry quarantineEntry = OpenPinnedCore(
                quarantine,
                EntryKind.Directory,
                false,
                true,
                true,
                false,
                false);
            try
            {
                RequireExpected(quarantineEntry, expected);
                RequireDirectChild(parentEntry, quarantineEntry);
                int reclaimedEntries = 0;
                RemovePinnedDirectoryContents(
                    quarantineEntry,
                    quarantineEntry.CanonicalPath,
                    0,
                    ref reclaimedEntries);
                MarkTreeEntryDelete(quarantineEntry);
            }
            finally
            {
                quarantineEntry.Dispose();
            }
            FlushPinnedDirectory(parentEntry);
            RequireAbsent(quarantine);
        }
        EmitSuccess("removed");
        return 0;
    }

    private static void RequireManagedQuarantineName(string name)
    {
        if (!ManagedQuarantineName.IsMatch(name))
            throw new SourceFsException("INVALID_QUARANTINE_NAME", 2);
    }

    private static void RemovePinnedDirectoryContents(
        PinnedEntry directory,
        string canonicalRoot,
        int depth,
        ref int reclaimedEntries)
    {
        if (!directory.IsDirectory || directory.IsReparsePoint)
            throw new SourceFsException("UNEXPECTED_ENTRY_TYPE", 4);
        if (depth > MAX_RECLAMATION_DEPTH)
            throw new SourceFsException("RECLAMATION_BUDGET_EXCEEDED", 4);

        ChildCapture capture = CaptureChildren(
            directory,
            canonicalRoot,
            MAX_RECLAMATION_ENTRIES - reclaimedEntries);
        reclaimedEntries += capture.ObservedEntries;
        foreach (ChildEvidence evidence in capture.Children)
        {
            string childPath = ChildPath(directory.CanonicalPath, evidence.Name);
            PinnedEntry child = OpenPinnedCore(
                childPath,
                null,
                true,
                evidence.IsDirectory && !evidence.IsReparsePoint,
                true,
                true,
                false);
            if (child == null)
                continue;
            try
            {
                RequireExpected(child, evidence.Identity);
                RequireDirectChild(directory, child);
                RequireWithinCanonicalRoot(canonicalRoot, child.CanonicalPath);
                if (
                    child.IsDirectory != evidence.IsDirectory ||
                    child.IsReparsePoint != evidence.IsReparsePoint)
                {
                    throw new SourceFsException("DIRECTORY_CHANGED", 4);
                }
                if (child.IsDirectory && !child.IsReparsePoint)
                    RemovePinnedDirectoryContents(child, canonicalRoot, depth + 1, ref reclaimedEntries);
                MarkTreeEntryDelete(child);
            }
            finally
            {
                child.Dispose();
            }
            FlushPinnedDirectory(directory);
            RequireAbsent(childPath);
        }
        if (CaptureChildren(
                directory,
                canonicalRoot,
                Math.Min(1, MAX_RECLAMATION_ENTRIES - reclaimedEntries)).ObservedEntries != 0)
            throw new SourceFsException("DIRECTORY_CHANGED", 4);
    }

    private static ChildCapture CaptureChildren(
        PinnedEntry directory,
        string canonicalRoot,
        int remainingEntryBudget)
    {
        if (remainingEntryBudget < 0)
            throw new SourceFsException("RECLAMATION_BUDGET_EXCEEDED", 4);
        List<ChildEvidence> children = new List<ChildEvidence>();
        int observedEntries = 0;
        WIN32_FIND_DATA data;
        IntPtr search = FindFirstFileW(
            ToExtendedPath(Path.Combine(directory.CanonicalPath, "*")),
            out data);
        if (search == InvalidHandle)
        {
            int native = Marshal.GetLastWin32Error();
            if (native == ERROR_FILE_NOT_FOUND)
                return new ChildCapture(children, observedEntries);
            throw NativeError("FindFirstFileW", native);
        }
        try
        {
            for (;;)
            {
                string name = data.cFileName;
                if (name != "." && name != "..")
                {
                    if (observedEntries >= remainingEntryBudget)
                        throw new SourceFsException("RECLAMATION_BUDGET_EXCEEDED", 4);
                    observedEntries++;
                    ValidateEntryName(name);
                    string childPath = ChildPath(directory.CanonicalPath, name);
                    using (PinnedEntry child = OpenPinnedCore(
                        childPath,
                        null,
                        true,
                        false,
                        false,
                        true,
                        true))
                    {
                        if (child != null)
                        {
                            RequireDirectChild(directory, child);
                            RequireWithinCanonicalRoot(canonicalRoot, child.CanonicalPath);
                            children.Add(new ChildEvidence(
                                name,
                                child.Identity,
                                child.IsDirectory,
                                child.IsReparsePoint));
                        }
                    }
                }
                if (FindNextFileW(search, out data))
                    continue;
                int native = Marshal.GetLastWin32Error();
                if (native != ERROR_NO_MORE_FILES)
                    throw NativeError("FindNextFileW", native);
                break;
            }
        }
        finally
        {
            FindClose(search);
        }
        children.Sort((left, right) =>
            StringComparer.OrdinalIgnoreCase.Compare(left.Name, right.Name));
        return new ChildCapture(children, observedEntries);
    }

    private static void RequireDirectChild(PinnedEntry parent, PinnedEntry child)
    {
        if (!String.Equals(
                Path.GetDirectoryName(child.CanonicalPath),
                parent.CanonicalPath,
                StringComparison.OrdinalIgnoreCase))
        {
            throw new SourceFsException("PATH_ESCAPE", 4);
        }
    }

    private static void RequireWithinCanonicalRoot(string root, string child)
    {
        string prefix = root.EndsWith("\\", StringComparison.Ordinal) ? root : root + "\\";
        if (!child.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            throw new SourceFsException("PATH_ESCAPE", 4);
    }

    private static void ReconcileJournalTransaction(string suppliedParent, string suppliedTarget)
    {
        string parent = RequireTrustedParent(suppliedParent);
        string target = NormaliseAbsolutePath(suppliedTarget);
        string targetName = Path.GetFileName(target);
        if (!String.Equals(target, ChildPath(parent, targetName), StringComparison.OrdinalIgnoreCase))
            throw new SourceFsException("PATH_ESCAPE", 2);
        string previous = ChildPath(parent, targetName + ".previous");
        string receipt = JournalTransaction.ReceiptPath(parent, targetName);

        using (PinnedEntry parentEntry = RequireMutationPinned(parent, EntryKind.Directory, true))
        {
            PinnedEntry receiptEntry = null;
            PinnedEntry targetEntry = null;
            PinnedEntry previousEntry = null;
            PinnedEntry temporaryEntry = null;
            try
            {
                receiptEntry = OpenJournalMutationPinned(receipt, true, false);
                if (receiptEntry == null)
                {
                    previousEntry = OpenJournalMutationPinned(previous, true, false);
                    if (previousEntry != null)
                        throw new SourceFsException("RESERVED_SIDECAR_OCCUPIED", 4);
                    return;
                }

                JournalTransaction transaction = JournalTransaction.Parse(ReadPinnedText(receiptEntry));
                if (!String.Equals(transaction.TargetName, targetName, StringComparison.Ordinal))
                    throw new SourceFsException("INVALID_TRANSACTION_RECEIPT", 4);
                string temporary = ChildPath(parent, transaction.TemporaryName);
                if (
                    String.Equals(temporary, target, StringComparison.OrdinalIgnoreCase) ||
                    String.Equals(temporary, previous, StringComparison.OrdinalIgnoreCase) ||
                    String.Equals(temporary, receipt, StringComparison.OrdinalIgnoreCase))
                {
                    throw new SourceFsException("INVALID_TRANSACTION_RECEIPT", 4);
                }

                targetEntry = OpenJournalMutationPinned(target, true, false);
                previousEntry = OpenJournalMutationPinned(previous, true, false);
                temporaryEntry = OpenJournalMutationPinned(temporary, true, false);

                bool targetIsPrior = MatchesJournalEntry(targetEntry, transaction.Target);
                bool targetIsReplacement = MatchesJournalEntry(targetEntry, transaction.Replacement);
                bool previousIsPrior = MatchesJournalEntry(previousEntry, transaction.Target);
                bool temporaryIsReplacement = MatchesJournalEntry(temporaryEntry, transaction.Replacement);
                if (
                    (targetEntry != null && !targetIsPrior && !targetIsReplacement) ||
                    (previousEntry != null && !previousIsPrior) ||
                    (temporaryEntry != null && !temporaryIsReplacement) ||
                    (targetIsPrior && targetIsReplacement))
                {
                    throw new SourceFsException("AMBIGUOUS_EVIDENCE", 4);
                }

                if (targetIsReplacement)
                {
                    if (temporaryEntry != null)
                        throw new SourceFsException("AMBIGUOUS_EVIDENCE", 4);
                    if (previousEntry != null)
                    {
                        DeletePinnedEntry(previousEntry, parentEntry, previous);
                        previousEntry = null;
                    }
                    DeletePinnedEntry(receiptEntry, parentEntry, receipt);
                    receiptEntry = null;
                    return;
                }

                if (targetIsPrior)
                {
                    if (previousEntry != null)
                        throw new SourceFsException("AMBIGUOUS_EVIDENCE", 4);
                    if (temporaryEntry == null)
                    {
                        DeletePinnedEntry(receiptEntry, parentEntry, receipt);
                        receiptEntry = null;
                        return;
                    }
                    RenamePinned(targetEntry, parentEntry, Path.GetFileName(previous));
                    FlushPinnedDirectory(parentEntry);
                    RequireAbsent(target);
                    previousEntry = targetEntry;
                    targetEntry = null;
                }

                if (targetEntry != null)
                    throw new SourceFsException("AMBIGUOUS_EVIDENCE", 4);
                if (temporaryEntry == null)
                {
                    if (previousEntry == null)
                        throw new SourceFsException("AMBIGUOUS_EVIDENCE", 4);
                    RenamePinned(previousEntry, parentEntry, targetName);
                    FlushPinnedDirectory(parentEntry);
                    RequireAbsent(previous);
                    targetEntry = previousEntry;
                    previousEntry = null;
                    RequireExpectedJournalState(target, transaction.Target);
                    DeletePinnedEntry(receiptEntry, parentEntry, receipt);
                    receiptEntry = null;
                    return;
                }
                if (!transaction.Target.IsMissing && previousEntry == null)
                    throw new SourceFsException("AMBIGUOUS_EVIDENCE", 4);

                RenamePinned(temporaryEntry, parentEntry, targetName);
                FlushPinnedDirectory(parentEntry);
                RequireAbsent(temporary);
                targetEntry = temporaryEntry;
                temporaryEntry = null;
                RequireExpectedJournalState(target, transaction.Replacement);
                if (previousEntry != null)
                {
                    DeletePinnedEntry(previousEntry, parentEntry, previous);
                    previousEntry = null;
                }
                DeletePinnedEntry(receiptEntry, parentEntry, receipt);
                receiptEntry = null;
            }
            finally
            {
                if (receiptEntry != null)
                    receiptEntry.Dispose();
                if (targetEntry != null)
                    targetEntry.Dispose();
                if (previousEntry != null)
                    previousEntry.Dispose();
                if (temporaryEntry != null)
                    temporaryEntry.Dispose();
            }
        }
    }

    private static PinnedEntry CreateJournalTransactionReceipt(
        PinnedEntry parentEntry,
        string receipt,
        string targetName,
        string temporaryName,
        ExpectedJournalEntry expectedTarget,
        PinnedEntry replacement,
        string replacementSha256)
    {
        RequireAbsent(receipt);
        JournalTransaction transaction = new JournalTransaction(
            targetName,
            temporaryName,
            expectedTarget,
            ExpectedJournalEntry.Present(replacement.Identity, replacementSha256));
        string contents = transaction.Canonical();
        string stage = ChildPath(
            Path.GetDirectoryName(receipt),
            Path.GetFileName(receipt) + ".stage-" + Guid.NewGuid().ToString("N"));
        PinnedEntry stageEntry = CreateNewJournalPinned(stage);
        try
        {
            WritePinnedText(stageEntry, contents);
            string stageSha256 = HashOnly(stageEntry);
            RequireAbsent(receipt);
            RenamePinned(stageEntry, parentEntry, Path.GetFileName(receipt));
            FlushPinnedDirectory(parentEntry);
            RequireAbsent(stage);
            using (PinnedEntry committed = RequirePinned(receipt, EntryKind.File))
            {
                RequireExpected(committed, stageEntry.Identity);
                if (!String.Equals(HashOnly(committed), stageSha256, StringComparison.Ordinal))
                    throw new SourceFsException("CONTENT_MISMATCH", 4);
            }
            PinnedEntry result = stageEntry;
            stageEntry = null;
            return result;
        }
        finally
        {
            if (stageEntry != null)
                stageEntry.Dispose();
        }
    }

    private static bool MatchesJournalEntry(PinnedEntry entry, ExpectedJournalEntry expected)
    {
        if (entry == null || expected.IsMissing)
            return false;
        return
            String.Equals(entry.Identity, expected.Identity, StringComparison.Ordinal) &&
            String.Equals(HashOnly(entry), expected.Sha256, StringComparison.Ordinal);
    }

    private static void DeletePinnedEntry(PinnedEntry entry, PinnedEntry parentEntry, string path)
    {
        RequireExpectedJournalState(path, ExpectedJournalEntry.Present(entry.Identity, HashOnly(entry)));
        MarkDelete(entry);
        entry.Dispose();
        FlushPinnedDirectory(parentEntry);
        RequireAbsent(path);
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
            PinnedEntry result = new PinnedEntry(
                handle,
                canonical,
                exactIdentity,
                directory,
                reparse);
            handle = InvalidHandle;
            return result;
        }
        finally
        {
            if (handle != InvalidHandle)
                CloseHandle(handle);
        }
    }

    private static PinnedEntry CreateNewJournalPinned(string supplied)
    {
        string path = NormaliseAbsolutePath(supplied);
        IntPtr handle = CreateFileW(
            ToExtendedPath(path),
            FILE_READ_ATTRIBUTES | GENERIC_READ | GENERIC_WRITE | DELETE | SYNCHRONIZE,
            FILE_SHARE_READ,
            IntPtr.Zero,
            CREATE_NEW,
            FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
            IntPtr.Zero);
        if (handle == InvalidHandle)
            throw NativeError("CreateFileW(transaction receipt)");
        try
        {
            BY_HANDLE_FILE_INFORMATION basic;
            if (!GetFileInformationByHandle(handle, out basic))
                throw NativeError("GetFileInformationByHandle");
            if ((basic.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0 ||
                (basic.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0)
            {
                throw new SourceFsException("UNEXPECTED_ENTRY_TYPE", 4);
            }
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
            PinnedEntry result = new PinnedEntry(
                handle,
                canonical,
                FormatIdentity(identity),
                false,
                false);
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

    private static void MarkTreeEntryDelete(PinnedEntry entry)
    {
        IntPtr information = Marshal.AllocHGlobal(4);
        try
        {
            Marshal.WriteInt32(
                information,
                unchecked((int)(FILE_DISPOSITION_FLAG_DELETE | FILE_DISPOSITION_FLAG_IGNORE_READONLY_ATTRIBUTE)));
            if (!SetFileInformationByHandle(
                    entry.Handle,
                    FILE_DISPOSITION_INFO_EX_CLASS,
                    information,
                    4))
            {
                int native = Marshal.GetLastWin32Error();
                if (native == ERROR_INVALID_PARAMETER)
                {
                    MarkDelete(entry);
                    return;
                }
                throw NativeError("SetFileInformationByHandle(FileDispositionInfoEx)", native);
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

    private static string ReadPinnedText(PinnedEntry entry)
    {
        SafeFileHandle safe = new SafeFileHandle(entry.Handle, false);
        using (FileStream stream = new FileStream(safe, FileAccess.Read, 4096, false))
        {
            if (stream.Length < 0 || stream.Length > MAX_JOURNAL_TRANSACTION_BYTES)
                throw new SourceFsException("INVALID_TRANSACTION_RECEIPT", 4);
            byte[] bytes = new byte[(int)stream.Length];
            int offset = 0;
            while (offset < bytes.Length)
            {
                int read = stream.Read(bytes, offset, bytes.Length - offset);
                if (read == 0)
                    throw new SourceFsException("INVALID_TRANSACTION_RECEIPT", 4);
                offset += read;
            }
            for (int index = 0; index < bytes.Length; index++)
            {
                byte current = bytes[index];
                if (current != 0x0a && (current < 0x20 || current > 0x7e))
                    throw new SourceFsException("INVALID_TRANSACTION_RECEIPT", 4);
            }
            return Encoding.ASCII.GetString(bytes);
        }
    }

    private static void WritePinnedText(PinnedEntry entry, string contents)
    {
        byte[] bytes = Encoding.ASCII.GetBytes(contents);
        if (bytes.Length == 0 || bytes.Length > MAX_JOURNAL_TRANSACTION_BYTES)
            throw new SourceFsException("INVALID_TRANSACTION_RECEIPT", 4);
        SafeFileHandle safe = new SafeFileHandle(entry.Handle, false);
        using (FileStream stream = new FileStream(safe, FileAccess.ReadWrite, 4096, false))
        {
            stream.SetLength(0);
            stream.Write(bytes, 0, bytes.Length);
            stream.Flush();
        }
        if (!FlushFileBuffers(entry.Handle))
            throw NativeError("FlushFileBuffers(transaction receipt)");
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

        internal static ExpectedJournalEntry Present(string identity, string sha256)
        {
            return new ExpectedJournalEntry(
                false,
                RequireIdentity(identity),
                RequireSha256(sha256));
        }
    }

    private sealed class JournalTransaction
    {
        private const string Header = "flinttrade-windows-journal-transaction-v1";

        internal readonly string TargetName;
        internal readonly string TemporaryName;
        internal readonly ExpectedJournalEntry Target;
        internal readonly ExpectedJournalEntry Replacement;

        internal JournalTransaction(
            string targetName,
            string temporaryName,
            ExpectedJournalEntry target,
            ExpectedJournalEntry replacement)
        {
            this.TargetName = RequireTransactionEntryName(targetName);
            this.TemporaryName = RequireTransactionEntryName(temporaryName);
            this.Target = target;
            if (replacement.IsMissing)
                throw new SourceFsException("INVALID_TRANSACTION_RECEIPT", 4);
            this.Replacement = replacement;
        }

        internal static string ReceiptPath(string parent, string targetName)
        {
            return ChildPath(parent, RequireTransactionEntryName(targetName) + ".transaction");
        }

        internal string Canonical()
        {
            return
                Header + "\n" +
                "target=" + this.TargetName + "\n" +
                "temporary=" + this.TemporaryName + "\n" +
                "target-identity=" + (this.Target.IsMissing ? "missing" : this.Target.Identity) + "\n" +
                "target-sha256=" + (this.Target.IsMissing ? "missing" : this.Target.Sha256) + "\n" +
                "replacement-identity=" + this.Replacement.Identity + "\n" +
                "replacement-sha256=" + this.Replacement.Sha256 + "\n";
        }

        internal static JournalTransaction Parse(string contents)
        {
            if (contents == null || contents.Length > MAX_JOURNAL_TRANSACTION_BYTES)
                throw new SourceFsException("INVALID_TRANSACTION_RECEIPT", 4);
            string[] lines = contents.Split(new char[] { '\n' });
            if (lines.Length != 8 || lines[0] != Header || lines[7] != "")
                throw new SourceFsException("INVALID_TRANSACTION_RECEIPT", 4);
            string targetName = ReceiptValue(lines[1], "target=");
            string temporaryName = ReceiptValue(lines[2], "temporary=");
            ExpectedJournalEntry target = ExpectedJournalEntry.Parse(
                ReceiptValue(lines[3], "target-identity="),
                ReceiptValue(lines[4], "target-sha256="));
            ExpectedJournalEntry replacement = ExpectedJournalEntry.Parse(
                ReceiptValue(lines[5], "replacement-identity="),
                ReceiptValue(lines[6], "replacement-sha256="));
            if (replacement.IsMissing)
                throw new SourceFsException("INVALID_TRANSACTION_RECEIPT", 4);
            JournalTransaction result = new JournalTransaction(targetName, temporaryName, target, replacement);
            if (!String.Equals(result.Canonical(), contents, StringComparison.Ordinal))
                throw new SourceFsException("INVALID_TRANSACTION_RECEIPT", 4);
            return result;
        }

        private static string ReceiptValue(string line, string prefix)
        {
            if (line == null || !line.StartsWith(prefix, StringComparison.Ordinal))
                throw new SourceFsException("INVALID_TRANSACTION_RECEIPT", 4);
            string value = line.Substring(prefix.Length);
            if (value.Length == 0 || value.IndexOf('=') >= 0)
                throw new SourceFsException("INVALID_TRANSACTION_RECEIPT", 4);
            return value;
        }

        private static string RequireTransactionEntryName(string value)
        {
            ValidateEntryName(value);
            for (int index = 0; index < value.Length; index++)
            {
                char current = value[index];
                if (current < 0x21 || current > 0x7e || current == '=')
                    throw new SourceFsException("INVALID_TRANSACTION_RECEIPT", 4);
            }
            return value;
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

    private sealed class ChildEvidence
    {
        internal readonly string Identity;
        internal readonly bool IsDirectory;
        internal readonly bool IsReparsePoint;
        internal readonly string Name;

        internal ChildEvidence(
            string name,
            string identity,
            bool isDirectory,
            bool isReparsePoint)
        {
            this.Name = name;
            this.Identity = identity;
            this.IsDirectory = isDirectory;
            this.IsReparsePoint = isReparsePoint;
        }
    }

    private sealed class ChildCapture
    {
        internal readonly List<ChildEvidence> Children;
        internal readonly int ObservedEntries;

        internal ChildCapture(List<ChildEvidence> children, int observedEntries)
        {
            this.Children = children;
            this.ObservedEntries = observedEntries;
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
            if (command == "recover-journal" && values.Count == 2 &&
                values.ContainsKey("parent") && values.ContainsKey("target"))
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
            if (command == "remove-quarantined-directory" && values.Count == 3 &&
                values.ContainsKey("parent") && values.ContainsKey("quarantine") &&
                values.ContainsKey("expected"))
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

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct WIN32_FIND_DATA
    {
        internal uint dwFileAttributes;
        internal FILETIME ftCreationTime;
        internal FILETIME ftLastAccessTime;
        internal FILETIME ftLastWriteTime;
        internal uint nFileSizeHigh;
        internal uint nFileSizeLow;
        internal uint dwReserved0;
        internal uint dwReserved1;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
        internal string cFileName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 14)]
        internal string cAlternateFileName;
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

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr FindFirstFileW(
        string fileName,
        out WIN32_FIND_DATA findFileData);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool FindNextFileW(
        IntPtr findFile,
        out WIN32_FIND_DATA findFileData);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool FindClose(IntPtr findFile);

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
