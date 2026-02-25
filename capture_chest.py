"""
Bongo Cat Chest Capture Tool
=============================
Run this script ONCE to capture a reference image of the chest icon.
A semi-transparent overlay will appear - drag a rectangle around the chest.
The cropped region is saved as chest_template.png for use by auto_loot.py.
"""

import tkinter as tk
from PIL import ImageGrab, Image, ImageTk
import sys
import os


class ScreenRegionSelector:
    """Full-screen overlay that lets the user drag-select a region."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Chest Capture - Select the chest region")
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.configure(cursor="crosshair")

        # Capture the full screen
        self.screenshot = ImageGrab.grab()
        self.tk_image = ImageTk.PhotoImage(self.screenshot)

        # Canvas with screenshot as background
        self.canvas = tk.Canvas(self.root, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)

        # Dark overlay for visual feedback
        self.overlay = self.canvas.create_rectangle(
            0, 0,
            self.root.winfo_screenwidth(),
            self.root.winfo_screenheight(),
            fill="black", stipple="gray50", outline=""
        )

        # Instructions text
        self.canvas.create_text(
            self.root.winfo_screenwidth() // 2, 30,
            text="🖱️ Drag a rectangle around the chest icon, then release. Press ESC to cancel.",
            fill="white", font=("Segoe UI", 16, "bold")
        )

        # Selection rectangle
        self.rect = None
        self.start_x = 0
        self.start_y = 0
        self.end_x = 0
        self.end_y = 0

        # Bind events
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.root.bind("<Escape>", lambda e: self.cancel())

        self.result = None

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="#00ff88", width=2, dash=(5, 3)
        )

    def on_drag(self, event):
        self.canvas.coords(
            self.rect,
            self.start_x, self.start_y,
            event.x, event.y
        )

    def on_release(self, event):
        self.end_x = event.x
        self.end_y = event.y

        # Normalize coordinates
        x1 = min(self.start_x, self.end_x)
        y1 = min(self.start_y, self.end_y)
        x2 = max(self.start_x, self.end_x)
        y2 = max(self.start_y, self.end_y)

        # Minimum size check
        if (x2 - x1) < 10 or (y2 - y1) < 10:
            print("⚠️  Selection too small. Please drag a larger rectangle.")
            return

        self.result = (x1, y1, x2, y2)
        self.root.destroy()

    def cancel(self):
        print("❌ Cancelled.")
        self.root.destroy()
        sys.exit(0)

    def run(self):
        self.root.mainloop()
        return self.result


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_dir, "chest_template.png")

    print("=" * 50)
    print("  Bongo Cat Chest Capture Tool")
    print("=" * 50)
    print()
    print("📋 Instructions:")
    print("  1. Make sure the Bongo Cat chest is visible on screen")
    print("  2. A fullscreen overlay will appear")
    print("  3. Drag a rectangle around the chest icon")
    print("  4. Release to save the template")
    print("  5. Press ESC to cancel")
    print()
    input("Press Enter when the chest is visible on screen...")

    selector = ScreenRegionSelector()
    region = selector.run()

    if region is None:
        print("❌ No region selected.")
        sys.exit(1)

    x1, y1, x2, y2 = region

    # Crop from the original screenshot
    screenshot = ImageGrab.grab()
    cropped = screenshot.crop((x1, y1, x2, y2))
    cropped.save(output_path)

    print()
    print(f"✅ Chest template saved to: {output_path}")
    print(f"   Size: {cropped.size[0]}x{cropped.size[1]} pixels")
    print()
    print("You can now run auto_loot.py to start auto-looting!")


if __name__ == "__main__":
    main()
