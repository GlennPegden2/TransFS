using System;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace Tranfs_Retrobat_Config
{
    public partial class MainForm : Form
    {
        private bool _isOperationInProgress = false;

        public MainForm()
        {
            InitializeComponent();
        }

        private void MainForm_Load(object sender, EventArgs e)
        {
            // Try to auto-detect RetroBat installation
            var retroBatDir = RetroBatHelper.FindRetroBatInstallDir();
            if (!string.IsNullOrEmpty(retroBatDir))
            {
                txtRetroBatDir.Text = retroBatDir;
                LogMessage($"Auto-detected RetroBat at: {retroBatDir}", "success");
            }
            else
            {
                LogMessage("RetroBat installation not found automatically. Please browse to locate it.", "warning");
            }
        }

        private void btnBrowseRetroBat_Click(object sender, EventArgs e)
        {
            using (var dialog = new FolderBrowserDialog())
            {
                dialog.Description = "Select RetroBat Installation Directory";
                if (!string.IsNullOrEmpty(txtRetroBatDir.Text) && Directory.Exists(txtRetroBatDir.Text))
                {
                    dialog.SelectedPath = txtRetroBatDir.Text;
                }

                if (dialog.ShowDialog() == DialogResult.OK)
                {
                    txtRetroBatDir.Text = dialog.SelectedPath;
                    LogMessage($"Selected RetroBat directory: {dialog.SelectedPath}");
                }
            }
        }

        private void btnBrowseTransFS_Click(object sender, EventArgs e)
        {
            using (var dialog = new FolderBrowserDialog())
            {
                dialog.Description = "Select TransFS Share Location (RetroBat/bios will be created here)";
                if (!string.IsNullOrEmpty(txtTransFSPath.Text) && Directory.Exists(txtTransFSPath.Text))
                {
                    dialog.SelectedPath = txtTransFSPath.Text;
                }

                if (dialog.ShowDialog() == DialogResult.OK)
                {
                    txtTransFSPath.Text = dialog.SelectedPath;
                    ValidateTransFS();
                }
            }
        }

        private void btnValidate_Click(object sender, EventArgs e)
        {
            ValidateInputs();
        }

        private void ValidateInputs()
        {
            bool isValid = true;

            // Validate RetroBat directory
            if (string.IsNullOrWhiteSpace(txtRetroBatDir.Text))
            {
                LogMessage("RetroBat directory is not set.", "error");
                isValid = false;
            }
            else if (!Directory.Exists(txtRetroBatDir.Text))
            {
                LogMessage($"RetroBat directory does not exist: {txtRetroBatDir.Text}", "error");
                isValid = false;
            }
            else
            {
                var biosDir = RetroBatHelper.GetBiosDirectory(txtRetroBatDir.Text);
                if (!Directory.Exists(biosDir))
                {
                    LogMessage($"BIOS directory not found at: {biosDir}", "error");
                    isValid = false;
                }
                else
                {
                    LogMessage($"RetroBat BIOS directory found: {biosDir}", "success");
                }
            }

            // Validate TransFS
            ValidateTransFS();

            if (isValid && !string.IsNullOrEmpty(lblValidationStatus.Text) && !lblValidationStatus.Text.Contains("error", StringComparison.OrdinalIgnoreCase))
            {
                btnCopyBios.Enabled = true;
                LogMessage("All validations passed. Ready to copy BIOS files.", "success");
            }
        }

        private void ValidateTransFS()
        {
            if (string.IsNullOrWhiteSpace(txtTransFSPath.Text))
            {
                LogMessage("TransFS path is not set.", "error");
                return;
            }

            var (isValid, message) = FileOperationHelper.ValidateDirectory(txtTransFSPath.Text);
            if (isValid)
            {
                LogMessage(message, "success");
                // Ensure RetroBat/bios subdirectory exists
                var targetBiosDir = Path.Combine(txtTransFSPath.Text, "RetroBat", "bios");
                Directory.CreateDirectory(targetBiosDir);
                LogMessage($"Target BIOS directory ready: {targetBiosDir}", "success");
            }
            else
            {
                LogMessage(message, "error");
            }
        }

        private async void btnCopyBios_Click(object sender, EventArgs e)
        {
            if (_isOperationInProgress)
                return;

            if (!ValidateForCopy())
                return;

            _isOperationInProgress = true;
            btnCopyBios.Enabled = false;
            progressBar.Value = 0;

            try
            {
                var sourceBiosDir = RetroBatHelper.GetBiosDirectory(txtRetroBatDir.Text);
                var targetBiosDir = Path.Combine(txtTransFSPath.Text, "RetroBat", "bios");

                LogMessage($"Starting BIOS copy from {sourceBiosDir} to {targetBiosDir}...");
                LogMessage("This may take a few minutes depending on file count and size...");

                var filesCopied = await FileOperationHelper.CopyDirectoryAsync(
                    sourceBiosDir,
                    targetBiosDir,
                    (progress, currentFile) =>
                    {
                        progressBar.Invoke(new Action(() => progressBar.Value = progress));
                        lblCurrentFile.Invoke(new Action(() => lblCurrentFile.Text = currentFile));
                    });

                LogMessage($"Successfully copied {filesCopied} files to TransFS!", "success");
                btnUpdateConfig.Enabled = true;
            }
            catch (Exception ex)
            {
                LogMessage($"Error during copy: {ex.Message}", "error");
            }
            finally
            {
                _isOperationInProgress = false;
                btnCopyBios.Enabled = true;
            }
        }

        private async void btnUpdateConfig_Click(object sender, EventArgs e)
        {
            if (_isOperationInProgress)
                return;

            var result = MessageBox.Show(
                "Do you want to update the local RetroBat configuration to use the TransFS BIOS?\n\n" +
                "This will:\n" +
                "1. Back up emulatorLauncher.cfg to emulatorLauncher.cfg.transfs (if not already backed up)\n" +
                "2. Update the bios= line to point to the TransFS share",
                "Update Configuration?",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Question);

            if (result != DialogResult.Yes)
                return;

            _isOperationInProgress = true;
            btnUpdateConfig.Enabled = false;

            try
            {
                var configPath = RetroBatHelper.GetEmulatorLauncherConfig(txtRetroBatDir.Text);
                if (!File.Exists(configPath))
                {
                    LogMessage($"Configuration file not found: {configPath}", "error");
                    return;
                }

                // Backup original config
                LogMessage("Creating backup of emulatorLauncher.cfg...");
                bool backedUp = FileOperationHelper.BackupFile(configPath);
                if (backedUp)
                {
                    LogMessage($"Backup created: {configPath}.transfs", "success");
                }
                else
                {
                    LogMessage($"Backup already exists: {configPath}.transfs", "info");
                }

                // Update config
                var newBiosPath = Path.Combine(txtTransFSPath.Text, "RetroBat", "bios");
                LogMessage($"Updating bios= line to: {newBiosPath}");
                
                FileOperationHelper.UpdateBiosConfigLine(configPath, newBiosPath);
                
                LogMessage("Configuration updated successfully!", "success");
                LogMessage($"Modified: {configPath}", "info");

                MessageBox.Show(
                    $"Configuration updated successfully!\n\n" +
                    $"Old config backed up to: emulatorLauncher.cfg.transfs\n" +
                    $"bios= line now points to: {newBiosPath}",
                    "Success",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
            }
            catch (Exception ex)
            {
                LogMessage($"Error updating configuration: {ex.Message}", "error");
                MessageBox.Show($"Error: {ex.Message}", "Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            finally
            {
                _isOperationInProgress = false;
                btnUpdateConfig.Enabled = true;
            }
        }

        private bool ValidateForCopy()
        {
            if (string.IsNullOrWhiteSpace(txtRetroBatDir.Text) || !Directory.Exists(txtRetroBatDir.Text))
            {
                MessageBox.Show("Please select a valid RetroBat directory.", "Invalid RetroBat Directory", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return false;
            }

            if (string.IsNullOrWhiteSpace(txtTransFSPath.Text) || !Directory.Exists(txtTransFSPath.Text))
            {
                MessageBox.Show("Please select a valid TransFS share location.", "Invalid TransFS Path", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return false;
            }

            var sourceBiosDir = RetroBatHelper.GetBiosDirectory(txtRetroBatDir.Text);
            if (!Directory.Exists(sourceBiosDir))
            {
                MessageBox.Show($"BIOS directory not found: {sourceBiosDir}", "BIOS Not Found", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return false;
            }

            return true;
        }

        private void LogMessage(string message, string type = "info")
        {
            var timestamp = DateTime.Now.ToString("HH:mm:ss");
            var prefix = type.ToLower() switch
            {
                "success" => "[✓]",
                "error" => "[✗]",
                "warning" => "[!]",
                _ => "[i]"
            };

            var logText = $"{timestamp} {prefix} {message}";
            
            txtLog.Invoke(new Action(() =>
            {
                txtLog.AppendText(logText + Environment.NewLine);
            }));
        }

        private void InitializeComponent()
        {
            this.txtRetroBatDir = new System.Windows.Forms.TextBox();
            this.txtTransFSPath = new System.Windows.Forms.TextBox();
            this.btnBrowseRetroBat = new System.Windows.Forms.Button();
            this.btnBrowseTransFS = new System.Windows.Forms.Button();
            this.btnValidate = new System.Windows.Forms.Button();
            this.btnCopyBios = new System.Windows.Forms.Button();
            this.btnUpdateConfig = new System.Windows.Forms.Button();
            this.txtLog = new System.Windows.Forms.TextBox();
            this.progressBar = new System.Windows.Forms.ProgressBar();
            this.lblCurrentFile = new System.Windows.Forms.Label();
            this.lblValidationStatus = new System.Windows.Forms.Label();

            // Form
            this.Text = "RetroBat & TransFS Configuration Sync";
            this.StartPosition = System.Windows.Forms.FormStartPosition.CenterScreen;
            this.Size = new System.Drawing.Size(800, 700);
            this.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;

            // RetroBat Directory Section
            var lblRetroBat = new System.Windows.Forms.Label()
            {
                Text = "RetroBat Installation Directory:",
                Location = new System.Drawing.Point(10, 10),
                AutoSize = true
            };
            this.Controls.Add(lblRetroBat);

            this.txtRetroBatDir.Location = new System.Drawing.Point(10, 30);
            this.txtRetroBatDir.Size = new System.Drawing.Size(650, 20);
            this.txtRetroBatDir.ReadOnly = false;
            this.Controls.Add(this.txtRetroBatDir);

            this.btnBrowseRetroBat.Text = "Browse...";
            this.btnBrowseRetroBat.Location = new System.Drawing.Point(670, 30);
            this.btnBrowseRetroBat.Size = new System.Drawing.Size(110, 25);
            this.btnBrowseRetroBat.Click += btnBrowseRetroBat_Click;
            this.Controls.Add(this.btnBrowseRetroBat);

            // TransFS Path Section
            var lblTransFS = new System.Windows.Forms.Label()
            {
                Text = "TransFS Share Location (map/UNC path):",
                Location = new System.Drawing.Point(10, 65),
                AutoSize = true
            };
            this.Controls.Add(lblTransFS);

            this.txtTransFSPath.Location = new System.Drawing.Point(10, 85);
            this.txtTransFSPath.Size = new System.Drawing.Size(650, 20);
            this.txtTransFSPath.ReadOnly = false;
            this.Controls.Add(this.txtTransFSPath);

            this.btnBrowseTransFS.Text = "Browse...";
            this.btnBrowseTransFS.Location = new System.Drawing.Point(670, 85);
            this.btnBrowseTransFS.Size = new System.Drawing.Size(110, 25);
            this.btnBrowseTransFS.Click += btnBrowseTransFS_Click;
            this.Controls.Add(this.btnBrowseTransFS);

            // Validation Status
            this.lblValidationStatus.Location = new System.Drawing.Point(10, 115);
            this.lblValidationStatus.Size = new System.Drawing.Size(770, 40);
            this.lblValidationStatus.AutoSize = false;
            this.lblValidationStatus.Text = "Ready to validate. Click 'Validate' to check paths.";
            this.Controls.Add(this.lblValidationStatus);

            // Buttons Row 1
            this.btnValidate.Text = "Validate Paths";
            this.btnValidate.Location = new System.Drawing.Point(10, 160);
            this.btnValidate.Size = new System.Drawing.Size(100, 30);
            this.btnValidate.Click += btnValidate_Click;
            this.Controls.Add(this.btnValidate);

            this.btnCopyBios.Text = "Copy BIOS Files";
            this.btnCopyBios.Location = new System.Drawing.Point(120, 160);
            this.btnCopyBios.Size = new System.Drawing.Size(120, 30);
            this.btnCopyBios.Enabled = false;
            this.btnCopyBios.Click += btnCopyBios_Click;
            this.Controls.Add(this.btnCopyBios);

            this.btnUpdateConfig.Text = "Update Configuration";
            this.btnUpdateConfig.Location = new System.Drawing.Point(250, 160);
            this.btnUpdateConfig.Size = new System.Drawing.Size(140, 30);
            this.btnUpdateConfig.Enabled = false;
            this.btnUpdateConfig.Click += btnUpdateConfig_Click;
            this.Controls.Add(this.btnUpdateConfig);

            // Progress
            this.progressBar.Location = new System.Drawing.Point(10, 200);
            this.progressBar.Size = new System.Drawing.Size(770, 25);
            this.progressBar.Minimum = 0;
            this.progressBar.Maximum = 100;
            this.Controls.Add(this.progressBar);

            // Current File
            this.lblCurrentFile.Location = new System.Drawing.Point(10, 230);
            this.lblCurrentFile.Size = new System.Drawing.Size(770, 20);
            this.lblCurrentFile.Text = "Ready...";
            this.Controls.Add(this.lblCurrentFile);

            // Log Output
            var lblLog = new System.Windows.Forms.Label()
            {
                Text = "Operation Log:",
                Location = new System.Drawing.Point(10, 260),
                AutoSize = true
            };
            this.Controls.Add(lblLog);

            this.txtLog.Location = new System.Drawing.Point(10, 280);
            this.txtLog.Size = new System.Drawing.Size(770, 390);
            this.txtLog.Multiline = true;
            this.txtLog.ReadOnly = true;
            this.txtLog.ScrollBars = System.Windows.Forms.ScrollBars.Vertical;
            this.txtLog.Font = new System.Drawing.Font("Courier New", 9);
            this.Controls.Add(this.txtLog);

            this.Load += MainForm_Load;
        }

        private System.Windows.Forms.TextBox txtRetroBatDir;
        private System.Windows.Forms.TextBox txtTransFSPath;
        private System.Windows.Forms.Button btnBrowseRetroBat;
        private System.Windows.Forms.Button btnBrowseTransFS;
        private System.Windows.Forms.Button btnValidate;
        private System.Windows.Forms.Button btnCopyBios;
        private System.Windows.Forms.Button btnUpdateConfig;
        private System.Windows.Forms.TextBox txtLog;
        private System.Windows.Forms.ProgressBar progressBar;
        private System.Windows.Forms.Label lblCurrentFile;
        private System.Windows.Forms.Label lblValidationStatus;
    }
}
