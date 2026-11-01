// Stable native host. Application owns discovery, settings, UI and process lifecycle.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyVersion("3.0.0.0")]
[assembly: AssemblyFileVersion("3.0.0.0")]
[assembly: AssemblyInformationalVersion("Morphbench Launcher v3 (host protocol 1)")]

static class Program
{
    [STAThread]
    internal static int Main(string[] args)
    {
        Process child;
        try
        {
            string home = AppDomain.CurrentDomain.BaseDirectory;
            string python = Path.GetFullPath(Path.Combine(home, "python", "python.exe"));
            string shim = Path.GetFullPath(Path.Combine(home, "mb.py"));
            // Opening files honors MO2's virtual paths where attribute probes may not.
            foreach (string path in new[] { python, shim })
                using (File.Open(path, FileMode.Open, FileAccess.Read,
                    FileShare.ReadWrite | FileShare.Delete)) { }

            var arguments = new StringBuilder("-I ").Append(Quote(shim))
                .Append(" --launcher-host 1 --native-parent ")
                .Append(Process.GetCurrentProcess().Id).Append(" --");
            foreach (string argument in args) arguments.Append(' ').Append(Quote(argument));
            child = Process.Start(new ProcessStartInfo(python, arguments.ToString())
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = Environment.CurrentDirectory,
            });
            if (child == null) throw new InvalidOperationException("Python could not be started.");
        }
        catch (Exception error)
        {
            MessageBox.Show("Morphbench could not start.\r\n" + error.Message,
                "Morphbench", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }

        using (child)
        {
            child.WaitForExit();
            return child.ExitCode;
        }
    }

    // Windows argv escaping: backslashes double before quotes and the closing quote.
    internal static string Quote(string value)
    {
        var quoted = new StringBuilder("\"");
        int slashes = 0;
        foreach (char character in value)
        {
            if (character == '\\') { slashes++; continue; }
            if (character == '"') quoted.Append('\\', slashes * 2 + 1).Append('"');
            else quoted.Append('\\', slashes).Append(character);
            slashes = 0;
        }
        return quoted.Append('\\', slashes * 2).Append('"').ToString();
    }
}
