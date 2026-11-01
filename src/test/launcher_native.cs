// Compile alongside the unchanged production host, selecting this test entry point.
using System;
using System.Text;
using System.Windows.Forms;

static class LauncherNativeChecks
{
    [STAThread]
    static int Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        if (args.Length == 2 && args[0] == "quote")
        {
            Console.Write(Program.Quote(args[1]));
            return 0;
        }
        if (args.Length == 2 && args[0] == "startup-error")
        {
            int result = Program.Main(new string[0]);
            if (result == 1 && MessageBox.Calls == 1 && MessageBox.Caption == "Morphbench"
                && MessageBox.Text.Contains(args[1]))
            {
                Console.WriteLine("PASS startup-error");
                return 0;
            }
            Console.Error.WriteLine("Unexpected startup result: " + result + "; " + MessageBox.Text);
        }
        return 1;
    }
}

// Global name lookup captures startup dialogs without modifying the production source.
static class MessageBox
{
    internal static int Calls;
    internal static string Text = "";
    internal static string Caption = "";

    internal static DialogResult Show(string text, string caption,
        MessageBoxButtons buttons, MessageBoxIcon icon)
    {
        Calls++;
        Text = text;
        Caption = caption;
        return DialogResult.OK;
    }
}
