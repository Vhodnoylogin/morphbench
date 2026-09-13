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
// MORPHBENCH_PYTHON variable, the "python" key in morphbench.json, python.exe on PATH (bar the
// Windows store stub), the PythonCore registry key, or the py.exe launcher.
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
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        var options = Options.Parse(args);
        if (options.Diag)
        {
            // Diagnostics without a window: what python sees from under MO2 - into a file
            // beside the exe. That is how the VFS is checked with nobody at the screen:
            // started through MO2, the answer is in the file.
            string home = Module.FindHome(options.Home);
            string python = home == null ? null : Module.FindPython(home);
            string text = home == null ? Texts.T("launcher.diagNoModule")
                : python == null ? Texts.T("launcher.diagNoPython")
                : new Launcher(home, python).Cli("env --json") + "\n---catalog---\n"
                  + new Launcher(home, python).Cli("render --entry assets/malebodywerewolf_0.nif --size 300x300 --colliders --out morphbench.diag.png --json");
            File.WriteAllText(Path.Combine(home ?? AppDomain.CurrentDomain.BaseDirectory, "morphbench.diag.json"),
                              text, new UTF8Encoding(false));
            return;
        }
        Application.Run(new MainForm(options));
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

    static Texts()
    {
        try
        {
            string home = Home();
            string folder = Path.Combine(home, "locale");
            Read(Path.Combine(folder, Base), fallback);
            string language = Wanted(home);
            if (language != Base) Read(Path.Combine(folder, language), chosen);
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
        string filled = Field.Replace(text, delegate(Match m)
        {
            string value;
            if (values.TryGetValue(m.Groups[1].Value, out value)) return value;
            whole = false;
            return m.Value;
        });
        if (whole) return filled;
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
    static string Wanted(string home)
    {
        string code = Clean(Environment.GetEnvironmentVariable(Env));
        if (code.Length == 0) code = Clean(FromConfig(Path.Combine(home, "morphbench.json")));
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

    static string FromConfig(string path)
    {
        try
        {
            if (!File.Exists(path)) return "";
            var d = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(path));
            object value;
            if (d != null && d.TryGetValue("language", out value) && value != null) return value.ToString();
        }
        catch (Exception) { }
        return "";
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

    /// Where the locale folder is. Beside the exe as a rule - the module and morphbench.exe
    /// live in one folder - but a window started from elsewhere is told where the module is,
    /// and the texts have to follow it there.
    static string Home()
    {
        var candidates = new List<string>();
        candidates.Add(AppDomain.CurrentDomain.BaseDirectory);
        string named = Environment.GetEnvironmentVariable("MORPHBENCH_HOME");
        if (!string.IsNullOrEmpty(named)) candidates.Add(named);
        candidates.Add(Directory.GetCurrentDirectory());
        foreach (string dir in candidates)
        {
            try
            {
                string full = Path.GetFullPath(dir);
                if (Directory.Exists(Path.Combine(full, "locale"))) return full;
            }
            catch (Exception) { }
        }
        return AppDomain.CurrentDomain.BaseDirectory;
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
                if (File.Exists(Path.Combine(full, Script))) return full;
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
        string path = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (string dir in path.Split(Path.PathSeparator))
        {
            if (dir.Trim().Length == 0) continue;
            // The Windows store stub lives in WindowsApps: with no real python behind it, it
            // opens the store instead of running anything.
            if (dir.IndexOf("WindowsApps", StringComparison.OrdinalIgnoreCase) >= 0) continue;
            string exe = Path.Combine(dir.Trim(), "python.exe");
            if (IsFile(exe)) return exe;
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
            // The settings are read by the workbench itself; only one key is needed here. The
            // path is in double quotes with its backslashes escaped - Regex.Unescape gives
            // them back.
            var m = Regex.Match(File.ReadAllText(json), "\"python\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"");
            return m.Success ? Regex.Unescape(m.Groups[1].Value) : null;
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
        try { return !string.IsNullOrEmpty(path) && File.Exists(path); }
        catch (Exception) { return false; }
    }

    public static string Quote(string s)
    {
        return "\"" + s.Replace("\"", "\\\"") + "\"";
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
            if (File.Exists(path))
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
class Launcher
{
    public readonly string Home;
    public readonly string Python;
    public string Url = "";
    public Action<string> Log = delegate { };
    readonly JavaScriptSerializer js = new JavaScriptSerializer();
    Process owned;                          // the server this window brought up
    //: How long a server is given to leave on its own before it is killed.
    const int StopWaitMs = 5000;

    public Launcher(string home, string python)
    {
        Home = home;
        Python = python;
    }

    public bool Owns { get { return owned != null && !owned.HasExited; } }

    // -- the command line of the workbench: the only source of the address and the environment --
    public ServerStatus StatusFromCli()
    {
        var st = new ServerStatus();
        string outp = RunCli("serve --status --json");
        Log(outp.Trim());                      // everything the workbench knows about the environment, verbatim
        try
        {
            var d = js.Deserialize<Dictionary<string, object>>(FirstJson(outp));
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
        string args = "serve --no-browser";
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
        using (var p = Process.Start(start))
        {
            // Both pipes are read at once: read one after the other, and a child that has
            // filled the second one (a long traceback) stops on the write, so the first pipe
            // never closes - the window would hang exactly when the diagnostics are wanted.
            var err = p.StandardError.ReadToEndAsync();
            string o = p.StandardOutput.ReadToEnd();
            p.WaitForExit();
            return o + err.Result;
        }
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
            var env = Get("api/environment");
            st.State = "ours";
            st.InsideMo2 = Bool(env, "insideMo2");
            st.Root = Str(env, "root");
            try
            {
                var root = Get("api/root");
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
        return Get("api/root?root=" + Uri.EscapeDataString(root));
    }

    public void Start(string root)
    {
        if (Owns) return;
        string args = Module.Quote(Path.Combine(Home, Module.Script)) + " serve --no-browser --json";
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
        Log("> " + Python + " " + args);
        owned = Process.Start(start);
        owned.EnableRaisingEvents = true;
        owned.OutputDataReceived += (s, e) => { if (e.Data != null) Log(e.Data); };
        owned.ErrorDataReceived += (s, e) => { if (e.Data != null) Log(e.Data); };
        owned.Exited += (s, e) => Log(Texts.T("launcher.serverExited", "code", SafeExitCode(owned)));
        owned.BeginOutputReadLine();
        owned.BeginErrorReadLine();
    }

    static string SafeExitCode(Process p)
    {
        try { return p.ExitCode.ToString(); } catch (Exception) { return "?"; }
    }

    public void Stop()
    {
        try
        {
            Get("api/shutdown");
        }
        catch (Exception e)
        {
            Log(Texts.T("launcher.stopFailed", "error", e.Message));
        }
        var p = owned;
        if (p == null) return;
        if (!p.WaitForExit(StopWaitMs))
        {
            Log(Texts.T("launcher.killed", "seconds", StopWaitMs / 1000));
            try { p.Kill(); } catch (Exception) { }
        }
        owned = null;
    }

    public void OpenPage()
    {
        if (string.IsNullOrEmpty(Url)) return;
        Process.Start(new ProcessStartInfo(Url) { UseShellExecute = true });
    }

    Dictionary<string, object> Get(string path)
    {
        var req = (HttpWebRequest)WebRequest.Create(Url + path);
        req.Timeout = 30000;                   // walking a large folder can take seconds
        req.Proxy = null;                      // the address is local, a proxy from the environment is no use
        try
        {
            using (var resp = (HttpWebResponse)req.GetResponse())
            {
                string server = resp.Headers["Server"] ?? "";
                if (!server.StartsWith("morphbench/")) throw new Exception(Texts.T("launcher.notMorphbench", "url", Url));
                return js.Deserialize<Dictionary<string, object>>(ReadAll(resp));
            }
        }
        catch (WebException e)
        {
            var resp = e.Response as HttpWebResponse;
            if (resp == null) throw;
            // A refusal by the server, in its own words: {"error": ...}
            string text = ReadAll(resp);
            string message = text;
            try
            {
                var d = js.Deserialize<Dictionary<string, object>>(text);
                object err;
                if (d != null && d.TryGetValue("error", out err) && err != null) message = err.ToString();
            }
            catch (Exception) { }
            throw new Exception(message);
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

// ---- the window -----------------------------------------------------------------------------
class MainForm : Form
{
    readonly Options options;
    Launcher launcher;
    Remembered remembered;
    ServerStatus status = new ServerStatus();
    bool probing;
    bool warnedForeign;                     // the warning about a server outside MO2 - once
    int waitTicks;                          // how many more seconds to wait for our own server
    //: What the parts of the environment line are strung together with. Punctuation, not a
    //: text: a translator should not have to carry a separator through every one of them.
    const string Sep = " · ";

    readonly Label stateLabel = new Label();
    readonly Label envLabel = new Label();
    readonly TextBox rootBox = new TextBox();
    readonly Button browseButton = new Button();
    readonly Button applyButton = new Button();
    readonly Button startButton = new Button();
    readonly Button stopButton = new Button();
    readonly Button pageButton = new Button();
    readonly Button refreshButton = new Button();
    readonly TextBox logBox = new TextBox();
    readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();

    public MainForm(Options options)
    {
        this.options = options;
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
        var rootLabel = new Label { Text = Texts.T("launcher.rootLabel"), AutoSize = true, Anchor = AnchorStyles.Left, Margin = new Padding(0, 6, 6, 0) };
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
        string home = Module.FindHome(options.Home);
        if (home == null)
        {
            Fail(Texts.T("launcher.noModule", "script", Module.Script));
            return;
        }
        string python = Module.FindPython(home);
        if (python == null)
        {
            Fail(Texts.T("launcher.noPython"));
            return;
        }
        launcher = new Launcher(home, python) { Log = Append };
        remembered = new Remembered(home);
        Append(Texts.T("launcher.module", "path", home));
        Append(Texts.T("launcher.python", "path", python));
        stateLabel.Text = Texts.T("launcher.asking");
        SetButtons(false);
        ThreadPool.QueueUserWorkItem(_ =>
        {
            var st = launcher.StatusFromCli();
            BeginInvoke((Action)(() => AfterFirstStatus(st)));
        });
    }

    void AfterFirstStatus(ServerStatus st)
    {
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
        // The server this window brought up leaves with it: otherwise an invisible process
        // would be left under MO2, and MO2 would wait for it.
        if (launcher != null && launcher.Owns) launcher.Stop();
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
        if (launcher == null) return;
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
            BeginInvoke((Action)(() =>
            {
                Append(outp.Trim().Length > 0 ? outp.Trim() : Texts.T("launcher.alreadyUp", "url", status.Url));
                if (open) OpenPage();
                Refresh(true);
            }));
        });
    }

    void StopServer()
    {
        if (launcher == null || !status.Up) { Append(Texts.T("launcher.notUp")); return; }
        stateLabel.Text = Texts.T("launcher.stopping");
        SetButtons(false);
        ThreadPool.QueueUserWorkItem(_ =>
        {
            launcher.Stop();
            BeginInvoke((Action)(() => { Append(Texts.T("launcher.stopped", "url", status.Url)); Refresh(true); }));
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
            BeginInvoke((Action)(() => { Append(message); Refresh(true); }));
        });
    }

    // -- the state: asked for in the background, shown in the window --
    void Refresh(bool now)
    {
        if (launcher == null || probing) return;
        probing = true;
        var previous = status;
        ThreadPool.QueueUserWorkItem(_ =>
        {
            ServerStatus st;
            try { st = launcher.Probe(previous); }
            catch (Exception e) { st = new ServerStatus { State = "busy", Error = e.Message, Url = launcher.Url }; }
            BeginInvoke((Action)(() =>
            {
                probing = false;
                bool cameUp = st.Up && !previous.Up;
                status = st;
                Show(st);
                if (st.Up) timer.Stop();
                if (cameUp && pendingOpen) { pendingOpen = false; OpenPage(); }
            }));
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
        startButton.Enabled = stopButton.Enabled = pageButton.Enabled = applyButton.Enabled = on;
    }

    void Append(string line)
    {
        if (InvokeRequired) { BeginInvoke((Action<string>)Append, line); return; }
        if (logBox.TextLength > 200000) logBox.Clear();
        logBox.AppendText(line + Environment.NewLine);
    }
}
