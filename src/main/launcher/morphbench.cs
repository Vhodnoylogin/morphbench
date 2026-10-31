// morphbench.exe - the launch window: bring the server up, stop it, the state, the browse root,
// the page.
//
// Why it is needed. MO2 replaces the file system only for the processes it started itself (and
// their children): the mods are merged into one game Data by the usvfs library. For the
// workbench to see the meshes of the whole build it has to be started from MO2 - and MO2 starts
// executables, not scripts. This window is exactly such an executable: started from MO2 it
// brings up `python mb.py serve` as its own child, and that child sees Data with every mod.
//
// The window computes nothing and knows nothing about meshes. Everything it can do is a call to
// the same server the command line calls: `serve --status`, `serve`, `serve --stop`, `/api/root`,
// open the page. Not a single path is written into it: the module is beside the exe (mb.py lives
// there), or a folder given as an argument, or the MORPHBENCH_HOME variable; python is the
// MORPHBENCH_PYTHON variable, the "python" key in morphbench.json, the python\ folder the release
// archive carries beside mb.py, python.exe on PATH (bar the Windows store stub), the PythonCore
// registry key, or the py.exe launcher.
//
// Arguments: --start - bring the server up and open the page at once; --root <folder> - the
// browse root for this run; <folder> - where mb.py lives.
//
// Built with the stock .NET Framework compiler, which every Windows has:
//     launcher\build.cmd
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;
using Microsoft.Win32.SafeHandles;

[assembly: AssemblyVersion("2.0.0.0")]
[assembly: AssemblyFileVersion("2.0.0.0")]
[assembly: AssemblyInformationalVersion("Morphbench Launcher v2 (protocol 1)")]

static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        var options = Options.Parse(args);
        var context = LaunchContext.Discover(options.Home);
        Texts.Configure(context);
        if (options.Diag)
        {
            // Diagnostics without a window: what python sees from under MO2 - into a file
            // beside the exe. That is how the VFS is checked with nobody at the screen:
            // started through MO2, the answer is in the file.
            string home = context.Home;
            string text = Diagnostic(context);
            try
            {
                File.WriteAllText(Path.Combine(home ?? AppDomain.CurrentDomain.BaseDirectory, "morphbench.diag.json"),
                                  text, new UTF8Encoding(false));
            }
            catch (Exception error)
            {
                Environment.ExitCode = 1;
                try { Console.Error.WriteLine(error.Message); } catch (Exception) { }
            }
            return;
        }
        Application.Run(new MainForm(options, context));
    }

    public static string Diagnostic(LaunchContext context)
    {
        var report = new Dictionary<string, object> { { "launcherProtocol", 1 } };
        var json = new JavaScriptSerializer();
        try
        {
            if (context.Home == null) throw new Exception(Texts.T("launcher.diagNoModule"));
            if (context.Python == null) throw new Exception(Texts.T("launcher.diagNoPython"));
            using (var launcher = new Launcher(context))
            {
                launcher.Initialize();
                Texts.Configure(context);
                report["environment"] = json.DeserializeObject(launcher.Cli(context.EnvironmentArgs));
                report["status"] = json.DeserializeObject(launcher.Cli(context.StatusArgs));
            }
        }
        catch (Exception error) { report["error"] = error.Message; }
        return json.Serialize(report);
    }
}

// ---- texts: the window reads the same catalogue the module does -----------------------------
//
// The window runs no python of its own, so it reads the locale files itself. The rules here are
// the rules of morphbench\i18n.py and the two must agree: the MORPHBENCH_LANG variable wins over
// the `language` setting, `auto` means the language of the operating system, every
// locale\<lang>\*.json is merged into one dictionary, a key starting with `#` is a note to the
// translator, and a key with no text falls back to English and then to the key itself.
//
// Nothing here may throw. This is a launcher: it has to come up even when the module beside it
// is broken, because a broken module is exactly when the user needs to read the error.
static class Texts
{
    //: Overrides the setting - for a run that must not depend on the machine.
    public const string Env = "MORPHBENCH_LANG";
    //: The language every other one falls back to. Its files hold every key in use.
    public const string Base = "en";

    static readonly Dictionary<string, string> chosen = new Dictionary<string, string>(StringComparer.Ordinal);
    static readonly Dictionary<string, string> fallback = new Dictionary<string, string>(StringComparer.Ordinal);
    //: `%(name)s` - by name, never by position: another language puts the words in another order.
    static readonly Regex Field = new Regex(@"%\((\w+)\)[-+ #0-9.]*[A-Za-z]");

    public static void Configure(LaunchContext context)
    {
        chosen.Clear();
        fallback.Clear();
        try
        {
            string home = context.SettingsHome ?? context.Home ?? AppDomain.CurrentDomain.BaseDirectory;
            string folder = context.LocaleHome ?? Path.Combine(home, "locale");
            Read(Path.Combine(folder, Base), fallback);
            string language = Wanted(context.Language);
            if (language != Base) Read(Path.Combine(folder, language), chosen);
            // A damaged/missing Application can still explain itself using the launcher overlay.
            string overlay = Path.Combine(context.Home ?? AppDomain.CurrentDomain.BaseDirectory, "locale");
            Read(Path.Combine(overlay, Base), fallback);
            if (language != Base) Read(Path.Combine(overlay, language), chosen);
        }
        catch (Exception)
        {
            // A catalogue that cannot be read is a nuisance; a window that will not open is a
            // fault. Every lookup then falls through to the key itself - latin, short and
            // searchable, which is better than an empty label.
        }
    }

    /// The text for a key, with the base language and then the key itself behind it.
    public static string T(string key)
    {
        string text;
        if (chosen.TryGetValue(key, out text) && text.Length > 0) return text;
        if (fallback.TryGetValue(key, out text) && text.Length > 0) return text;
        return key;
    }

    /// The same with named values put in: T("launcher.page", "url", url). The arguments go in
    /// pairs - name, value - because substitution is by name and a name is what the translator
    /// sees in the text.
    public static string T(string key, params object[] namesAndValues)
    {
        string text = T(key);
        if (namesAndValues == null || namesAndValues.Length < 2) return text;
        var values = new Dictionary<string, string>(StringComparer.Ordinal);
        for (int i = 0; i + 1 < namesAndValues.Length; i += 2)
        {
            string name = namesAndValues[i] == null ? "" : namesAndValues[i].ToString();
            values[name] = Convert.ToString(namesAndValues[i + 1], CultureInfo.InvariantCulture) ?? "";
        }
        bool whole = true;
        bool substituted = false;
        string filled = Field.Replace(text, delegate(Match m)
        {
            string value;
            if (values.TryGetValue(m.Groups[1].Value, out value)) { substituted = true; return value; }
            whole = false;
            return m.Value;
        });
        if (whole && substituted) return filled;
        // A substitution that does not fit the text is the translator's slip, not a reason to
        // lose what the caller meant to say: the values are appended so nothing goes missing.
        var names = new List<string>(values.Keys);
        names.Sort(StringComparer.Ordinal);
        var tail = new StringBuilder();
        foreach (string name in names)
        {
            if (tail.Length > 0) tail.Append(", ");
            tail.Append(name).Append("=").Append(values[name]);
        }
        return filled + " [" + tail + "]";
    }

    /// Which language to speak: the variable, then the setting, then the language of Windows.
    static string Wanted(string configured)
    {
        string code = Clean(Environment.GetEnvironmentVariable(Env));
        if (code.Length == 0) code = Clean(configured);
        if (code.Length == 0 || code == "auto") code = SystemLanguage();
        return code.Length == 0 ? Base : code;
    }

    static string SystemLanguage()
    {
        try
        {
            // CurrentUICulture, not InstalledUICulture: the module asks Windows for
            // GetUserDefaultUILanguage, which is the display language the user picked, and
            // InstalledUICulture is the one the machine was installed with. On a box switched
            // to another language the two differ, and the window would then speak a different
            // language from the server it starts.
            string code = CultureInfo.CurrentUICulture.TwoLetterISOLanguageName;
            return string.IsNullOrEmpty(code) ? Base : code.ToLowerInvariant();
        }
        catch (Exception) { return Base; }
    }

    /// Every text of one language: a folder holding any number of files, one per section,
    /// merged into one dictionary. A new section arrives as a NEW FILE, so two people adding
    /// two sections never rewrite the same file. The first declaration of a key wins, the way
    /// the module's catalogue does it.
    static void Read(string folder, Dictionary<string, string> into)
    {
        string[] files;
        try { files = Directory.GetFiles(folder, "*.json"); }
        catch (Exception) { return; }          // no folder for this language - English answers
        Array.Sort(files, StringComparer.OrdinalIgnoreCase);
        var js = new JavaScriptSerializer();
        foreach (string file in files)
        {
            try
            {
                var data = js.Deserialize<Dictionary<string, object>>(File.ReadAllText(file));
                if (data == null) continue;
                foreach (KeyValuePair<string, object> pair in data)
                {
                    string key = pair.Key ?? "";
                    if (key.Length == 0 || key[0] == '#' || pair.Value == null) continue;
                    if (!into.ContainsKey(key)) into[key] = pair.Value.ToString();
                }
            }
            // Caught per file: one malformed file must not lose the texts of all the others.
            catch (Exception) { }
        }
    }

    static string Clean(string code)
    {
        return code == null ? "" : code.Trim().ToLowerInvariant();
    }
}

// ---- command line arguments -----------------------------------------------------------------
class Options
{
    public string Home;          // the folder with mb.py, if named as an argument
    public string Root;          // the browse root for this run
    public bool Start;           // bring the server up at once
    public bool Diag;            // no window: env --json into a file, then leave

    public static Options Parse(string[] args)
    {
        var o = new Options();
        for (int i = 0; i < args.Length; i++)
        {
            string a = args[i];
            if (a == "--start") o.Start = true;
            else if (a == "--diag") o.Diag = true;
            else if (a == "--root" && i + 1 < args.Length) o.Root = args[++i];
            else if (a.StartsWith("--root=")) o.Root = a.Substring(7);
            else if (!a.StartsWith("--")) o.Home = a;
        }
        return o;
    }
}

// ---- where the module is and where python is ------------------------------------------------
static class Module
{
    public const string Script = "mb.py";

    public static string FindHome(string named)
    {
        var candidates = new List<string>();
        if (!string.IsNullOrEmpty(named)) candidates.Add(named);
        string env = Environment.GetEnvironmentVariable("MORPHBENCH_HOME");
        if (!string.IsNullOrEmpty(env)) candidates.Add(env);
        candidates.Add(AppDomain.CurrentDomain.BaseDirectory);
        candidates.Add(Directory.GetCurrentDirectory());
        foreach (string dir in candidates)
        {
            try
            {
                string full = Path.GetFullPath(dir);
                if (IsFile(Path.Combine(full, Script))) return full;
            }
            catch (Exception) { }
        }
        return null;
    }

    public static string FindPython(string home)
    {
        string env = Environment.GetEnvironmentVariable("MORPHBENCH_PYTHON");
        if (IsFile(env)) return env;
        string fromConfig = PythonFromConfig(Path.Combine(home, "morphbench.json"));
        if (IsFile(fromConfig)) return fromConfig;
        // The interpreter the release archive carries. It comes before PATH on purpose: bundling
        // python is what makes the archive answer the same way on every machine, and a python
        // found on PATH is somebody else's version with somebody else's packages. Only the two
        // explicit overrides above outrank it. Absent from a working copy, where there is no
        // python\ folder and the search simply goes on.
        string bundled = Path.Combine(home, "python", "python.exe");
        if (IsFile(bundled)) return bundled;
        string path = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (string dir in path.Split(Path.PathSeparator))
        {
            if (dir.Trim().Length == 0) continue;
            // The Windows store stub lives in WindowsApps: with no real python behind it, it
            // opens the store instead of running anything.
            if (dir.IndexOf("WindowsApps", StringComparison.OrdinalIgnoreCase) >= 0) continue;
            try
            {
                string exe = Path.Combine(dir.Trim().Trim('"'), "python.exe");
                if (IsFile(exe)) return exe;
            }
            catch (Exception) { }
        }
        string fromRegistry = PythonFromRegistry();
        if (fromRegistry != null) return fromRegistry;
        string launcher = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "py.exe");
        if (IsFile(launcher)) return launcher;
        return null;
    }

    static string PythonFromConfig(string json)
    {
        if (!IsFile(json)) return null;
        try
        {
            var data = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(json));
            object value;
            return data != null && data.TryGetValue("python", out value) ? value as string : null;
        }
        catch (Exception) { return null; }
    }

    static string PythonFromRegistry()
    {
        foreach (RegistryKey hive in new[] { Registry.CurrentUser, Registry.LocalMachine })
        {
            try
            {
                using (RegistryKey core = hive.OpenSubKey(@"Software\Python\PythonCore"))
                {
                    if (core == null) continue;
                    string[] versions = core.GetSubKeyNames();
                    Array.Sort(versions, StringComparer.OrdinalIgnoreCase);
                    Array.Reverse(versions);           // the newest one first
                    foreach (string v in versions)
                    {
                        using (RegistryKey k = core.OpenSubKey(v + @"\InstallPath"))
                        {
                            if (k == null) continue;
                            string exe = k.GetValue("ExecutablePath") as string;
                            if (IsFile(exe)) return exe;
                            string dir = k.GetValue("") as string;
                            if (dir != null && IsFile(Path.Combine(dir, "python.exe")))
                                return Path.Combine(dir, "python.exe");
                        }
                    }
                }
            }
            catch (Exception) { }
        }
        return null;
    }

    public static bool IsFile(string path)
    {
        try
        {
            if (string.IsNullOrEmpty(path)) return false;
            using (File.Open(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete)) return true;
        }
        catch (Exception) { return false; }
    }

    public static string Quote(string s)
    {
        // ProcessStartInfo passes one Windows command line, not an argv array. Backslashes
        // immediately before a quote are escapes, including the quote closing the argument:
        // a directory ending in '\\' must keep its slash without swallowing the next switch.
        var quoted = new StringBuilder("\"");
        int slashes = 0;
        foreach (char ch in s)
        {
            if (ch == '\\')
            {
                slashes++;
                continue;
            }
            quoted.Append('\\', ch == '"' ? slashes * 2 + 1 : slashes);
            quoted.Append(ch);
            slashes = 0;
        }
        quoted.Append('\\', slashes * 2);
        quoted.Append('"');
        return quoted.ToString();
    }
}

// The native contract stops at the versioned bootstrap response. Application selection,
// settings and HTTP routing belong to the updateable stdlib shim, never to this executable.
class LaunchContext
{
    public string Home;
    public string SettingsHome;
    public string LocaleHome;
    public string Python;
    public string Language;
    public string ServerApi = "api/launcher/v1/";
    public string StatusArgs = "serve --status --json";
    public string EnvironmentArgs = "env --json";
    public string StartArgs = "serve --no-browser --json";
    public int CliTimeoutMs = 30000;
    public int HttpTimeoutMs = 30000;
    public int StopWaitMs = 5000;
    public int LogMaxChars = 200000;

    public static LaunchContext Discover(string named)
    {
        string home = Module.FindHome(named);
        return new LaunchContext { Home = home, Python = home == null ? null : Module.FindPython(home) };
    }

    public ProcessStartInfo QueryStart()
    {
        string sourceShim = Path.Combine(Home, "launcher", "mb.py");
        bool source = Module.IsFile(sourceShim) && Module.IsFile(Path.Combine(Home, "morphbench", "__init__.py"));
        string shim = source ? sourceShim : Path.Combine(Home, Module.Script);
        var start = new ProcessStartInfo(Python, Module.Quote(shim) + " --launcher-context --protocol 1")
        {
            UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Home,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
        };
        if (source) start.EnvironmentVariables["MORPHBENCH_APP"] = Home;
        return start;
    }

    public void ApplyBootstrap(string output)
    {
        try
        {
            var payload = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(output);
            object protocol;
            if (payload == null || !payload.TryGetValue("protocolVersion", out protocol)
                || !(protocol is int) || (int)protocol != 1) throw new FormatException();
            Absolute(Required(payload, "appHome"));
            string settingsHome = Absolute(Required(payload, "settingsHome"));
            string localeHome = Absolute(Required(payload, "localeHome"));
            string serverApi = Required(payload, "serverApi");
            Uri relative;
            if (serverApi.StartsWith("/") || !serverApi.EndsWith("/") || serverApi.Contains("..")
                || serverApi.Contains("\\") || serverApi.Contains("?") || serverApi.Contains("#")
                || !Uri.TryCreate(serverApi, UriKind.Relative, out relative)) throw new FormatException();
            string statusArgs = Required(payload, "statusArgs");
            string startArgs = Required(payload, "startArgs");
            object environmentArgs;
            string diagnosticArgs = payload.TryGetValue("environmentArgs", out environmentArgs) ? environmentArgs as string : null;
            object rawSettings;
            if (!payload.TryGetValue("settings", out rawSettings)) throw new FormatException();
            var settings = rawSettings as Dictionary<string, object>;
            if (settings == null) throw new FormatException();
            object language;
            Language = settings.TryGetValue("language", out language) ? language as string : null;
            SettingsHome = settingsHome;
            LocaleHome = localeHome;
            ServerApi = serverApi;
            StatusArgs = statusArgs;
            StartArgs = startArgs;
            if (!string.IsNullOrEmpty(diagnosticArgs)) EnvironmentArgs = diagnosticArgs;
            CliTimeoutMs = Positive(settings, "launcherCliTimeoutMs", CliTimeoutMs, 3600000);
            HttpTimeoutMs = Positive(settings, "launcherHttpTimeoutMs", HttpTimeoutMs, 3600000);
            StopWaitMs = Positive(settings, "launcherStopWaitMs", StopWaitMs, 3600000);
            LogMaxChars = Positive(settings, "launcherLogMaxChars", LogMaxChars, 10000000);
        }
        catch (Exception error)
        {
            throw new Exception(Texts.T("launcher.protocolInvalid", "error", error.Message));
        }
    }

    static string Required(Dictionary<string, object> data, string key)
    {
        object value;
        string text = data.TryGetValue(key, out value) ? value as string : null;
        if (string.IsNullOrEmpty(text)) throw new FormatException(key);
        return text;
    }

    static string Absolute(string path)
    {
        bool absolute = path.StartsWith(@"\\") || (path.Length >= 3 && path[1] == ':'
            && (path[2] == '\\' || path[2] == '/'));
        if (!absolute) throw new FormatException();
        return Path.GetFullPath(path);
    }

    static int Positive(Dictionary<string, object> settings, string key, int fallback, int maximum)
    {
        object value;
        if (!settings.TryGetValue(key, out value) || !(value is int)) return fallback;
        int number = (int)value;
        return number > 0 && number <= maximum ? number : fallback;
    }
}

class ChildResult
{
    public string Output = "";
    public string ErrorOutput = "";
    public string StartError;
    public int? ExitCode;
    public bool TimedOut;
    public bool Cancelled;
    public bool Truncated;

    public string Failure(int timeoutMs, int maxChars)
    {
        if (Cancelled) return Texts.T("launcher.cliCancelled");
        if (TimedOut) return Texts.T("launcher.cliTimedOut", "seconds", timeoutMs / 1000.0);
        if (StartError != null) return Texts.T("launcher.cliFailed", "error", StartError);
        if (ExitCode != 0) return Texts.T("launcher.cliExited", "code", ExitCode);
        if (Truncated) return Texts.T("launcher.cliOutputTruncated", "chars", maxChars);
        return null;
    }
}

// Each redirected anonymous pipe has exactly one reader. Peek first, then request only bytes
// already buffered: no synchronous read can wait for EOF held open by a descendant. Keeping
// the UTF-8 decoder across polls preserves characters split between child writes.
sealed class ChildPipe : IDisposable
{
    readonly StreamReader reader;
    readonly SafeFileHandle handle;
    readonly Decoder decoder;
    readonly byte[] bytes = new byte[4096];
    readonly char[] chars;
    bool first = true;
    public bool Done;
    public uint LastReadBytes;

    public ChildPipe(StreamReader reader)
    {
        this.reader = reader;
        handle = ((FileStream)reader.BaseStream).SafeFileHandle;
        Encoding encoding = reader.CurrentEncoding;
        decoder = encoding.GetDecoder();
        chars = new char[encoding.GetMaxCharCount(bytes.Length)];
    }

    public bool Poll(out string text)
    {
        return Poll(out text, (uint)bytes.Length);
    }

    public uint BufferedBytes
    {
        get
        {
            uint available;
            return PeekNamedPipe(handle, IntPtr.Zero, 0, IntPtr.Zero, out available, IntPtr.Zero) ? available : 0;
        }
    }

    public bool Poll(out string text, uint maximum)
    {
        text = "";
        LastReadBytes = 0;
        if (Done) return false;
        uint available;
        if (!PeekNamedPipe(handle, IntPtr.Zero, 0, IntPtr.Zero, out available, IntPtr.Zero))
            return EndOrThrow(Marshal.GetLastWin32Error(), out text);
        if (available == 0) return false;
        uint count;
        if (!ReadFile(handle, bytes, Math.Min(available, Math.Min(maximum, (uint)bytes.Length)), out count, IntPtr.Zero))
            return EndOrThrow(Marshal.GetLastWin32Error(), out text);
        if (count == 0) return EndOrThrow(109, out text);
        LastReadBytes = count;
        text = Decode((int)count, false);
        return true;
    }

    bool EndOrThrow(int error, out string text)
    {
        // Broken/disconnected/closing anonymous pipe: buffered bytes have all been consumed.
        if (error != 109 && error != 232 && error != 233)
            throw new System.ComponentModel.Win32Exception(error);
        Done = true;
        text = Decode(0, true);
        return true;
    }

    string Decode(int count, bool flush)
    {
        int length = decoder.GetChars(bytes, 0, count, chars, 0, flush);
        int offset = first && length > 0 && chars[0] == '\uFEFF' ? 1 : 0;
        if (length > 0) first = false;
        return new string(chars, offset, length - offset);
    }

    public void Dispose()
    {
        try { reader.Dispose(); } catch (Exception) { }
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool PeekNamedPipe(SafeFileHandle pipe, IntPtr buffer, uint size,
        IntPtr read, out uint available, IntPtr remaining);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool ReadFile(SafeFileHandle file, byte[] buffer, uint count,
        out uint read, IntPtr overlapped);
}

class ChildRunner : IDisposable
{
    readonly object sync = new object();
    readonly HashSet<Process> active = new HashSet<Process>();
    volatile bool closing;

    sealed class Capture : IDisposable
    {
        readonly ChildPipe pipe;
        readonly StringBuilder text = new StringBuilder();
        readonly int maximum;
        public bool Truncated;
        public Capture(StreamReader reader, int maximum) { pipe = new ChildPipe(reader); this.maximum = maximum; }
        public bool Done { get { return pipe.Done; } }
        public string Text { get { return text.ToString(); } }
        public bool Poll()
        {
            string chunk;
            bool progress = pipe.Poll(out chunk);
            int keep = Math.Min(chunk.Length, Math.Max(0, maximum - text.Length));
            text.Append(chunk, 0, keep);
            if (keep < chunk.Length) Truncated = true;
            return progress;
        }
        public void Dispose() { pipe.Dispose(); }
    }

    public ChildResult Run(ProcessStartInfo start, int timeoutMs, int maxChars)
    {
        var result = new ChildResult();
        Capture output = null, errors = null;
        using (var process = new Process { StartInfo = start })
        {
            try
            {
                lock (sync)
                {
                    if (closing) { result.Cancelled = true; return result; }
                    if (!process.Start()) throw new InvalidOperationException();
                    active.Add(process);
                }
                output = new Capture(process.StandardOutput, maxChars);
                errors = new Capture(process.StandardError, maxChars);
                var watch = Stopwatch.StartNew();
                while (true)
                {
                    if (closing) { result.Cancelled = true; break; }
                    int remaining = timeoutMs - (int)watch.ElapsedMilliseconds;
                    if (remaining <= 0) { result.TimedOut = true; break; }
                    // One bounded chunk from each pipe keeps a noisy stream from starving its
                    // neighbour or hiding the deadline. Truncated data is still fully drained.
                    bool progress = output.Poll() | errors.Poll();
                    if (process.HasExited && output.Done && errors.Done) break;
                    if (!progress) Thread.Sleep(Math.Min(remaining, 20));
                }
                if (closing) result.Cancelled = true;
                if (result.Cancelled || result.TimedOut) Kill(process);
                if (process.HasExited) result.ExitCode = process.ExitCode;
            }
            catch (Exception error) { result.StartError = error.Message; Kill(process); }
            finally
            {
                if (output != null)
                {
                    result.Output = output.Text;
                    result.Truncated |= output.Truncated;
                    output.Dispose();
                }
                if (errors != null)
                {
                    result.ErrorOutput = errors.Text;
                    result.Truncated |= errors.Truncated;
                    errors.Dispose();
                }
                lock (sync) active.Remove(process);
            }
        }
        return result;
    }

    public static void Kill(Process process)
    {
        try { if (!process.HasExited) process.Kill(); }
        catch (Exception) { }
    }

    public void Dispose()
    {
        lock (sync)
        {
            if (closing) return;
            closing = true;
            foreach (Process process in active) Kill(process);
        }
    }
}

// ---- what the window remembers between runs -------------------------------------------------
class Remembered
{
    readonly string path;
    public string Root = "";

    public Remembered(string home)
    {
        path = Path.Combine(home, "morphbench.launcher.json");
        try
        {
            if (Module.IsFile(path))
            {
                var d = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(path));
                object r;
                if (d != null && d.TryGetValue("root", out r) && r != null) Root = r.ToString();
            }
        }
        catch (Exception) { }
    }

    public void Save()
    {
        try
        {
            var d = new Dictionary<string, object> { { "root", Root ?? "" } };
            File.WriteAllText(path, new JavaScriptSerializer().Serialize(d), new UTF8Encoding(false));
        }
        catch (Exception) { }
    }
}

// ---- the state of the server as the window sees it ------------------------------------------
class ServerStatus
{
    public string State = "free";          // free, ours, busy - the same as ServerLink
    public string Url = "";
    public bool? InsideMo2;                // is the server under MO2?
    public string Root;                    // the root of the server
    public int? Meshes;                    // meshes under the root
    public bool HereInsideMo2;             // is this process under MO2?
    public string HereDataRoot;            // the game Data it sees
    public string Error;                   // why asking failed

    public bool Up { get { return State == "ours"; } }
}

// ---- the client of the server: the same calls the command line makes ------------------------
class Launcher : IDisposable
{
    public readonly string Home;
    public readonly string Python;
    public string Url = "";
    public Action<string> Log = delegate { };
    readonly LaunchContext context;
    readonly ChildRunner children = new ChildRunner();
    readonly object sync = new object();
    readonly HashSet<HttpWebRequest> requests = new HashSet<HttpWebRequest>();
    volatile bool closing;
    Process owned;                          // the server this window brought up
    public Launcher(string home, string python)
        : this(new LaunchContext { Home = home, SettingsHome = home, Python = python }) { }

    public Launcher(LaunchContext context)
    {
        this.context = context;
        Home = context.Home;
        Python = context.Python;
    }

    public bool Owns
    {
        get
        {
            lock (sync)
            {
                try { return owned != null && !owned.HasExited; }
                catch (Exception) { return false; }
            }
        }
    }

    public void Initialize()
    {
        var result = children.Run(context.QueryStart(), context.CliTimeoutMs, context.LogMaxChars);
        string failure = result.Failure(context.CliTimeoutMs, context.LogMaxChars);
        if (failure != null) throw new Exception(failure + "\r\n" + result.ErrorOutput.Trim());
        context.ApplyBootstrap(result.Output);
    }

    // -- the command line of the workbench: the only source of the address and the environment --
    public ServerStatus StatusFromCli()
    {
        var st = new ServerStatus();
        string outp = "";
        try
        {
            outp = RunCli(context.StatusArgs);
            SafeLog(outp.Trim());
            var d = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(FirstJson(outp));
            st.State = Str(d, "state") ?? "free";
            st.Url = Str(d, "url") ?? "";
            st.InsideMo2 = Bool(d, "insideMo2");
            st.Root = Str(d, "root");
            st.Meshes = Int(d, "meshes");
            st.HereInsideMo2 = Bool(d, "hereInsideMo2") ?? false;
            st.HereDataRoot = Str(d, "hereDataRoot");
            Url = st.Url;
        }
        catch (Exception e)
        {
            st.Error = Texts.T("launcher.statusNoAnswer", "error", e.Message) + "\r\n" + outp.Trim();
        }
        return st;
    }

    public string Cli(string args) { return RunCli(args); }

    // The server is already up: do not bring up a second one, hand it the browse root instead.
    // That is done by the same `mb.py serve` call as bringing it up: the rule "free - bring one
    // up, up - connect and hand over the path" lives in the command, in one place, and the
    // window has no branch of its own. From under MO2 the game Data this process sees through
    // usvfs is what gets handed over.
    public string HandOver(string root)
    {
        string args = context.StartArgs;
        if (!string.IsNullOrEmpty(root)) args += " --root " + Module.Quote(root);
        return RunCli(args);
    }

    string RunCli(string args)
    {
        var start = new ProcessStartInfo(Python, Module.Quote(Path.Combine(Home, Module.Script)) + " " + args)
        {
            UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Home,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
        };
        var result = children.Run(start, context.CliTimeoutMs, context.LogMaxChars);
        if (result.ErrorOutput.Trim().Length > 0) SafeLog(result.ErrorOutput.Trim());
        string failure = result.Failure(context.CliTimeoutMs, context.LogMaxChars);
        if (failure != null) throw new Exception(failure + "\r\n" + result.Output.Trim()
            + (result.ErrorOutput.Length == 0 ? "" : "\r\n" + result.ErrorOutput.Trim()));
        return result.Output;
    }

    // -- the server over HTTP: the same thing ServerLink does --
    public ServerStatus Probe(ServerStatus previous)
    {
        var st = new ServerStatus
        {
            Url = Url, HereInsideMo2 = previous.HereInsideMo2, HereDataRoot = previous.HereDataRoot,
        };
        if (string.IsNullOrEmpty(Url)) { st.State = "free"; return st; }
        try
        {
            var env = Get("environment");
            st.State = "ours";
            st.InsideMo2 = Bool(env, "insideMo2");
            st.Root = Str(env, "root");
            try
            {
                var root = Get("root");
                st.Root = Str(root, "root");
                st.Meshes = Int(root, "meshes");
            }
            catch (Exception) { }
        }
        catch (WebException e)
        {
            // The connection goes through but no answer comes back. That does not mean some
            // other program has the port - it means whoever has it cannot be named, and most
            // often it is our own server, locked up walking a large folder.
            st.State = e.Status == WebExceptionStatus.ConnectFailure ? "free"
                : e.Status == WebExceptionStatus.Timeout ? "slow" : "busy";
            if (st.State != "free") st.Error = e.Message;
        }
        catch (Exception e)
        {
            st.State = "busy";
            st.Error = e.Message;
        }
        return st;
    }

    public Dictionary<string, object> SetRoot(string root)
    {
        return Get("root?root=" + Uri.EscapeDataString(root));
    }

    public void Start(string root)
    {
        lock (sync)
        {
            if (closing) throw new OperationCanceledException(Texts.T("launcher.cliCancelled"));
            if (Owns) return;
            if (owned != null) { owned.Dispose(); owned = null; }
            string args = Module.Quote(Path.Combine(Home, Module.Script)) + " " + context.StartArgs;
            // The server leaves with this window BY ITSELF. Closing peacefully stops it anyway, but
            // a window killed outright has no time for that, and with nothing watching the parent an
            // invisible server would be left behind: the port taken, the file system MO2 handed it
            // long out of date, and the next run would quietly connect to exactly that one.
            args += " --parent " + Process.GetCurrentProcess().Id.ToString(CultureInfo.InvariantCulture);
            if (!string.IsNullOrEmpty(root)) args += " --root " + Module.Quote(root);
            var start = new ProcessStartInfo(Python, args)
            {
                UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Home,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
            };
            SafeLog("> " + Python + " " + args);
            var process = new Process { StartInfo = start, EnableRaisingEvents = true };
            process.Exited += (s, e) => SafeLog(Texts.T("launcher.serverExited", "code", SafeExitCode(process)));
            try
            {
                if (!process.Start()) throw new InvalidOperationException();
                owned = process;
                ReadServerOutput(process);
            }
            catch (Exception)
            {
                ChildRunner.Kill(process);
                process.Dispose();
                owned = null;
                throw;
            }
        }
    }

    static string SafeExitCode(Process p)
    {
        try { return p.ExitCode.ToString(); } catch (Exception) { return "?"; }
    }

    void ReadServerOutput(Process process)
    {
        // Capture streams before the worker starts, while Start still owns the lifecycle lock.
        var output = new ChildPipe(process.StandardOutput);
        var errors = new ChildPipe(process.StandardError);
        new Thread(delegate()
        {
            try
            {
                var outputLine = new StringBuilder();
                var errorLine = new StringBuilder();
                while (!closing)
                {
                    if (process.HasExited)
                    {
                        // Snapshot the remaining buffered bytes once. A descendant that keeps
                        // writing may not extend the lifetime of an exited server's readers.
                        DrainServerSnapshot(output, outputLine);
                        DrainServerSnapshot(errors, errorLine);
                        break;
                    }
                    string chunk;
                    bool progress = output.Poll(out chunk);
                    ServerLogChunk(outputLine, chunk);
                    progress |= errors.Poll(out chunk);
                    ServerLogChunk(errorLine, chunk);
                    if (output.Done && errors.Done) break;
                    if (!progress) Thread.Sleep(20);
                }
                if (outputLine.Length > 0) SafeLog(outputLine.ToString().TrimEnd('\r'));
                if (errorLine.Length > 0) SafeLog(errorLine.ToString().TrimEnd('\r'));
            }
            catch (Exception) { } // Closing may dispose the process between polls.
            finally { output.Dispose(); errors.Dispose(); }
        }) { IsBackground = true }.Start();
    }

    void DrainServerSnapshot(ChildPipe pipe, StringBuilder line)
    {
        uint remaining = pipe.BufferedBytes;
        // Poll once even at zero to flush an incomplete final UTF-8 character on EOF.
        do
        {
            string chunk;
            pipe.Poll(out chunk, Math.Max(remaining, 1));
            ServerLogChunk(line, chunk);
            if (pipe.LastReadBytes == 0 || remaining <= pipe.LastReadBytes) break;
            remaining -= pipe.LastReadBytes;
        } while (!closing);
    }

    void ServerLogChunk(StringBuilder line, string chunk)
    {
        foreach (char value in chunk)
        {
            if (value == '\n' || line.Length >= context.LogMaxChars)
            {
                SafeLog(line.ToString().TrimEnd('\r'));
                line.Length = 0;
            }
            if (value != '\n') line.Append(value);
        }
    }

    public void Stop()
    {
        Process process;
        lock (sync) { process = owned; }
        Stop(process, false);
        lock (sync) { if (owned == process) owned = null; }
    }

    void Stop(Process process, bool disposing)
    {
        string shutdown = "shutdown";
        if (disposing)
        {
            try
            {
                if (process == null || process.HasExited) { if (process != null) process.Dispose(); return; }
                // Start is idempotent: a server may have appeared after the last status.
                // Only the process we actually spawned may honor a close-time shutdown.
                shutdown += "?pid=" + process.Id.ToString(CultureInfo.InvariantCulture);
            }
            catch (Exception) { if (process != null) process.Dispose(); return; }
        }
        var watch = Stopwatch.StartNew();
        try
        {
            Get(shutdown, context.StopWaitMs, disposing);
        }
        catch (Exception e)
        {
            SafeLog(Texts.T("launcher.stopFailed", "error", e.Message));
        }
        if (process == null) return;
        try
        {
            int remaining = Math.Max(0, context.StopWaitMs - (int)watch.ElapsedMilliseconds);
            if (!process.WaitForExit(remaining))
            {
                SafeLog(Texts.T("launcher.killed", "seconds", context.StopWaitMs / 1000.0));
                ChildRunner.Kill(process);
            }
        }
        catch (Exception) { ChildRunner.Kill(process); }
        finally { process.Dispose(); }
    }

    void SafeLog(string text)
    {
        try { Log(text); } catch (Exception) { }
    }

    public void Dispose()
    {
        Process process;
        lock (sync)
        {
            if (closing) return;
            closing = true;
            process = owned;
            owned = null;
            foreach (HttpWebRequest request in requests) request.Abort();
        }
        children.Dispose();
        // An attached server belongs to its original launcher; only our child leaves here.
        if (process != null) Stop(process, true);
    }

    public void OpenPage()
    {
        if (string.IsNullOrEmpty(Url)) return;
        Process.Start(new ProcessStartInfo(Url) { UseShellExecute = true });
    }

    Dictionary<string, object> Get(string path)
    {
        return Get(path, context.HttpTimeoutMs, false);
    }

    Dictionary<string, object> Get(string path, int timeout, bool disposing)
    {
        var req = (HttpWebRequest)WebRequest.Create(Url + context.ServerApi + path);
        req.Timeout = timeout;
        req.ReadWriteTimeout = timeout;
        req.Proxy = null;                      // the address is local, a proxy from the environment is no use
        lock (sync)
        {
            if (closing && !disposing) throw new OperationCanceledException(Texts.T("launcher.cliCancelled"));
            requests.Add(req);
        }
        // Timeout alone stops waiting for headers; ReadWriteTimeout is per read. The same
        // deadline must also stop a peer that keeps a response body/pipe alive indefinitely.
        int expired = 0;
        var deadline = new System.Threading.Timer(delegate(object ignored)
        {
            Interlocked.Exchange(ref expired, 1);
            try { req.Abort(); } catch (Exception) { }
        }, null, timeout, Timeout.Infinite);
        try
        {
            using (var resp = (HttpWebResponse)req.GetResponse())
            {
                string server = resp.Headers["Server"] ?? "";
                if (!server.StartsWith("morphbench/")) throw new Exception(Texts.T("launcher.notMorphbench", "url", Url));
                return new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(ReadAll(resp));
            }
        }
        catch (WebException e)
        {
            if (Interlocked.CompareExchange(ref expired, 0, 0) != 0)
            {
                if (e.Response != null) e.Response.Close();
                throw new WebException(e.Message, e, WebExceptionStatus.Timeout, null);
            }
            var resp = e.Response as HttpWebResponse;
            if (resp == null) throw;
            using (resp)
            {
                // A refusal by the server, in its own words: {"error": ...}
                string text = ReadAll(resp);
                string message = text;
                try
                {
                    var d = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(text);
                    object err;
                    if (d != null && d.TryGetValue("error", out err) && err != null) message = err.ToString();
                }
                catch (Exception) { }
                throw new Exception(message);
            }
        }
        catch (Exception error)
        {
            if (Interlocked.CompareExchange(ref expired, 0, 0) != 0)
                throw new WebException(error.Message, error, WebExceptionStatus.Timeout, null);
            throw;
        }
        finally
        {
            deadline.Dispose();
            lock (sync) requests.Remove(req);
        }
    }

    static string ReadAll(HttpWebResponse resp)
    {
        using (var r = new StreamReader(resp.GetResponseStream(), Encoding.UTF8)) return r.ReadToEnd();
    }

    static string FirstJson(string text)
    {
        int i = text.IndexOf('{');
        int j = text.LastIndexOf('}');
        if (i < 0 || j < i) throw new Exception(Texts.T("launcher.noJson"));
        return text.Substring(i, j - i + 1);
    }

    static string Str(Dictionary<string, object> d, string key)
    {
        object v;
        return d != null && d.TryGetValue(key, out v) && v != null ? v.ToString() : null;
    }

    static bool? Bool(Dictionary<string, object> d, string key)
    {
        object v;
        if (d == null || !d.TryGetValue(key, out v) || v == null) return null;
        return v is bool ? (bool)v : (bool?)null;
    }

    static int? Int(Dictionary<string, object> d, string key)
    {
        object v;
        if (d == null || !d.TryGetValue(key, out v) || v == null) return null;
        try { return Convert.ToInt32(v); } catch (Exception) { return null; }
    }
}

// Every completion, including process output, goes through this one lifetime gate. Checking
// before BeginInvoke alone is insufficient: closing can destroy the handle between the two.
class UiDispatcher
{
    readonly Control control;
    readonly int uiThread = Thread.CurrentThread.ManagedThreadId;
    volatile bool closing;
    public UiDispatcher(Control control) { this.control = control; }
    public bool Closing { get { return closing; } }
    public void Close() { closing = true; }
    public bool Post(Action action)
    {
        if (closing || control.IsDisposed || control.Disposing || !control.IsHandleCreated) return false;
        try
        {
            Action guarded = delegate
            {
                if (!closing && !control.IsDisposed && !control.Disposing) action();
            };
            if (Thread.CurrentThread.ManagedThreadId == uiThread) guarded();
            else control.BeginInvoke(guarded);
            return true;
        }
        catch (InvalidOperationException) { return false; }
    }
}

// ---- the window -----------------------------------------------------------------------------
class MainForm : Form
{
    readonly Options options;
    readonly LaunchContext context;
    readonly UiDispatcher ui;
    readonly object logSync = new object();
    readonly StringBuilder pendingLog = new StringBuilder();
    bool logQueued;
    Launcher launcher;
    Remembered remembered;
    ServerStatus status = new ServerStatus();
    bool probing;
    bool ready;
    bool warnedForeign;                     // the warning about a server outside MO2 - once
    int waitTicks;                          // how many more seconds to wait for our own server
    //: What the parts of the environment line are strung together with. Punctuation, not a
    //: text: a translator should not have to carry a separator through every one of them.
    const string Sep = " · ";

    readonly Label stateLabel = new Label();
    readonly Label envLabel = new Label();
    readonly Label rootLabel = new Label();
    readonly TextBox rootBox = new TextBox();
    readonly Button browseButton = new Button();
    readonly Button applyButton = new Button();
    readonly Button startButton = new Button();
    readonly Button stopButton = new Button();
    readonly Button pageButton = new Button();
    readonly Button refreshButton = new Button();
    readonly TextBox logBox = new TextBox();
    readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();

    public MainForm(Options options) : this(options, LaunchContext.Discover(options.Home)) { }

    public MainForm(Options options, LaunchContext context)
    {
        this.options = options;
        this.context = context;
        ui = new UiDispatcher(this);
        Text = "morphbench";
        // The title icon is set explicitly: /win32icon gives an icon to the FILE (explorer, the
        // taskbar), and a WinForms window without this draws its own default one. The same .ico
        // is taken, embedded as a resource - it holds every size, and Windows picks the 16 point
        // one for the title itself instead of shrinking the large one.
        try
        {
            using (var s = Assembly.GetExecutingAssembly().GetManifestResourceStream("morphbench.ico"))
                if (s != null) Icon = new Icon(s);
        }
        catch (Exception) { }
        if (Icon == null)
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); }
            catch (Exception) { }
        Font = new Font("Segoe UI", 9f);
        // The sizes are given for 96 dpi and multiply themselves by the scale of the screen:
        // WinForms scales fonts and buttons by dpi, but not the size of the window.
        AutoScaleMode = AutoScaleMode.None;
        float k;
        using (var g = CreateGraphics()) k = g.DpiX / 96f;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size((int)(680 * k), (int)(420 * k));
        MinimumSize = new Size((int)(560 * k), (int)(320 * k));
        Build();
        Load += OnLoad;
        FormClosing += OnClosing;
    }

    void Build()
    {
        var grid = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(10), ColumnCount = 1 };
        grid.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        grid.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        grid.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        grid.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        grid.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));

        stateLabel.AutoSize = true;
        stateLabel.Font = new Font(Font, FontStyle.Bold);
        stateLabel.Margin = new Padding(0, 0, 0, 2);
        envLabel.AutoSize = true;
        envLabel.ForeColor = SystemColors.GrayText;
        envLabel.Margin = new Padding(0, 0, 0, 8);
        // A long root must not push the window wider: the labels wrap at its width.
        grid.SizeChanged += (s, e) =>
        {
            int w = Math.Max(100, grid.ClientSize.Width - grid.Padding.Horizontal);
            stateLabel.MaximumSize = new Size(w, 0);
            envLabel.MaximumSize = new Size(w, 0);
        };

        var rootRow = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 4, Margin = new Padding(0, 0, 0, 8) };
        rootRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        rootRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
        rootRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        rootRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        rootLabel.Text = Texts.T("launcher.rootLabel");
        rootLabel.AutoSize = true;
        rootLabel.Anchor = AnchorStyles.Left;
        rootLabel.Margin = new Padding(0, 6, 6, 0);
        rootBox.Anchor = AnchorStyles.Left | AnchorStyles.Right;
        browseButton.Text = Texts.T("launcher.browseButton");
        browseButton.AutoSize = true;
        browseButton.Click += (s, e) => Browse();
        applyButton.Text = Texts.T("launcher.apply");
        applyButton.AutoSize = true;
        applyButton.Click += (s, e) => Apply();
        rootRow.Controls.Add(rootLabel, 0, 0);
        rootRow.Controls.Add(rootBox, 1, 0);
        rootRow.Controls.Add(browseButton, 2, 0);
        rootRow.Controls.Add(applyButton, 3, 0);

        var buttons = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, Margin = new Padding(0, 0, 0, 8) };
        startButton.Text = Texts.T("launcher.start");
        stopButton.Text = Texts.T("launcher.stop");
        pageButton.Text = Texts.T("launcher.openPage");
        refreshButton.Text = Texts.T("launcher.refresh");
        foreach (var b in new[] { startButton, stopButton, pageButton, refreshButton })
        {
            b.AutoSize = true;
            b.Padding = new Padding(6, 2, 6, 2);
            buttons.Controls.Add(b);
        }
        startButton.Click += (s, e) => StartServer();
        stopButton.Click += (s, e) => StopServer();
        pageButton.Click += (s, e) => OpenPage();
        refreshButton.Click += (s, e) => Refresh(true);

        logBox.Multiline = true;
        logBox.ReadOnly = true;
        logBox.ScrollBars = ScrollBars.Vertical;
        logBox.Dock = DockStyle.Fill;
        logBox.Font = new Font("Consolas", 9f);
        logBox.BackColor = SystemColors.Window;

        grid.Controls.Add(stateLabel, 0, 0);
        grid.Controls.Add(envLabel, 0, 1);
        grid.Controls.Add(rootRow, 0, 2);
        grid.Controls.Add(buttons, 0, 3);
        grid.Controls.Add(logBox, 0, 4);
        Controls.Add(grid);

        // The state is asked for by the button and after every action. The timer is needed only
        // while we wait for a server we brought up to answer - and goes out once it has.
        timer.Interval = 1000;
        timer.Tick += (s, e) => { if (--waitTicks <= 0) timer.Stop(); Refresh(false); };
    }

    // -- the life of the window --
    void OnLoad(object sender, EventArgs e)
    {
        string home = context.Home;
        if (home == null)
        {
            Fail(Texts.T("launcher.noModule", "script", Module.Script));
            return;
        }
        string python = context.Python;
        if (python == null)
        {
            Fail(Texts.T("launcher.noPython"));
            return;
        }
        launcher = new Launcher(context) { Log = Append };
        remembered = new Remembered(home);
        stateLabel.Text = Texts.T("launcher.asking");
        SetButtons(false);
        ThreadPool.QueueUserWorkItem(_ =>
        {
            string failure = null;
            try { launcher.Initialize(); }
            catch (Exception error) { failure = error.Message; }
            ui.Post(() => AfterContext(failure));
        });
    }

    void AfterContext(string failure)
    {
        if (failure != null)
        {
            Append(Texts.T("launcher.module", "path", context.Home));
            Append(Texts.T("launcher.python", "path", context.Python));
            Fail(failure);
            return;
        }
        Texts.Configure(context);
        Append(Texts.T("launcher.module", "path", context.Home));
        Append(Texts.T("launcher.python", "path", context.Python));
        rootLabel.Text = Texts.T("launcher.rootLabel");
        browseButton.Text = Texts.T("launcher.browseButton");
        applyButton.Text = Texts.T("launcher.apply");
        startButton.Text = Texts.T("launcher.start");
        stopButton.Text = Texts.T("launcher.stop");
        pageButton.Text = Texts.T("launcher.openPage");
        refreshButton.Text = Texts.T("launcher.refresh");
        stateLabel.Text = Texts.T("launcher.asking");
        ThreadPool.QueueUserWorkItem(_ =>
        {
            ServerStatus st;
            try { st = launcher.StatusFromCli(); }
            catch (Exception error) { st = new ServerStatus { Error = Texts.T("launcher.statusNoAnswer", "error", error.Message) }; }
            ui.Post(() => AfterFirstStatus(st));
        });
    }

    void AfterFirstStatus(ServerStatus st)
    {
        ready = true;
        status = st;
        if (st.Error != null) Append(st.Error);
        // Under MO2 the root is the game Data this process sees; outside MO2 it is the root of
        // a server that is already up, and if there is no server - the one we remember.
        rootBox.Text = !string.IsNullOrEmpty(options.Root) ? options.Root
            : st.HereInsideMo2 ? (st.HereDataRoot ?? "")
            : (st.Up && !string.IsNullOrEmpty(st.Root)) ? st.Root : remembered.Root;
        Show(st);
        if (options.Start) StartServer();
    }

    void OnClosing(object sender, FormClosingEventArgs e)
    {
        timer.Stop();
        ui.Close();
        // The server this window brought up leaves with it: otherwise an invisible process
        // would be left under MO2, and MO2 would wait for it.
        if (launcher != null) launcher.Dispose();
    }

    void Fail(string message)
    {
        stateLabel.Text = Texts.T("launcher.failLabel", "message", message);
        stateLabel.ForeColor = Color.Firebrick;
        SetButtons(false);
        Append(message);
    }

    // -- actions: every one of them a call to the server, the same call the command line makes --
    void StartServer()
    {
        if (launcher == null || ui.Closing || !ready) return;
        if (status.Up)
        {
            HandOver();
            return;
        }
        if (status.State == "busy")
        {
            Append(Texts.T("launcher.portTaken", "url", status.Url));
            return;
        }
        string root = rootBox.Text.Trim();
        try
        {
            launcher.Start(root.Length > 0 ? root : null);
        }
        catch (Exception e)
        {
            Append(Texts.T("launcher.startFailed", "error", e.Message));
            return;
        }
        if (!status.HereInsideMo2 && root.Length > 0) { remembered.Root = root; remembered.Save(); }
        stateLabel.Text = Texts.T("launcher.starting");
        // The page is opened as soon as the server answers - see Refresh.
        pendingOpen = options.Start;
        options.Start = false;
        waitTicks = 60;
        timer.Start();
        Refresh(true);
    }

    bool pendingOpen;

    /// The server is already up - connect to it and hand over the browse root. The call is the
    /// same as the one that brings it up, which makes pressing "start" idempotent: server up or
    /// not, the window does one and the same thing, and it is the command that tells them apart.
    void HandOver()
    {
        string root = rootBox.Text.Trim();
        bool open = options.Start;
        options.Start = false;
        stateLabel.Text = Texts.T("launcher.handingOver");
        SetButtons(false);
        ThreadPool.QueueUserWorkItem(_ =>
        {
            string outp;
            try { outp = launcher.HandOver(root); }
            catch (Exception e) { outp = Texts.T("launcher.handOverFailed", "error", e.Message); }
            ui.Post(() =>
            {
                Append(outp.Trim().Length > 0 ? outp.Trim() : Texts.T("launcher.alreadyUp", "url", status.Url));
                if (open) OpenPage();
                Refresh(true);
            });
        });
    }

    void StopServer()
    {
        if (launcher == null || !status.Up) { Append(Texts.T("launcher.notUp")); return; }
        stateLabel.Text = Texts.T("launcher.stopping");
        SetButtons(false);
        ThreadPool.QueueUserWorkItem(_ =>
        {
            string error = null;
            try { launcher.Stop(); }
            catch (Exception failure) { error = Texts.T("launcher.stopFailed", "error", failure.Message); }
            ui.Post(() => { Append(error ?? Texts.T("launcher.stopped", "url", status.Url)); Refresh(true); });
        });
    }

    void OpenPage()
    {
        if (launcher == null) return;
        if (!status.Up) { Append(Texts.T("launcher.noPageNoServer")); return; }
        try { launcher.OpenPage(); Append(Texts.T("launcher.page", "url", status.Url)); }
        catch (Exception e) { Append(Texts.T("launcher.pageFailed", "error", e.Message)); }
    }

    void Browse()
    {
        using (var dlg = new FolderBrowserDialog())
        {
            dlg.Description = Texts.T("launcher.browseHint");
            dlg.ShowNewFolderButton = false;
            if (rootBox.Text.Trim().Length > 0 && Directory.Exists(rootBox.Text.Trim())) dlg.SelectedPath = rootBox.Text.Trim();
            if (dlg.ShowDialog(this) == DialogResult.OK) rootBox.Text = dlg.SelectedPath;
        }
    }

    void Apply()
    {
        if (launcher == null) return;
        string root = rootBox.Text.Trim();
        if (root.Length == 0) { Append(Texts.T("launcher.nameFolder")); return; }
        if (!status.HereInsideMo2) { remembered.Root = root; remembered.Save(); }
        if (!status.Up) { Append(Texts.T("launcher.rootRemembered")); return; }
        stateLabel.Text = Texts.T("launcher.walking", "root", root);
        SetButtons(false);
        ThreadPool.QueueUserWorkItem(_ =>
        {
            string message;
            try
            {
                var got = launcher.SetRoot(root);
                object meshes;
                got.TryGetValue("meshes", out meshes);
                message = Texts.T("launcher.browsing", "root", root, "meshes", meshes);
            }
            catch (Exception e)
            {
                message = Texts.T("launcher.serverRefused", "error", e.Message);
            }
            ui.Post(() => { Append(message); Refresh(true); });
        });
    }

    // -- the state: asked for in the background, shown in the window --
    void Refresh(bool now)
    {
        if (launcher == null || probing || ui.Closing || !ready) return;
        probing = true;
        var previous = status;
        ThreadPool.QueueUserWorkItem(_ =>
        {
            ServerStatus st;
            try { st = launcher.Probe(previous); }
            catch (Exception e) { st = new ServerStatus { State = "busy", Error = e.Message, Url = launcher.Url }; }
            ui.Post(() =>
            {
                probing = false;
                bool cameUp = st.Up && !previous.Up;
                status = st;
                Show(st);
                if (st.Up) timer.Stop();
                if (cameUp && pendingOpen) { pendingOpen = false; OpenPage(); }
            });
        });
    }

    void Show(ServerStatus st)
    {
        string state;
        Color colour;
        switch (st.State)
        {
            case "ours":
                state = Texts.T("launcher.stateUp", "url", st.Url, "owner",
                                Texts.T(launcher != null && launcher.Owns ? "launcher.ownerHere" : "launcher.ownerOther"));
                colour = Color.ForestGreen;
                break;
            case "busy":
                state = Texts.T("launcher.stateBusy", "url", st.Url);
                colour = Color.Firebrick;
                break;
            case "slow":
                state = Texts.T("launcher.stateSlow", "url", st.Url);
                colour = Color.DarkOrange;
                break;
            default:
                state = Texts.T("launcher.stateDown", "url", st.Url);
                colour = SystemColors.ControlText;
                break;
        }
        stateLabel.Text = Texts.T("launcher.serverIs", "state", state);
        stateLabel.ForeColor = colour;
        var env = new StringBuilder();
        env.Append(Texts.T("launcher.envHere", "yesno", YesNo(st.HereInsideMo2)));
        if (!string.IsNullOrEmpty(st.HereDataRoot))
            env.Append(Sep).Append(Texts.T("launcher.envData", "path", st.HereDataRoot));
        if (st.Up)
        {
            env.Append(Sep).Append(Texts.T("launcher.envServer", "yesno", YesNo(st.InsideMo2 == true)));
            env.Append(Sep).Append(Texts.T("launcher.envRoot", "root",
                string.IsNullOrEmpty(st.Root) ? Texts.T("launcher.rootUnset") : st.Root));
            if (st.Meshes != null) env.Append(Texts.T("launcher.envMeshes", "meshes", st.Meshes));
        }
        envLabel.Text = env.ToString();
        if (st.Up && st.HereInsideMo2 && st.InsideMo2 == false)
        {
            if (!warnedForeign) Append(Texts.T("launcher.foreignServer"));
            warnedForeign = true;
        }
        else if (!st.Up) warnedForeign = false;
        SetButtons(true);
        startButton.Enabled = !st.Up && st.State != "busy" && st.State != "slow";
        stopButton.Enabled = st.Up;
        pageButton.Enabled = st.Up;
        applyButton.Enabled = true;
    }

    static string YesNo(bool on)
    {
        return Texts.T(on ? "launcher.yes" : "launcher.no");
    }

    void SetButtons(bool on)
    {
        startButton.Enabled = stopButton.Enabled = pageButton.Enabled = applyButton.Enabled = refreshButton.Enabled = on;
    }

    void Append(string line)
    {
        if (ui.Closing) return;
        lock (logSync)
        {
            int maximum = context.LogMaxChars;
            string text = line ?? "";
            if (text.Length > maximum) text = text.Substring(text.Length - maximum);
            pendingLog.Append(text).Append(Environment.NewLine);
            if (pendingLog.Length > maximum) pendingLog.Remove(0, pendingLog.Length - maximum);
            if (logQueued) return;
            logQueued = true;
        }
        if (!ui.Post(FlushLog))
            lock (logSync) { pendingLog.Length = 0; logQueued = false; }
    }

    void FlushLog()
    {
        string text;
        lock (logSync)
        {
            text = pendingLog.ToString();
            pendingLog.Length = 0;
            logQueued = false;
        }
        if (logBox.TextLength + text.Length > context.LogMaxChars) logBox.Clear();
        logBox.AppendText(text);
    }
}
