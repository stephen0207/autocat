import os
import subprocess
import sys

def build():
    print("Starting build process...")
    
    # Ensure pyinstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Path to main script and resources
    main_script = "auto_loot.py"
    res_name = "chest_template.png"
    
    # Build command
    # --onefile: single exe
    # --add-data: include the template (Windows uses ; as separator)
    # --uac-admin: request admin privileges on launch
    cmd = [
        "pyinstaller",
        "--onefile",
        "--add-data", f"{res_name};.",
        "--uac-admin",
        "--name", "AutoLoot",
        main_script
    ]
    
    print(f"Running command: {' '.join(cmd)}")
    subprocess.check_call(cmd)
    
    print("\nBuild complete! Check the 'dist' folder for AutoLoot.exe.")

if __name__ == "__main__":
    build()
