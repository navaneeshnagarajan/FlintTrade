using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using Microsoft.Win32.SafeHandles;

internal static class Program
{
    private const uint CREATE_SUSPENDED = 0x00000004;
    private const uint CREATE_NO_WINDOW = 0x08000000;
    private const uint EXTENDED_STARTUPINFO_PRESENT = 0x00080000;
    private const uint STARTF_USESTDHANDLES = 0x00000100;

    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    private const int JobObjectBasicAccountingInformation = 1;
    private const int JobObjectExtendedLimitInformation = 9;

    private const uint SYNCHRONIZE = 0x00100000;
    private const uint WAIT_OBJECT_0 = 0;
    private const uint WAIT_TIMEOUT = 258;
    private const uint WAIT_FAILED = 0xffffffff;
    private const uint INFINITE = 0xffffffff;

    private const int STD_OUTPUT_HANDLE = -11;
    private const int STD_ERROR_HANDLE = -12;
    private const uint DUPLICATE_SAME_ACCESS = 0x00000002;

    private const uint GENERIC_READ = 0x80000000;
    private const uint FILE_SHARE_READ = 0x00000001;
    private const uint FILE_SHARE_WRITE = 0x00000002;
    private const uint OPEN_EXISTING = 3;
    private const uint FILE_ATTRIBUTE_NORMAL = 0x00000080;
    private const uint FILE_ATTRIBUTE_DIRECTORY = 0x00000010;
    private const uint FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400;
    private const uint FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000;

    private static readonly IntPtr InvalidHandle = new IntPtr(-1);
    private static readonly IntPtr ProcThreadAttributeHandleList = new IntPtr(0x00020002);

    private static int Main(string[] args)
    {
        try
        {
            return Run(Options.Parse(args));
        }
        catch (Exception error)
        {
            Win32Exception native = error as Win32Exception;
            Console.Error.WriteLine(
                "Windows Job supervisor failed before launch{0}.",
                native == null
                    ? String.Empty
                    : " with Win32 error " + native.NativeErrorCode.ToString(CultureInfo.InvariantCulture));
            return 127;
        }
    }

    private static int Run(Options options)
    {
        IntPtr job = IntPtr.Zero;
        IntPtr parent = IntPtr.Zero;
        IntPtr startEvent = IntPtr.Zero;
        IntPtr controlEvent = IntPtr.Zero;
        IntPtr releaseEvent = IntPtr.Zero;
        IntPtr process = IntPtr.Zero;
        IntPtr primaryThread = IntPtr.Zero;
        bool assigned = false;

        try
        {
            startEvent = CreateEventW(IntPtr.Zero, true, false, null);
            RequireHandle(startEvent, "CreateEventW(start)");
            controlEvent = CreateEventW(IntPtr.Zero, true, false, null);
            RequireHandle(controlEvent, "CreateEventW");
            releaseEvent = CreateEventW(IntPtr.Zero, true, false, null);
            RequireHandle(releaseEvent, "CreateEventW(release)");

            ControlState control = new ControlState(startEvent, controlEvent, releaseEvent);
            StartControlReader(control, options.Token);

            parent = OpenProcess(SYNCHRONIZE, false, options.ParentPid);
            RequireHandle(parent, "OpenProcess(parent)");

            job = CreateJobObjectW(IntPtr.Zero, null);
            RequireHandle(job, "CreateJobObjectW");
            EnableKillOnClose(job);

            IntPtr[] startWaits = { parent, controlEvent, startEvent };
            uint startResult = WaitForMultipleObjects(
                (uint)startWaits.Length,
                startWaits,
                false,
                INFINITE);
            if (startResult == WAIT_FAILED)
                throw NativeError("WaitForMultipleObjects(start)");
            if (startResult == WAIT_OBJECT_0)
                return 130;
            if (startResult == WAIT_OBJECT_0 + 1)
            {
                string reason = control.Reason ?? "control-error";
                int result = ExitCodeForReason(reason, 1);
                WriteSettled(options, reason, 1);
                WaitForReleaseOrParent(parent, releaseEvent);
                return result;
            }
            if (startResult != WAIT_OBJECT_0 + 2)
                throw new InvalidOperationException("Unexpected supervisor start wait result.");

            PROCESS_INFORMATION created = CreateSuspendedTarget(options);
            process = created.hProcess;
            primaryThread = created.hThread;

            if (!AssignProcessToJobObject(job, process))
                throw NativeError("AssignProcessToJobObject");
            assigned = true;

            // Close the launch race while the target is still suspended.
            if (WaitForSingleObject(parent, 0) == WAIT_OBJECT_0)
            {
                int result = StopOwnedJob(options, job, process, "parent-lost");
                WaitForReleaseOrParent(parent, releaseEvent);
                return result;
            }

            if (WaitForSingleObject(controlEvent, 0) == WAIT_OBJECT_0)
            {
                int result = StopOwnedJob(options, job, process, control.Reason ?? "control-error");
                WaitForReleaseOrParent(parent, releaseEvent);
                return result;
            }

            uint previousSuspendCount = ResumeThread(primaryThread);
            if (previousSuspendCount == UInt32.MaxValue)
                throw NativeError("ResumeThread");

            CloseOwnedHandle(ref primaryThread);

            // Lowest-index signalled handle wins, so parent/control outrank a
            // simultaneous leader exit.
            IntPtr[] waits = { parent, controlEvent, process };
            uint waitResult = WaitForMultipleObjects(
                (uint)waits.Length,
                waits,
                false,
                INFINITE);

            if (waitResult == WAIT_FAILED)
                throw NativeError("WaitForMultipleObjects");

            if (waitResult == WAIT_OBJECT_0)
            {
                int result = StopOwnedJob(options, job, process, "parent-lost");
                WaitForReleaseOrParent(parent, releaseEvent);
                return result;
            }

            if (waitResult == WAIT_OBJECT_0 + 1)
            {
                int result = StopOwnedJob(options, job, process, control.Reason ?? "control-error");
                WaitForReleaseOrParent(parent, releaseEvent);
                return result;
            }

            if (waitResult != WAIT_OBJECT_0 + 2)
                throw new InvalidOperationException("Unexpected supervisor wait result.");

            uint leaderExit = ReadExitCode(process);
            uint activeProcesses = QueryActiveProcesses(job);

            if (activeProcesses != 0)
            {
                TerminateAndProveEmpty(job);
                WriteSettled(options, "orphan-drained", leaderExit);
                WaitForReleaseOrParent(parent, releaseEvent);
                return leaderExit == 0 ? 1 : unchecked((int)leaderExit);
            }

            WriteSettled(options, "natural", leaderExit);
            WaitForReleaseOrParent(parent, releaseEvent);
            return unchecked((int)leaderExit);
        }
        catch (Exception error)
        {
            bool contained = TryRollback(job, process, assigned);

            Win32Exception native = error as Win32Exception;
            Console.Error.WriteLine(
                "Windows Job supervisor setup/settlement failed{0}.",
                native == null
                    ? String.Empty
                    : " with Win32 error " + native.NativeErrorCode.ToString(CultureInfo.InvariantCulture));

            if (contained)
            {
                WriteSettled(options, "setup-failed", 127);
                if (parent != IntPtr.Zero && releaseEvent != IntPtr.Zero)
                    WaitForReleaseOrParent(parent, releaseEvent);
            }

            // No settled sentinel means the TypeScript caller must return
            // contained:false.
            return contained ? 127 : 125;
        }
        finally
        {
            CloseOwnedHandle(ref primaryThread);
            CloseOwnedHandle(ref process);
            CloseOwnedHandle(ref parent);
            CloseOwnedHandle(ref startEvent);
            CloseOwnedHandle(ref controlEvent);
            CloseOwnedHandle(ref releaseEvent);

            // This is the kill-on-close backstop. The handle is deliberately
            // non-inheritable, so only this supervisor owns it.
            CloseOwnedHandle(ref job);
        }
    }

    private static void WaitForReleaseOrParent(
        IntPtr parent,
        IntPtr releaseEvent)
    {
        IntPtr[] waits = { parent, releaseEvent };
        uint result = WaitForMultipleObjects(
            (uint)waits.Length,
            waits,
            false,
            INFINITE);
        if (result == WAIT_FAILED)
            throw NativeError("WaitForMultipleObjects(release)");
        if (result != WAIT_OBJECT_0 && result != WAIT_OBJECT_0 + 1)
            throw new InvalidOperationException("Unexpected supervisor release wait result.");
    }

    private static int ExitCodeForReason(string reason, uint leaderExit)
    {
        if (reason == "timeout")
            return 124;
        if (reason == "cancel" || reason == "shutdown" || reason == "parent-lost")
            return 130;
        if (reason == "listener" || reason == "control-error")
            return 1;
        return unchecked((int)leaderExit);
    }

    private static int StopOwnedJob(
        Options options,
        IntPtr job,
        IntPtr process,
        string reason)
    {
        TerminateAndProveEmpty(job);

        uint leaderExit = 1;
        if (WaitForSingleObject(process, 5000) == WAIT_OBJECT_0)
            leaderExit = ReadExitCode(process);

        WriteSettled(options, reason, leaderExit);

        if (reason == "timeout")
            return 124;
        if (reason == "listener" || reason == "control-error")
            return 1;

        return 130;
    }

    private static void TerminateAndProveEmpty(IntPtr job)
    {
        if (!TerminateJobObject(job, 1) && QueryActiveProcesses(job) != 0)
            throw NativeError("TerminateJobObject");

        if (!WaitForJobEmpty(job, 5000))
            throw new InvalidOperationException(
                "Windows Job remained active after termination.");
    }

    private static bool TryRollback(
        IntPtr job,
        IntPtr process,
        bool assigned)
    {
        try
        {
            if (process == IntPtr.Zero)
                return job == IntPtr.Zero || QueryActiveProcesses(job) == 0;

            if (assigned)
            {
                if (!TerminateJobObject(job, 1) && QueryActiveProcesses(job) != 0)
                    return false;
                return WaitForJobEmpty(job, 5000);
            }

            uint processWait = WaitForSingleObject(process, 0);
            if (processWait == WAIT_TIMEOUT && !TerminateProcess(process, 1))
                return false;

            return WaitForSingleObject(process, 5000) == WAIT_OBJECT_0;
        }
        catch
        {
            return false;
        }
    }

    private static void EnableKillOnClose(IntPtr job)
    {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits =
            new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();

        limits.BasicLimitInformation.LimitFlags =
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

        if (!SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                ref limits,
                (uint)Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION))))
        {
            throw NativeError("SetInformationJobObject");
        }
    }

    private static uint QueryActiveProcesses(IntPtr job)
    {
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting =
            new JOBOBJECT_BASIC_ACCOUNTING_INFORMATION();

        if (!QueryInformationJobObject(
                job,
                JobObjectBasicAccountingInformation,
                ref accounting,
                (uint)Marshal.SizeOf(typeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)),
                IntPtr.Zero))
        {
            throw NativeError("QueryInformationJobObject");
        }

        return accounting.ActiveProcesses;
    }

    private static bool WaitForJobEmpty(IntPtr job, int timeoutMilliseconds)
    {
        Stopwatch elapsed = Stopwatch.StartNew();

        while (true)
        {
            if (QueryActiveProcesses(job) == 0)
                return true;

            if (elapsed.ElapsedMilliseconds >= timeoutMilliseconds)
                return false;

            Thread.Sleep(20);
        }
    }

    private static uint ReadExitCode(IntPtr process)
    {
        uint exitCode;
        if (!GetExitCodeProcess(process, out exitCode))
            throw NativeError("GetExitCodeProcess");
        return exitCode;
    }

    private static PROCESS_INFORMATION CreateSuspendedTarget(Options options)
    {
        IntPtr targetLock = IntPtr.Zero;
        IntPtr childInput = IntPtr.Zero;
        IntPtr childOutput = IntPtr.Zero;
        IntPtr childError = IntPtr.Zero;
        IntPtr attributeList = IntPtr.Zero;
        IntPtr attributeHandles = IntPtr.Zero;
        bool attributeListInitialised = false;

        try
        {
            targetLock = OpenAndVerifyTarget(options);
            SECURITY_ATTRIBUTES inheritable = new SECURITY_ATTRIBUTES();
            inheritable.nLength = Marshal.SizeOf(typeof(SECURITY_ATTRIBUTES));
            inheritable.bInheritHandle = 1;

            childInput = CreateFileW(
                "NUL",
                GENERIC_READ,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                ref inheritable,
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                IntPtr.Zero);
            RequireHandle(childInput, "CreateFileW(NUL)");

            childOutput = DuplicateInheritableStandardHandle(STD_OUTPUT_HANDLE);
            childError = DuplicateInheritableStandardHandle(STD_ERROR_HANDLE);

            IntPtr attributeBytes = IntPtr.Zero;
            InitializeProcThreadAttributeList(
                IntPtr.Zero,
                1,
                0,
                ref attributeBytes);

            if (attributeBytes == IntPtr.Zero)
                throw NativeError("InitializeProcThreadAttributeList(size)");

            attributeList = Marshal.AllocHGlobal(attributeBytes);
            if (!InitializeProcThreadAttributeList(
                    attributeList,
                    1,
                    0,
                    ref attributeBytes))
            {
                throw NativeError("InitializeProcThreadAttributeList");
            }
            attributeListInitialised = true;

            attributeHandles = Marshal.AllocHGlobal(IntPtr.Size * 3);
            Marshal.WriteIntPtr(attributeHandles, 0, childInput);
            Marshal.WriteIntPtr(attributeHandles, IntPtr.Size, childOutput);
            Marshal.WriteIntPtr(attributeHandles, IntPtr.Size * 2, childError);

            if (!UpdateProcThreadAttribute(
                    attributeList,
                    0,
                    ProcThreadAttributeHandleList,
                    attributeHandles,
                    new IntPtr(IntPtr.Size * 3),
                    IntPtr.Zero,
                    IntPtr.Zero))
            {
                throw NativeError("UpdateProcThreadAttribute(handle-list)");
            }

            STARTUPINFOEX startup = new STARTUPINFOEX();
            startup.StartupInfo.cb =
                Marshal.SizeOf(typeof(STARTUPINFOEX));
            startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
            startup.StartupInfo.hStdInput = childInput;
            startup.StartupInfo.hStdOutput = childOutput;
            startup.StartupInfo.hStdError = childError;
            startup.lpAttributeList = attributeList;

            PROCESS_INFORMATION processInformation;
            StringBuilder commandLine =
                new StringBuilder(BuildCommandLine(
                    options.Target,
                    options.TargetArguments));

            uint flags =
                CREATE_SUSPENDED |
                CREATE_NO_WINDOW |
                EXTENDED_STARTUPINFO_PRESENT;

            if (!CreateProcessW(
                    options.Target,
                    commandLine,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    true,
                    flags,
                    IntPtr.Zero,
                    options.WorkingDirectory,
                    ref startup,
                    out processInformation))
            {
                throw NativeError("CreateProcessW");
            }

            return processInformation;
        }
        finally
        {
            if (attributeListInitialised)
                DeleteProcThreadAttributeList(attributeList);
            if (attributeHandles != IntPtr.Zero)
                Marshal.FreeHGlobal(attributeHandles);
            if (attributeList != IntPtr.Zero)
                Marshal.FreeHGlobal(attributeList);

            CloseOwnedHandle(ref childInput);
            CloseOwnedHandle(ref childOutput);
            CloseOwnedHandle(ref childError);
            CloseOwnedHandle(ref targetLock);
        }
    }

    private static IntPtr OpenAndVerifyTarget(Options options)
    {
        SECURITY_ATTRIBUTES attributes = new SECURITY_ATTRIBUTES();
        attributes.nLength = Marshal.SizeOf(typeof(SECURITY_ATTRIBUTES));
        IntPtr handle = CreateFileW(
            options.Target,
            GENERIC_READ,
            FILE_SHARE_READ,
            ref attributes,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT,
            IntPtr.Zero);
        RequireHandle(handle, "CreateFileW(target-lock)");
        try
        {
            BY_HANDLE_FILE_INFORMATION information;
            if (!GetFileInformationByHandle(handle, out information))
                throw NativeError("GetFileInformationByHandle(target-lock)");
            if ((information.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) != 0)
                throw new InvalidOperationException("Target executable must be an exact ordinary file.");
            string canonical = FinalPath(handle);
            if (!String.Equals(canonical, Path.GetFullPath(options.Target), StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Target executable path is aliased.");
            if (options.TargetSha256 != null &&
                !String.Equals(HashHandle(handle), options.TargetSha256, StringComparison.Ordinal))
            {
                throw new InvalidOperationException("Target executable digest does not match the build manifest.");
            }
            IntPtr result = handle;
            handle = IntPtr.Zero;
            return result;
        }
        finally
        {
            CloseOwnedHandle(ref handle);
        }
    }

    private static string FinalPath(IntPtr handle)
    {
        StringBuilder buffer = new StringBuilder(32768);
        uint length = GetFinalPathNameByHandleW(handle, buffer, (uint)buffer.Capacity, 0);
        if (length == 0 || length >= (uint)buffer.Capacity)
            throw NativeError("GetFinalPathNameByHandleW(target-lock)");
        string value = buffer.ToString();
        if (value.StartsWith("\\\\?\\UNC\\", StringComparison.OrdinalIgnoreCase))
            value = "\\\\" + value.Substring(8);
        else if (value.StartsWith("\\\\?\\", StringComparison.OrdinalIgnoreCase))
            value = value.Substring(4);
        return Path.GetFullPath(value);
    }

    private static string HashHandle(IntPtr handle)
    {
        SafeFileHandle safe = new SafeFileHandle(handle, false);
        using (FileStream stream = new FileStream(safe, FileAccess.Read, 65536, false))
        using (SHA256 algorithm = SHA256.Create())
        {
            stream.Position = 0;
            byte[] digest = algorithm.ComputeHash(stream);
            StringBuilder value = new StringBuilder(64);
            for (int index = 0; index < digest.Length; index++)
                value.Append(digest[index].ToString("x2", CultureInfo.InvariantCulture));
            return value.ToString();
        }
    }

    private static IntPtr DuplicateInheritableStandardHandle(int standardHandle)
    {
        IntPtr source = GetStdHandle(standardHandle);
        RequireHandle(source, "GetStdHandle");

        IntPtr duplicate;
        IntPtr current = GetCurrentProcess();

        if (!DuplicateHandle(
                current,
                source,
                current,
                out duplicate,
                0,
                true,
                DUPLICATE_SAME_ACCESS))
        {
            throw NativeError("DuplicateHandle");
        }

        return duplicate;
    }

    private static string BuildCommandLine(
        string target,
        string[] arguments)
    {
        StringBuilder result = new StringBuilder();
        result.Append(QuoteWindowsArgument(target));

        for (int index = 0; index < arguments.Length; index++)
        {
            result.Append(' ');
            result.Append(QuoteWindowsArgument(arguments[index]));
        }

        return result.ToString();
    }

    // Matches the CommandLineToArgvW/MSVC backslash-before-quote convention.
    internal static string QuoteWindowsArgument(string value)
    {
        if (value.Length != 0 &&
            value.IndexOfAny(new[] { ' ', '\t', '\r', '\n', '\v', '"' }) < 0)
        {
            return value;
        }

        StringBuilder quoted = new StringBuilder();
        quoted.Append('"');

        int backslashes = 0;
        for (int index = 0; index < value.Length; index++)
        {
            char current = value[index];

            if (current == '\\')
            {
                backslashes++;
                continue;
            }

            if (current == '"')
            {
                quoted.Append('\\', backslashes * 2 + 1);
                quoted.Append('"');
                backslashes = 0;
                continue;
            }

            quoted.Append('\\', backslashes);
            quoted.Append(current);
            backslashes = 0;
        }

        // Backslashes immediately before the closing quote must be doubled.
        quoted.Append('\\', backslashes * 2);
        quoted.Append('"');
        return quoted.ToString();
    }

    private static void StartControlReader(
        ControlState state,
        string token)
    {
        Thread reader = new Thread(delegate()
        {
            try
            {
                string start = Console.In.ReadLine();
                string[] startFields = start == null ? new string[0] : start.Split('\t');
                if (startFields.Length == 3 &&
                    startFields[0] == "FLINTTRADE_JOB_START" &&
                    startFields[1] == "1" &&
                    startFields[2] == token)
                {
                    state.SignalStart();
                }
                else if (startFields.Length == 4 &&
                    startFields[0] == "FLINTTRADE_JOB_TERMINATE" &&
                    startFields[1] == "1" &&
                    startFields[2] == token &&
                    IsControlReason(startFields[3]))
                {
                    state.Signal(startFields[3]);
                }
                else
                {
                    state.Signal(start == null ? "parent-lost" : "control-error");
                    if (start == null)
                        state.SignalRelease();
                    return;
                }
                while (true)
                {
                    string line = Console.In.ReadLine();
                    if (line == null)
                    {
                        state.Signal("parent-lost");
                        return;
                    }

                    string[] fields = line.Split('\t');
                    if (fields.Length == 3 &&
                        fields[0] == "FLINTTRADE_JOB_RELEASE" &&
                        fields[1] == "1" &&
                        fields[2] == token)
                    {
                        state.SignalRelease();
                        return;
                    }
                    if (fields.Length != 4 ||
                        fields[0] != "FLINTTRADE_JOB_TERMINATE" ||
                        fields[1] != "1" ||
                        fields[2] != token)
                    {
                        state.Signal("control-error");
                        state.SignalRelease();
                        return;
                    }

                    string reason = fields[3];
                    if (!IsControlReason(reason))
                    {
                        state.Signal("control-error");
                        state.SignalRelease();
                        return;
                    }

                    state.Signal(reason);
                }
            }
            catch
            {
                state.Signal("control-error");
                state.SignalRelease();
            }
        });

        reader.IsBackground = true;
        reader.Name = "FlintTrade Job control";
        reader.Start();
    }

    private static bool IsControlReason(string reason)
    {
        return reason == "cancel" ||
            reason == "timeout" ||
            reason == "listener" ||
            reason == "shutdown";
    }

    private static void WriteSettled(
        Options options,
        string reason,
        uint leaderExit)
    {
        // Separate the proof from an unterminated target stderr fragment.
        Console.Error.WriteLine();
        Console.Error.WriteLine(
            "FLINTTRADE_JOB_SUPERVISOR\t1\t{0}\tsettled\t{1}\t{2}\t0",
            options.Token,
            reason,
            leaderExit.ToString(CultureInfo.InvariantCulture));
        Console.Error.Flush();
    }

    private static void RequireHandle(IntPtr handle, string operation)
    {
        if (handle == IntPtr.Zero || handle == InvalidHandle)
            throw NativeError(operation);
    }

    private static Win32Exception NativeError(string operation)
    {
        return new Win32Exception(
            Marshal.GetLastWin32Error(),
            operation + " failed");
    }

    private static void CloseOwnedHandle(ref IntPtr handle)
    {
        if (handle == IntPtr.Zero || handle == InvalidHandle)
        {
            handle = IntPtr.Zero;
            return;
        }

        IntPtr closing = handle;
        handle = IntPtr.Zero;
        CloseHandle(closing);
    }

    private sealed class ControlState
    {
        private readonly IntPtr startEventHandle;
        private readonly IntPtr eventHandle;
        private readonly IntPtr releaseEventHandle;
        private string reason;

        internal ControlState(
            IntPtr startEventHandle,
            IntPtr eventHandle,
            IntPtr releaseEventHandle)
        {
            this.startEventHandle = startEventHandle;
            this.eventHandle = eventHandle;
            this.releaseEventHandle = releaseEventHandle;
        }

        internal string Reason
        {
            get
            {
                return Interlocked.CompareExchange(
                    ref this.reason,
                    null,
                    null);
            }
        }

        internal void Signal(string value)
        {
            if (Interlocked.CompareExchange(
                    ref this.reason,
                    value,
                    null) == null)
            {
                SetEvent(this.eventHandle);
            }
        }

        internal void SignalStart()
        {
            SetEvent(this.startEventHandle);
        }

        internal void SignalRelease()
        {
            SetEvent(this.releaseEventHandle);
        }
    }

    private sealed class Options
    {
        internal string Token;
        internal uint ParentPid;
        internal string WorkingDirectory;
        internal string TargetSha256;
        internal string Target;
        internal string[] TargetArguments;

        internal static Options Parse(string[] args)
        {
            if (args.Length < 8)
                throw new ArgumentException("Incomplete supervisor protocol.");

            int index = 0;
            Expect(args, ref index, "--protocol");
            Expect(args, ref index, "1");
            Expect(args, ref index, "--token");

            string token = Take(args, ref index);
            if (!IsHexToken(token))
                throw new ArgumentException("Invalid supervisor token.");

            Expect(args, ref index, "--parent-pid");

            uint parentPid;
            if (!UInt32.TryParse(
                    Take(args, ref index),
                    NumberStyles.None,
                    CultureInfo.InvariantCulture,
                    out parentPid) ||
                parentPid == 0)
            {
                throw new ArgumentException("Invalid parent PID.");
            }

            string workingDirectory = null;
            if (index < args.Length && args[index] == "--cwd")
            {
                index++;
                string suppliedWorkingDirectory = Take(args, ref index);
                if (!Path.IsPathRooted(suppliedWorkingDirectory))
                {
                    throw new ArgumentException(
                        "Working directory must be an existing absolute path.");
                }
                workingDirectory = Path.GetFullPath(suppliedWorkingDirectory);
                if (!Directory.Exists(workingDirectory))
                    throw new ArgumentException(
                        "Working directory must be an existing absolute path.");
            }

            string targetSha256 = null;
            if (index < args.Length && args[index] == "--target-sha256")
            {
                index++;
                targetSha256 = Take(args, ref index);
                if (!IsSha256(targetSha256))
                    throw new ArgumentException("Invalid target executable digest.");
            }

            Expect(args, ref index, "--");

            string suppliedTarget = Take(args, ref index);
            if (!Path.IsPathRooted(suppliedTarget))
                throw new ArgumentException(
                    "Target must be an existing absolute executable.");
            string target = Path.GetFullPath(suppliedTarget);
            if (!File.Exists(target) ||
                !String.Equals(
                    Path.GetExtension(target),
                    ".exe",
                    StringComparison.OrdinalIgnoreCase))
            {
                throw new ArgumentException(
                    "Target must be an existing absolute executable.");
            }

            string[] targetArguments =
                new string[args.Length - index];
            Array.Copy(
                args,
                index,
                targetArguments,
                0,
                targetArguments.Length);

            return new Options
            {
                Token = token,
                ParentPid = parentPid,
                WorkingDirectory = workingDirectory,
                TargetSha256 = targetSha256,
                Target = target,
                TargetArguments = targetArguments
            };
        }

        private static string Take(string[] args, ref int index)
        {
            if (index >= args.Length)
                throw new ArgumentException("Incomplete supervisor protocol.");
            return args[index++];
        }

        private static void Expect(
            string[] args,
            ref int index,
            string expected)
        {
            if (Take(args, ref index) != expected)
                throw new ArgumentException("Invalid supervisor protocol.");
        }

        private static bool IsHexToken(string value)
        {
            if (value == null || value.Length != 32)
                return false;

            for (int index = 0; index < value.Length; index++)
            {
                char current = value[index];
                bool digit = current >= '0' && current <= '9';
                bool lower = current >= 'a' && current <= 'f';
                bool upper = current >= 'A' && current <= 'F';

                if (!digit && !lower && !upper)
                    return false;
            }

            return true;
        }

        private static bool IsSha256(string value)
        {
            if (value == null || value.Length != 64)
                return false;

            for (int index = 0; index < value.Length; index++)
            {
                char current = value[index];
                bool digit = current >= '0' && current <= '9';
                bool lower = current >= 'a' && current <= 'f';
                if (!digit && !lower)
                    return false;
            }

            return true;
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SECURITY_ATTRIBUTES
    {
        internal int nLength;
        internal IntPtr lpSecurityDescriptor;
        internal int bInheritHandle;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO
    {
        internal int cb;
        internal string lpReserved;
        internal string lpDesktop;
        internal string lpTitle;
        internal int dwX;
        internal int dwY;
        internal int dwXSize;
        internal int dwYSize;
        internal int dwXCountChars;
        internal int dwYCountChars;
        internal int dwFillAttribute;
        internal uint dwFlags;
        internal short wShowWindow;
        internal short cbReserved2;
        internal IntPtr lpReserved2;
        internal IntPtr hStdInput;
        internal IntPtr hStdOutput;
        internal IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct STARTUPINFOEX
    {
        internal STARTUPINFO StartupInfo;
        internal IntPtr lpAttributeList;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION
    {
        internal IntPtr hProcess;
        internal IntPtr hThread;
        internal uint dwProcessId;
        internal uint dwThreadId;
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
    private struct JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
    {
        internal long TotalUserTime;
        internal long TotalKernelTime;
        internal long ThisPeriodTotalUserTime;
        internal long ThisPeriodTotalKernelTime;
        internal uint TotalPageFaultCount;
        internal uint TotalProcesses;
        internal uint ActiveProcesses;
        internal uint TotalTerminatedProcesses;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        internal ulong ReadOperationCount;
        internal ulong WriteOperationCount;
        internal ulong OtherOperationCount;
        internal ulong ReadTransferCount;
        internal ulong WriteTransferCount;
        internal ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        internal long PerProcessUserTimeLimit;
        internal long PerJobUserTimeLimit;
        internal uint LimitFlags;
        internal UIntPtr MinimumWorkingSetSize;
        internal UIntPtr MaximumWorkingSetSize;
        internal uint ActiveProcessLimit;
        internal UIntPtr Affinity;
        internal uint PriorityClass;
        internal uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        internal JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        internal IO_COUNTERS IoInfo;
        internal UIntPtr ProcessMemoryLimit;
        internal UIntPtr JobMemoryLimit;
        internal UIntPtr PeakProcessMemoryUsed;
        internal UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObjectW(
        IntPtr jobAttributes,
        string name);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetInformationJobObject(
        IntPtr job,
        int informationClass,
        ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION information,
        uint informationLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryInformationJobObject(
        IntPtr job,
        int informationClass,
        ref JOBOBJECT_BASIC_ACCOUNTING_INFORMATION information,
        uint informationLength,
        IntPtr returnLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AssignProcessToJobObject(
        IntPtr job,
        IntPtr process);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateJobObject(
        IntPtr job,
        uint exitCode);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcessW(
        string applicationName,
        StringBuilder commandLine,
        IntPtr processAttributes,
        IntPtr threadAttributes,
        [MarshalAs(UnmanagedType.Bool)] bool inheritHandles,
        uint creationFlags,
        IntPtr environment,
        string currentDirectory,
        ref STARTUPINFOEX startupInfo,
        out PROCESS_INFORMATION processInformation);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint ResumeThread(IntPtr thread);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateProcess(
        IntPtr process,
        uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetExitCodeProcess(
        IntPtr process,
        out uint exitCode);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(
        IntPtr handle,
        uint milliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForMultipleObjects(
        uint count,
        [In] IntPtr[] handles,
        [MarshalAs(UnmanagedType.Bool)] bool waitAll,
        uint milliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(
        uint desiredAccess,
        [MarshalAs(UnmanagedType.Bool)] bool inheritHandle,
        uint processId);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateEventW(
        IntPtr eventAttributes,
        [MarshalAs(UnmanagedType.Bool)] bool manualReset,
        [MarshalAs(UnmanagedType.Bool)] bool initialState,
        string name);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetEvent(IntPtr eventHandle);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr GetStdHandle(int standardHandle);

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetCurrentProcess();

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DuplicateHandle(
        IntPtr sourceProcess,
        IntPtr sourceHandle,
        IntPtr targetProcess,
        out IntPtr targetHandle,
        uint desiredAccess,
        [MarshalAs(UnmanagedType.Bool)] bool inheritHandle,
        uint options);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateFileW(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        ref SECURITY_ATTRIBUTES securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(
        IntPtr file,
        out BY_HANDLE_FILE_INFORMATION information);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandleW(
        IntPtr file,
        StringBuilder path,
        uint pathLength,
        uint flags);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool InitializeProcThreadAttributeList(
        IntPtr attributeList,
        int attributeCount,
        int flags,
        ref IntPtr size);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UpdateProcThreadAttribute(
        IntPtr attributeList,
        uint flags,
        IntPtr attribute,
        IntPtr value,
        IntPtr size,
        IntPtr previousValue,
        IntPtr returnSize);

    [DllImport("kernel32.dll")]
    private static extern void DeleteProcThreadAttributeList(
        IntPtr attributeList);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);
}
