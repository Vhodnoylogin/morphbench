// Compiled together with the complete production launcher by test_launcher_native.py.
// No form is shown, and every synthetic child is bounded and cleaned up by its check.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

static class LauncherNativeChecks
{
    static string Self { get { return typeof(LauncherNativeChecks).Assembly.Location; } }
    static string scratch;
    static string production;
    static string python;

    [STAThread]
    static int Main(string[] args)
    {
        if (args.Length > 0 && args[0] == "child") return Child(args);
        string childMode = Environment.GetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_CHILD");
        if (childMode == "server-inherited" || childMode == "server-inherited-flood")
            return Child(new[] { "child", "inherited", Environment.GetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_MARKER"),
                childMode == "server-inherited-flood" ? "flood-descendant" : "sleep" });
        if (childMode != null) return Child(new[] { "child", childMode });
        try
        {
            scratch = args[2];
            production = args[3];
            python = args[4];
            Texts.Configure(new LaunchContext { Home = args[3], SettingsHome = args[3] });
            switch (args[1])
            {
                case "start-failure": StartFailure(); break;
                case "pipes": Pipes(); break;
                case "timeout": Timeout(); break;
                case "inherited-pipe": InheritedPipe(); break;
                case "cancel": Cancel(); break;
                case "cli": Cli(); break;
                case "discovery": Discovery(); break;
                case "dispatch": Dispatch(); break;
                case "ownership": Ownership(); break;
                case "http": Http(); break;
                case "shutdown-pin": ShutdownPin(); break;
                case "pipe-resources": PipeResources(false); break;
                case "server-pipe-resources": PipeResources(true); break;
                case "utf8": Utf8(); break;
                case "diagnostic": Diagnostic(); break;
                default: throw new Exception("unknown check");
            }
            Console.WriteLine("PASS " + args[1]);
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }

    static void Check(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }

    static ProcessStartInfo Start(string arguments)
    {
        return new ProcessStartInfo(Self, arguments)
        {
            UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = scratch,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
        };
    }

    static int Child(string[] args)
    {
        switch (args[1])
        {
            case "pipes":
                var writer = new Thread(delegate()
                {
                    for (int i = 0; i < 128; i++) Console.Error.Write(new string('e', 8192));
                    Console.Error.Flush();
                });
                writer.Start();
                for (int i = 0; i < 128; i++) Console.Write(new string('o', 8192));
                Console.Out.Flush();
                writer.Join();
                return 0;
            case "sleep":
                Console.WriteLine(Process.GetCurrentProcess().Id);
                Console.Out.Flush();
                Thread.Sleep(15000);
                return 0;
            case "utf8":
                using (var output = Console.OpenStandardOutput())
                    foreach (byte value in Encoding.UTF8.GetBytes("\uFEFFЖ🙂кириллица"))
                    {
                        output.WriteByte(value);
                        output.Flush();
                        Thread.Sleep(2);
                    }
                return 0;
            case "utf8-incomplete":
                using (var output = Console.OpenStandardOutput()) output.WriteByte(0xD0);
                return 0;
            case "flood-descendant":
                var clock = Stopwatch.StartNew();
                try
                {
                    using (var output = Console.OpenStandardOutput())
                    {
                        byte[] flood = Encoding.ASCII.GetBytes(new string('f', 4096));
                        while (clock.ElapsedMilliseconds < 15000) output.Write(flood, 0, flood.Length);
                    }
                }
                catch (IOException) { }
                Thread.Sleep(Math.Max(0, 15000 - (int)clock.ElapsedMilliseconds));
                return 0;
            case "inherited":
                var info = new StartupInfo();
                info.Size = Marshal.SizeOf(info);
                info.Flags = 0x100;
                info.Input = GetStdHandle(-10);
                info.Output = GetStdHandle(-11);
                info.Error = GetStdHandle(-12);
                ProcessInfo child;
                bool started = CreateProcess(null, new StringBuilder(Module.Quote(Self) + " child " + (args.Length > 3 ? args[3] : "sleep")),
                    IntPtr.Zero, IntPtr.Zero, true, 0x08000000, IntPtr.Zero, scratch, ref info, out child);
                if (!started) return 44;
                File.WriteAllText(args[2], child.Id.ToString());
                CloseHandle(child.Thread);
                CloseHandle(child.Process);
                return 0;
            case "nonzero": Console.Write("{\"state\":\"ours\"}"); Console.Error.Write("diagnostic"); return 42;
            case "status": Console.Write("{\"state\":\"free\",\"url\":\"http://127.0.0.1:1/\"}"); Console.Error.Write("warning {not json}"); return 0;
            default: return 43;
        }
    }

    static void StartFailure()
    {
        using (var runner = new ChildRunner())
        {
            var start = Start("");
            start.FileName = Path.Combine(scratch, "missing.exe");
            var result = runner.Run(start, 1000, 1000);
            Check(result.StartError != null && result.ExitCode == null, "process-start failure escaped/lost");
            start.FileName = Path.Combine(scratch, "not-executable.exe");
            File.WriteAllText(start.FileName, "not an executable");
            result = runner.Run(start, 1000, 1000);
            Check(result.StartError != null, "invalid executable was not reported");
        }
    }

    static void Pipes()
    {
        using (var runner = new ChildRunner())
        {
            var result = runner.Run(Start("child pipes"), 10000, 50000);
            Check(!result.TimedOut && result.ExitCode == 0, "concurrent pipes deadlocked");
            Check(result.Output.Length == 50000 && result.ErrorOutput.Length == 50000 && result.Truncated,
                "capture cap lost or pipes were not fully drained");
        }
    }

    static void Timeout()
    {
        using (var runner = new ChildRunner())
        {
            var clock = Stopwatch.StartNew();
            var result = runner.Run(Start("child sleep"), 300, 1000);
            Check(result.TimedOut && clock.ElapsedMilliseconds < 3000, "deadline did not bound a sleeping child");
            int pid;
            Check(int.TryParse(result.Output.Trim(), out pid), "partial child output was lost before timeout");
            WaitGone(pid);
        }
    }

    static void InheritedPipe()
    {
        string marker = Path.Combine(scratch, "descendant.pid");
        using (var runner = new ChildRunner())
        {
            var clock = Stopwatch.StartNew();
            try
            {
                var result = runner.Run(Start("child inherited " + Module.Quote(marker)), 500, 1000);
                Check(result.TimedOut && clock.ElapsedMilliseconds < 3000, "inherited pipe EOF ignored deadline");
                Check(result.ExitCode == 0, "direct child did not exit successfully before inherited-pipe timeout");
            }
            finally
            {
                if (File.Exists(marker))
                    try { using (var process = Process.GetProcessById(int.Parse(File.ReadAllText(marker)))) process.Kill(); }
                    catch (ArgumentException) { }
            }
        }
    }

    static void Cancel()
    {
        var runner = new ChildRunner();
        ChildResult result = null;
        var worker = new Thread(delegate() { result = runner.Run(Start("child sleep"), 15000, 1000); });
        worker.Start();
        Thread.Sleep(200);
        runner.Dispose();
        Check(worker.Join(3000), "close left a CLI worker blocked");
        Check(result.Cancelled, "cancelled child was reported as successful");
        Check(runner.Run(Start("child sleep"), 300, 1000).Cancelled, "new child started after close");
    }

    static void Utf8()
    {
        using (var runner = new ChildRunner())
        {
            var result = runner.Run(Start("child utf8"), 3000, 1000);
            Check(result.ExitCode == 0 && result.Output == "Ж🙂кириллица", "split UTF-8/BOM decoding changed");
            result = runner.Run(Start("child utf8-incomplete"), 3000, 1000);
            Check(result.ExitCode == 0 && result.Output == "\uFFFD", "incomplete final UTF-8 was not flushed");
        }
    }

    static void Diagnostic()
    {
        string home = Path.Combine(scratch, "install", "launcher");
        Directory.CreateDirectory(home);
        File.Copy(Path.Combine(production, "launcher", "mb.py"), Path.Combine(home, "mb.py"));
        string app = App(Path.Combine(scratch, "install", "app"));
        File.WriteAllText(Path.Combine(app, "mb.py"),
            "import json, sys\nprint(json.dumps({'command': sys.argv[1:]}))\n");
        Environment.SetEnvironmentVariable("MORPHBENCH_PYTHON", python);
        var entry = typeof(Program).GetMethod("Main", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic);
        entry.Invoke(null, new object[] { new[] { "--diag", home } });
        string path = Path.Combine(home, "morphbench.diag.json");
        var report = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(path));
        Check(report.ContainsKey("environment") && report.ContainsKey("status") && !report.ContainsKey("error"),
            "--diag did not emit generic structured environment/status");
        Check(!File.Exists(Path.Combine(home, "morphbench.diag.png")), "--diag rendered a domain fixture");
        string broken = Path.Combine(home, "broken.exe");
        File.WriteAllText(broken, "not an executable");
        Environment.SetEnvironmentVariable("MORPHBENCH_PYTHON", broken);
        entry.Invoke(null, new object[] { new[] { "--diag", home } });
        report = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(path));
        Check(report.ContainsKey("error") && report.ContainsKey("launcherProtocol"), "--diag process-start failure escaped JSON report");
        Environment.SetEnvironmentVariable("MORPHBENCH_PYTHON", null);
    }

    static void PipeResources(bool serverMode)
    {
        var descendants = new List<int>();
        var process = Process.GetCurrentProcess();
        var context = new LaunchContext { Home = scratch, Python = Self, StopWaitMs = 100 };
        try
        {
            // Warm the CLR process/exit-event plumbing before measuring the repeated case.
            using (var runner = new ChildRunner()) runner.Run(Start("child nonzero"), 2000, 1000);
            Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_CHILD", "nonzero");
            using (var launcher = new Launcher(context))
            {
                launcher.Start(null);
                var wait = Stopwatch.StartNew();
                while (launcher.Owns && wait.ElapsedMilliseconds < 2000) Thread.Sleep(10);
            }
            Thread.Sleep(200);
            GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect();
            process.Refresh();
            int threadsBefore = process.Threads.Count;
            int handlesBefore = process.HandleCount;
            using (var runner = new ChildRunner())
            using (var launcher = new Launcher(context))
                for (int i = 0; i < 8; i++)
                {
                    string marker = Path.Combine(scratch, "resource-" + i + ".pid");
                    if (serverMode)
                    {
                        Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_CHILD", i % 2 == 0 ? "server-inherited" : "server-inherited-flood");
                        Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_MARKER", marker);
                        launcher.Start(null);
                        var wait = Stopwatch.StartNew();
                        while (launcher.Owns && wait.ElapsedMilliseconds < 2000) Thread.Sleep(10);
                        Check(!launcher.Owns, "direct synthetic server did not exit");
                    }
                    else
                    {
                        Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_CHILD", null);
                        var result = runner.Run(Start("child inherited " + Module.Quote(marker)), 200, 1000);
                        Check(result.TimedOut && result.ExitCode == 0, "inherited-pipe timeout contract changed");
                    }
                    Check(File.Exists(marker), "synthetic descendant did not start");
                    descendants.Add(int.Parse(File.ReadAllText(marker)));
                }
            Thread.Sleep(300);
            GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect();
            process.Refresh();
            int threadsAfter = process.Threads.Count;
            int handlesAfter = process.HandleCount;
            Console.WriteLine("resources threads=" + threadsBefore + "->" + threadsAfter
                + " handles=" + handlesBefore + "->" + handlesAfter);
            // Keep descendants alive until after measurement: killing them would hide a
            // synchronous read stranded on the inherited writer, which was the original bug.
            foreach (int pid in descendants)
                using (var descendant = Process.GetProcessById(pid)) Check(!descendant.HasExited, "descendant was killed by launcher");
            Check(threadsAfter <= threadsBefore + 4, "inherited pipes retained reader threads");
            Check(handlesAfter <= handlesBefore + 24, "inherited pipes retained reader handles");
        }
        finally
        {
            Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_CHILD", null);
            Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_MARKER", null);
            foreach (int pid in descendants)
                try { using (var descendant = Process.GetProcessById(pid)) descendant.Kill(); }
                catch (ArgumentException) { }
            process.Dispose();
        }
    }

    static void Cli()
    {
        try
        {
            Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_CHILD", "status");
            using (var launcher = new Launcher(scratch, Self))
            {
                var status = launcher.StatusFromCli();
                Check(status.Error == null && status.State == "free" && status.Url.Contains(":1/"),
                    "stderr contaminated stdout JSON");
            }
            Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_CHILD", "nonzero");
            using (var launcher = new Launcher(scratch, Self))
            {
                var status = launcher.StatusFromCli();
                Check(status.Error != null && status.Error.Contains("42") && status.Error.Contains("diagnostic") && !status.Up,
                    "nonzero child with valid JSON was accepted or lost diagnostics");
            }
            using (var launcher = new Launcher(scratch, Path.Combine(scratch, "missing.exe")))
                Check(launcher.StatusFromCli().Error != null, "initial failure escaped status worker");
        }
        finally { Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_CHILD", null); }
    }

    static string App(string path)
    {
        Directory.CreateDirectory(Path.Combine(path, "morphbench"));
        File.WriteAllText(Path.Combine(path, "mb.py"), "# fixture");
        File.WriteAllText(Path.Combine(path, "morphbench", "__init__.py"), "# fixture");
        return path;
    }

    static void Discovery()
    {
        try
        {
            Environment.SetEnvironmentVariable("MORPHBENCH_HOME", null);
            Environment.SetEnvironmentVariable("MORPHBENCH_APP", null);
            Environment.SetEnvironmentVariable("MORPHBENCH_PYTHON", python);
            string home = Path.Combine(scratch, "install", "launcher");
            Directory.CreateDirectory(home);
            File.Copy(Path.Combine(production, "launcher", "mb.py"), Path.Combine(home, "mb.py"));
            string app = App(Path.Combine(scratch, "install", "app"));
            Directory.CreateDirectory(Path.Combine(app, "locale", "ru"));
            File.WriteAllText(Path.Combine(app, "locale", "ru", "launcher.json"), "{\"launcher.start\":\"application-ru\"}");
            File.WriteAllText(Path.Combine(app, "morphbench.json"), "{\"language\":\"ru\",\"launcherCliTimeoutMs\":321,\"launcherLogMaxChars\":1001}");
            File.WriteAllText(Path.Combine(home, "morphbench.json"), "{\"language\":\"en\",\"launcherCliTimeoutMs\":999}");
            Environment.SetEnvironmentVariable("MORPHBENCH_LANG", null);
            var context = LaunchContext.Discover(home);
            using (var launcher = new Launcher(context)) launcher.Initialize();
            Check(context.SettingsHome == app && context.CliTimeoutMs == 321 && context.LogMaxChars == 1001,
                "structured bootstrap ignored Application settings");
            Texts.Configure(context);
            Check(Texts.T("launcher.start") == "application-ru", "Application language ignored");
            Check(context.ServerApi == "api/launcher/v1/", "versioned server adapter not selected");
            string explicitApp = App(Path.Combine(scratch, "explicit app"));
            Environment.SetEnvironmentVariable("MORPHBENCH_APP", explicitApp + "\\.\\");
            context = LaunchContext.Discover(home);
            using (var launcher = new Launcher(context)) launcher.Initialize();
            Check(context.SettingsHome == explicitApp, "bootstrap lexical App override rejected");
            Environment.SetEnvironmentVariable("MORPHBENCH_APP", "relative");
            bool rejected = false;
            using (var launcher = new Launcher(LaunchContext.Discover(home)))
                try { launcher.Initialize(); } catch (Exception) { rejected = true; }
            Check(rejected, "invalid App override silently fell back");
            string source = App(Path.Combine(scratch, "source"));
            Directory.CreateDirectory(Path.Combine(source, "launcher"));
            File.Copy(Path.Combine(production, "launcher", "mb.py"), Path.Combine(source, "launcher", "mb.py"));
            context = LaunchContext.Discover(source);
            using (var launcher = new Launcher(context)) launcher.Initialize();
            Check(context.SettingsHome == source, "source query did not pin positional App home");
            Check(Environment.GetEnvironmentVariable("MORPHBENCH_APP") == "relative", "source query mutated parent environment");
            foreach (string invalid in new[] { "{}", "{\"protocolVersion\":2}", "[]", "not JSON" })
            {
                rejected = false;
                try { context.ApplyBootstrap(invalid); } catch (Exception) { rejected = true; }
                Check(rejected, "malformed/unsupported bootstrap accepted");
            }
        }
        finally { Environment.SetEnvironmentVariable("MORPHBENCH_APP", null); }
    }

    static void Dispatch()
    {
        for (int iteration = 0; iteration < 30; iteration++)
        {
            var control = new Control();
            IntPtr handle = control.Handle;
            var ui = new UiDispatcher(control);
            int called = 0;
            var worker = new Thread(delegate()
            {
                for (int i = 0; i < 500; i++) ui.Post(() => called++);
            });
            worker.Start();
            ui.Close();
            control.Dispose();
            Check(worker.Join(3000), "UI dispatch worker blocked during close");
            Application.DoEvents();
            Check(called == 0 && !ui.Post(() => called++), "completion ran after closing");
        }
        using (var control = new Control())
        {
            IntPtr handle = control.Handle;
            var ui = new UiDispatcher(control);
            int called = 0;
            var worker = new Thread(delegate() { ui.Post(() => called++); });
            worker.Start(); worker.Join();
            ui.Close();
            Application.DoEvents();
            Check(called == 0, "queued callback ran after close gate");
        }
    }

    static void Ownership()
    {
        var start = Start("child sleep");
        using (var independent = Process.Start(start))
        {
            try
            {
                using (var launcher = new Launcher(scratch, Self)) { }
                Check(!independent.HasExited, "closing an attached launcher killed independent process");
            }
            finally { if (!independent.HasExited) independent.Kill(); }
        }
        Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_CHILD", "sleep");
        var owned = new Launcher(new LaunchContext { Home = scratch, Python = Self, StopWaitMs = 200 });
        try
        {
            owned.Start(null);
            Check(owned.Owns, "synthetic owned server did not start");
            var clock = Stopwatch.StartNew();
            owned.Dispose();
            Check(!owned.Owns && clock.ElapsedMilliseconds < 3000, "owned server close exceeded deadline");
            bool rejected = false;
            try { owned.Start(null); } catch (OperationCanceledException) { rejected = true; }
            Check(rejected, "server started after launcher was closed");
        }
        finally { owned.Dispose(); Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_CHILD", null); }

        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_CHILD", "nonzero");
        var exited = new Launcher(new LaunchContext { Home = scratch, Python = Self, StopWaitMs = 200 })
        { Url = "http://127.0.0.1:" + ((IPEndPoint)listener.LocalEndpoint).Port + "/" };
        try
        {
            exited.Start(null);
            var wait = Stopwatch.StartNew();
            while (exited.Owns && wait.ElapsedMilliseconds < 3000) Thread.Sleep(10);
            Check(!exited.Owns, "synthetic already-exited server did not exit");
            exited.Dispose();
            Check(!listener.Pending(), "closing an exited child contacted a replacement server");
        }
        finally
        {
            exited.Dispose();
            listener.Stop();
            Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_CHILD", null);
        }
    }

    static void Http()
    {
        foreach (bool cancel in new[] { false, true })
        {
            var listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            var received = new ManualResetEvent(false);
            string request = null;
            var server = new Thread(delegate()
            {
                try
                {
                    using (var client = listener.AcceptTcpClient())
                    using (var stream = client.GetStream())
                    {
                        var reader = new StreamReader(stream);
                        request = reader.ReadLine();
                        while (!string.IsNullOrEmpty(reader.ReadLine())) { }
                        byte[] headers = Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nServer: morphbench/test\r\nContent-Length: 99999\r\nConnection: close\r\n\r\n");
                        stream.Write(headers, 0, headers.Length);
                        stream.Flush();
                        received.Set();
                        // A continuous trickle defeats per-read timeouts but must not defeat
                        // either the request's total deadline or form-close cancellation.
                        for (int i = 0; i < 300; i++)
                        {
                            stream.WriteByte((byte)' ');
                            stream.Flush();
                            Thread.Sleep(20);
                        }
                    }
                }
                catch (Exception) { }
            }) { IsBackground = true };
            server.Start();
            var context = new LaunchContext { Home = scratch, Python = Self, HttpTimeoutMs = cancel ? 10000 : 200 };
            var launcher = new Launcher(context) { Url = "http://127.0.0.1:" + ((IPEndPoint)listener.LocalEndpoint).Port + "/" };
            try
            {
                ServerStatus status = null;
                var worker = new Thread(delegate() { status = launcher.Probe(new ServerStatus()); });
                var clock = Stopwatch.StartNew();
                worker.Start();
                Check(received.WaitOne(3000), "HTTP request did not arrive");
                if (cancel) launcher.Dispose();
                Check(worker.Join(3000) && clock.ElapsedMilliseconds < 3500,
                    "HTTP response body outlived deadline/close");
                Check(request.StartsWith("GET /api/launcher/v1/environment "), "versioned HTTP adapter bypassed");
                if (!cancel) Check(status.State == "slow", "total body timeout misclassified as foreign server");
            }
            finally
            {
                launcher.Dispose();
                listener.Stop();
                server.Join(1000);
            }
        }
    }

    static void ShutdownPin()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        string request = null;
        var server = new Thread(delegate()
        {
            try
            {
                using (var client = listener.AcceptTcpClient())
                using (var stream = client.GetStream())
                {
                    var reader = new StreamReader(stream);
                    request = reader.ReadLine();
                    while (!string.IsNullOrEmpty(reader.ReadLine())) { }
                    byte[] response = Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nServer: morphbench/test\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}");
                    stream.Write(response, 0, response.Length);
                }
            }
            catch (Exception) { }
        }) { IsBackground = true };
        server.Start();
        Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_CHILD", "sleep");
        var launcher = new Launcher(new LaunchContext { Home = scratch, Python = Self, StopWaitMs = 300 })
        { Url = "http://127.0.0.1:" + ((IPEndPoint)listener.LocalEndpoint).Port + "/" };
        int pid = 0;
        var logged = new ManualResetEvent(false);
        launcher.Log = delegate(string line)
        {
            int observed;
            if (int.TryParse(line, out observed)) { pid = observed; logged.Set(); }
        };
        try
        {
            launcher.Start(null);
            Check(logged.WaitOne(3000), "streamed child log remained buffered");
            launcher.Dispose();
            Check(server.Join(2000) && request == "GET /api/launcher/v1/shutdown?pid=" + pid + " HTTP/1.1",
                "close-time shutdown did not pin the owned child PID");
            WaitGone(pid);
        }
        finally
        {
            launcher.Dispose();
            listener.Stop();
            Environment.SetEnvironmentVariable("MORPHBENCH_NATIVE_TEST_CHILD", null);
        }
    }

    static void WaitGone(int pid)
    {
        try
        {
            using (var process = Process.GetProcessById(pid)) Check(process.WaitForExit(2000), "timed-out child survived");
        }
        catch (ArgumentException) { }
    }

    [StructLayout(LayoutKind.Sequential)]
    struct StartupInfo
    {
        public int Size;
        public string Reserved, Desktop, Title;
        public int X, Y, XSize, YSize, XChars, YChars, Fill, Flags;
        public short Show, ReservedSize;
        public IntPtr ReservedBytes, Input, Output, Error;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct ProcessInfo { public IntPtr Process, Thread; public int Id, ThreadId; }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool CreateProcess(string application, StringBuilder command, IntPtr processAttributes,
        IntPtr threadAttributes, bool inherit, int flags, IntPtr environment, string current,
        ref StartupInfo startup, out ProcessInfo process);
    [DllImport("kernel32.dll")] static extern IntPtr GetStdHandle(int standard);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
}
