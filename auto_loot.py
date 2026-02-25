"""
Bongo Cat Auto-Loot Script
============================
Detects the treasure chest in the Bongo Cat window using template
matching (chest_template.png) and clicks it with pyautogui.

Uses PrintWindow API for screen capture, which works even when the
monitor is off or the window is behind other windows.

Usage:
    Run as Administrator!
    python auto_loot.py

Controls:
    F6  = Pause / Resume
    F7  = Stop and exit
"""

import sys
import os

# Force unbuffered output so the terminal updates in real-time
os.environ['PYTHONUNBUFFERED'] = '1'
sys.stdout.reconfigure(line_buffering=True)

import cv2
import numpy as np
import pyautogui


import time
import threading
import os
import sys
import ctypes
import ctypes.wintypes
from datetime import datetime

import win32gui
import win32con
import win32api
import win32ui


# ═══════════════════════════════════════════════════════
#  AUTO-ELEVATE TO ADMIN
# ═══════════════════════════════════════════════════════

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def elevate():
    if not is_admin():
        print("  🔒 Requesting admin privileges...")
        # Use absolute path and -u for unbuffered output
        script = os.path.abspath(sys.argv[0])
        args = "-u " + " ".join([f'"{script}"'] + [f'"{a}"' for a in sys.argv[1:]])
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, args, None, 1
        )
        sys.exit(0)


def disable_quick_edit():
    """
    Disable Quick Edit mode on the Windows console.
    When Quick Edit is ON (default), any mouse click on the console
    window starts a text selection that FREEZES all program output
    until Enter is pressed. Since our script moves the real cursor
    to click chests, the cursor can accidentally hit the console
    window, causing the script to stall.
    """
    try:
        kernel32 = ctypes.windll.kernel32
        h_stdin = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.wintypes.DWORD()
        kernel32.GetConsoleMode(h_stdin, ctypes.byref(mode))
        # Clear ENABLE_QUICK_EDIT_MODE (0x0040) and ENABLE_INSERT_MODE (0x0020)
        # Keep ENABLE_EXTENDED_FLAGS (0x0080) so the change takes effect
        new_mode = (mode.value & ~0x0040 & ~0x0020) | 0x0080
        kernel32.SetConsoleMode(h_stdin, new_mode)
        print("  ✅ Quick Edit mode disabled (prevents accidental freezes)")
    except Exception as e:
        print(f"  ⚠️  Could not disable Quick Edit: {e}")


# ═══════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════

WINDOW_TITLE = "BongoCat"
CHECK_INTERVAL = 5.0
CONFIDENCE_THRESHOLD = 0.75
POST_CLICK_COOLDOWN = 1.0
MIN_CHEST_INTERVAL = 1 * 60  # 1 min — chests spawn every 30 min, ignore duplicates
# Virtual key codes for hotkeys (no keyboard library needed)
VK_F6 = 0x75  # Pause/Resume
VK_F7 = 0x76  # Stop
VK_F8 = 0x77  # Toggle Keep Alive (prevent display sleep)

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.02

# ═══════════════════════════════════════════════════════


class BongoCatAutoLooter:
    def __init__(self, template_path: str):
        self.paused = False
        self.running = True
        self.keep_alive = True  # Prevent display + system sleep (on by default)
        self.loot_count = 0
        self.last_loot_time = 0  # epoch timestamp of the last looted chest
        self.hwnd = None
        self.template = None
        self.template_w = 0
        self.template_h = 0

        self._stop_event = threading.Event()  # Used for non-blocking sleeps

        self._prev_f6 = False  # Track key state to detect press edges
        self._prev_f7 = False
        self._prev_f8 = False

        self._load_template(template_path)
        self._find_window()

    def _load_template(self, template_path: str):
        if not os.path.exists(template_path):
            print(f"  ❌ Template not found: {template_path}")
            print("     Run capture_chest.py first to create the template.")
            sys.exit(1)

        self.template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if self.template is None:
            print(f"  ❌ Failed to load: {template_path}")
            sys.exit(1)

        self.template_h, self.template_w = self.template.shape[:2]
        print(f"  ✅ Template: {self.template_w}x{self.template_h} px")

    def _find_window(self):
        def enum_cb(hwnd, results):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if WINDOW_TITLE.lower() in title.lower():
                    results.append((hwnd, title))

        results = []
        win32gui.EnumWindows(enum_cb, results)

        if not results:
            print(f"  ❌ '{WINDOW_TITLE}' window not found. Is Bongo Cat running?")
            sys.exit(1)

        self.hwnd = results[0][0]
        rect = win32gui.GetWindowRect(self.hwnd)
        print(f"  🪟 Found: \"{results[0][1]}\"")
        print(f"     Screen position: left={rect[0]} top={rect[1]} "
              f"right={rect[2]} bottom={rect[3]}")

    def _check_hotkeys(self):
        """Poll physical key state — no console input interaction."""
        f6_down = bool(win32api.GetAsyncKeyState(VK_F6) & 0x8000)
        f7_down = bool(win32api.GetAsyncKeyState(VK_F7) & 0x8000)
        f8_down = bool(win32api.GetAsyncKeyState(VK_F8) & 0x8000)

        # Detect rising edge (key just pressed)
        if f6_down and not self._prev_f6:
            self._toggle_pause()
        if f7_down and not self._prev_f7:
            self._stop()
        if f8_down and not self._prev_f8:
            self._toggle_keep_alive()

        self._prev_f6 = f6_down
        self._prev_f7 = f7_down
        self._prev_f8 = f8_down

    def _toggle_pause(self):
        self.paused = not self.paused
        status = "⏸️  PAUSED" if self.paused else "▶️  RESUMED"
        print(f"\n{status} (press F6 to toggle)")

    def _stop(self):
        self.running = False
        self._stop_event.set()  # Wake up any sleeping wait immediately
        print(f"\n🛑 Stopping...")

    def _toggle_keep_alive(self):
        self.keep_alive = not self.keep_alive
        self._apply_keep_alive()
        status = "🔆 Keep Alive ON" if self.keep_alive else "🌙 Keep Alive OFF"
        detail = "(display + system stay awake)" if self.keep_alive else "(display may turn off)"
        print(f"\n{status} {detail} — press F8 to toggle")

    def _apply_keep_alive(self):
        """Apply or remove the keep-alive execution state."""
        ES_CONTINUOUS        = 0x80000000
        ES_SYSTEM_REQUIRED   = 0x00000001
        ES_DISPLAY_REQUIRED  = 0x00000002

        if self.keep_alive:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            )
        else:
            # Only prevent system sleep, allow display to turn off
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            )

    def _sleep(self, seconds: float):
        """Non-blocking sleep that checks hotkeys every 0.2s."""
        end_time = time.time() + seconds
        while time.time() < end_time and self.running:
            self._check_hotkeys()
            remaining = end_time - time.time()
            if remaining <= 0:
                break
            self._stop_event.wait(timeout=min(0.2, remaining))

    def capture_window(self) -> np.ndarray | None:
        """
        Capture the Bongo Cat window using the PrintWindow API.
        Works even when the monitor is off or the window is behind others.
        """
        try:
            if not win32gui.IsWindow(self.hwnd):
                print("  ⚠️  Window lost! Re-finding...")
                self._find_window()

            rect = win32gui.GetWindowRect(self.hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]

            if width <= 0 or height <= 0:
                return None

            # Create device contexts and bitmap for off-screen rendering
            hwnd_dc = win32gui.GetWindowDC(self.hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)

            # PW_RENDERFULLCONTENT (2) — works with hardware-accelerated windows
            ctypes.windll.user32.PrintWindow(
                self.hwnd, save_dc.GetSafeHdc(), 2
            )

            # Convert bitmap to numpy array
            bmpstr = bitmap.GetBitmapBits(True)
            img = np.frombuffer(bmpstr, dtype=np.uint8).reshape(
                height, width, 4
            )
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            # Cleanup GDI resources
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, hwnd_dc)
            win32gui.DeleteObject(bitmap.GetHandle())

            return img

        except Exception as e:
            print(f"  ⚠️  Capture error: {e}")
            return None

    def find_chest(self, screen: np.ndarray):
        """Template match. Returns (cx, cy, confidence) or None."""
        # Ensure template fits in the captured image
        if (screen.shape[0] < self.template_h or
                screen.shape[1] < self.template_w):
            return None

        result = cv2.matchTemplate(screen, self.template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= CONFIDENCE_THRESHOLD:
            cx = max_loc[0] + self.template_w // 2
            cy = max_loc[1] + self.template_h // 2
            return cx, cy, max_val

        return None

    def click_chest(self, region_x: int, region_y: int):
        """
        Click the chest by aggressively stealing focus from the
        fullscreen game, clicking BongoCat, then restoring.

        Works even in exclusive fullscreen by:
        1) Simulating Alt key (unlocks SetForegroundWindow restriction)
        2) Forcing BongoCat to foreground
        3) Physical mouse click
        4) Restoring the game
        """
        HWND_TOPMOST    = -1
        HWND_NOTOPMOST  = -2
        SWP_NOMOVE      = 0x0002
        SWP_NOSIZE      = 0x0001
        SWP_NOACTIVATE  = 0x0010
        SWP_SHOWWINDOW  = 0x0040
        VK_MENU         = 0x12   # Alt key
        KEYEVENTF_KEYUP = 0x0002
        SW_SHOW         = 5
        SW_RESTORE      = 9

        try:
            win_rect = win32gui.GetWindowRect(self.hwnd)
            screen_x = win_rect[0] + region_x
            screen_y = win_rect[1] + region_y

            # ── Wait for mouse idle (skip if screen off) ──
            orig = None
            try:
                IDLE_THRESHOLD = 0.3
                last_pos = win32api.GetCursorPos()
                idle_start = time.time()

                while True:
                    if not self.running:
                        return
                    self._check_hotkeys()
                    if self.paused:
                        return

                    current_pos = win32api.GetCursorPos()
                    if current_pos != last_pos:
                        idle_start = time.time()
                        last_pos = current_pos
                    elif time.time() - idle_start >= IDLE_THRESHOLD:
                        break
                    time.sleep(0.05)

                orig = win32api.GetCursorPos()
            except Exception:
                pass  # Screen off — skip idle wait

            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"  [{timestamp}] 🖱️  Click at ({screen_x}, {screen_y})",
                  flush=True)

            prev_hwnd = None
            try:
                prev_hwnd = win32gui.GetForegroundWindow()
            except Exception:
                pass

            # ══════════════════════════════════════════════
            #  STEP 1: Break out of exclusive fullscreen
            # ══════════════════════════════════════════════
            # Simulate Alt key press — this satisfies Windows'
            # restriction that only the foreground process can
            # call SetForegroundWindow. Pressing Alt unlocks it.
            ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)          # Alt down
            ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)  # Alt up

            # Allow our process to set foreground window
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY

            # Release cursor clip (game locks cursor in fullscreen)
            ctypes.windll.user32.ClipCursor(None)

            # ══════════════════════════════════════════════
            #  STEP 2: Force BongoCat to front
            # ══════════════════════════════════════════════
            # Make topmost
            ctypes.windll.user32.SetWindowPos(
                self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            )

            # Ensure window is visible and not minimized
            win32gui.ShowWindow(self.hwnd, SW_RESTORE)

            # Bring to top of Z-order
            win32gui.BringWindowToTop(self.hwnd)

            # Set as foreground (should work now after Alt key simulation)
            try:
                win32gui.SetForegroundWindow(self.hwnd)
            except Exception:
                # Fallback: attach to foreground thread's input queue
                try:
                    fg = win32gui.GetForegroundWindow()
                    fg_thread = ctypes.windll.user32.GetWindowThreadProcessId(fg, None)
                    our_thread = ctypes.windll.kernel32.GetCurrentThreadId()
                    ctypes.windll.user32.AttachThreadInput(fg_thread, our_thread, True)
                    win32gui.SetForegroundWindow(self.hwnd)
                    ctypes.windll.user32.AttachThreadInput(fg_thread, our_thread, False)
                except Exception:
                    pass

            time.sleep(0.2)  # Let BongoCat fully appear

            # Release clip again (game may have re-clipped)
            ctypes.windll.user32.ClipCursor(None)

            # ══════════════════════════════════════════════
            #  STEP 3: Physical click on the chest
            # ══════════════════════════════════════════════
            try:
                win32api.SetCursorPos((screen_x, screen_y))
            except Exception:
                pass

            time.sleep(0.02)
            ctypes.windll.user32.ClipCursor(None)

            # A single click is enough to loot
            win32api.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
            time.sleep(0.03)
            win32api.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
            time.sleep(0.03)

            # ══════════════════════════════════════════════
            #  STEP 4: Restore everything
            # ══════════════════════════════════════════════
            # Remove TOPMOST flag
            ctypes.windll.user32.SetWindowPos(
                self.hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            )

            # Restore cursor position
            if orig:
                try:
                    win32api.SetCursorPos(orig)
                except Exception:
                    pass

            # Give focus back to the game
            ctypes.windll.user32.ClipCursor(None)
            if prev_hwnd and win32gui.IsWindow(prev_hwnd):
                time.sleep(0.1)
                try:
                    # Simulate Alt again to allow setting foreground
                    ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
                    win32gui.SetForegroundWindow(prev_hwnd)
                except Exception:
                    pass

        except Exception as e:
            # Always try to clean up TOPMOST
            try:
                ctypes.windll.user32.SetWindowPos(
                    self.hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                )
            except Exception:
                pass
            print(f"  ⚠️  Click error: {e}", flush=True)

    def run(self):
        print()
        print("=" * 55)
        print("  🐱 Bongo Cat Auto-Loot")
        print("=" * 55)
        print()
        print(f"  ⚠️  Keep Bongo Cat window open (can be behind other windows)")
        print(f"  💡 Monitor can be turned off — script will keep working")
        print()
        print(f"  📋 Check every {CHECK_INTERVAL}s | "
              f"Confidence ≥ {CONFIDENCE_THRESHOLD} | "
              f"Cooldown {POST_CLICK_COOLDOWN}s")
        alive_status = "ON" if self.keep_alive else "OFF"
        print(f"  ⌨️  F6=Pause/Resume | F7=Stop | F8=Keep Alive ({alive_status})")
        print()
        print("-" * 55)
        print(f"  📊 Chests: 0 | 👀 Scanning...", flush=True)

        # Apply keep-alive state (prevents display + system sleep)
        self._apply_keep_alive()

        start_time = time.time()

        try:
            while self.running:
                self._check_hotkeys()
                if self.paused:
                    self._sleep(0.5)
                    continue

                frame = self.capture_window()
                if frame is None:
                    self._sleep(CHECK_INTERVAL)
                    continue

                match = self.find_chest(frame)

                if match:
                    x, y, confidence = match
                    now = time.time()
                    time_since_last = now - self.last_loot_time

                    # If detected too soon after last loot, it's the same chest
                    if self.last_loot_time > 0 and time_since_last < MIN_CHEST_INTERVAL:
                        # Still click (in case previous click missed), but don't log
                        self.click_chest(x, y)
                        self._sleep(POST_CLICK_COOLDOWN)
                    else:
                        self.loot_count += 1
                        self.last_loot_time = now
                        ts = datetime.now().strftime("%H:%M:%S")

                        print(
                            f"  [{ts}] 📦 Chest #{self.loot_count}! "
                            f"offset=({x},{y}) conf={confidence:.2%}",
                            flush=True
                        )

                        self.click_chest(x, y)

                        elapsed = int(time.time() - start_time)
                        mins, secs = divmod(elapsed, 60)
                        hrs, mins = divmod(mins, 60)
                        print(
                            f"  [{ts}] ✅ Clicked! "
                            f"Total: {self.loot_count} | "
                            f"⏱️ {hrs:02d}:{mins:02d}:{secs:02d} | "
                            f"Next check in {POST_CLICK_COOLDOWN}s...",
                            flush=True
                        )
                        self._sleep(POST_CLICK_COOLDOWN)
                else:
                    self._sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            print("\n🛑 Stopped", flush=True)

        finally:
            # Allow system to sleep again
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)

            elapsed = int(time.time() - start_time)
            mins, secs = divmod(elapsed, 60)
            hrs, mins = divmod(mins, 60)
            print()
            print("=" * 55)
            print(f"  📊 Session Summary")
            print(f"     Chests looted : {self.loot_count}")
            print(f"     Total time    : {hrs:02d}:{mins:02d}:{secs:02d}")
            print("=" * 55)
            print()
            input("  Press Enter to exit...")


def main():
    elevate()
    disable_quick_edit()  # Prevent console freezes from cursor movement — must run before any prints
    # Flush stdout/stderr immediately after disabling Quick Edit
    sys.stdout.flush()
    sys.stderr.flush()

    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    template_path = os.path.join(script_dir, "chest_template.png")

    print()
    print("=" * 55)
    print("  🐱 Bongo Cat Auto-Loot")
    print("=" * 55)
    # print(f"  🔑 Admin: {is_admin()}")
    # print(f"  📂 Dir: {script_dir}")

    looter = BongoCatAutoLooter(template_path)
    looter.run()


if __name__ == "__main__":
    main()
