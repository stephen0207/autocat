# AutoLoot

An automated looting tool for Bongo cat designed to detect and click on loot chests.

## 🚀 Features

- **Image Recognition**: Uses OpenCV to detect chest on screen.
- **Auto-Clicking**: Automatically interacts with chests when the cursor has been idle for 0.3s.
- **Conditional Admin**: Only requests Administrator privileges if the target Bongo Cat instance is running as Admin.
- **Background Support**: Works even when the monitor is off using the `PrintWindow` API.

## 🕹️ Controls

- **F6**: Pause / Resume
- **F7**: Stop and Exit
- **F8**: Toggle Keep Alive (prevents display/system sleep)

## 📦 Installation

### Using the EXE (Recommended)
You can download the latest standalone version from the [Releases](https://github.com/stephen0207/autocat/releases) page.
1. Download `AutoLoot.exe`.
2. Run `AutoLoot.exe`. It will automatically prompt for Admin if needed.

### Running from Source
1. Ensure you have Python 3.11+ installed.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create your loot template:
   ```bash
   python capture_chest.py
   ```
4. Run the script:
   ```bash
   python auto_loot.py
   ```
