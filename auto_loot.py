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

# Force fully unbuffered output so the terminal updates in real-time.
# os.environ['PYTHONUNBUFFERED'] only works if set BEFORE the interpreter starts,
# so we use write_through=True which bypasses Python's internal text buffer.
sys.stdout.reconfigure(write_through=True)
sys.stderr.reconfigure(write_through=True)

import cv2
import numpy as np
import pyautogui

import time
import threading
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


def is_process_elevated(pid: int) -> bool:
    """
    Return True if the process with the given PID is running with
    elevated (admin) privileges.
    """
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TOKEN_QUERY = 0x0008

    try:
        h_process = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not h_process:
            return False

        h_token = ctypes.wintypes.HANDLE()
        if not ctypes.windll.advapi32.OpenProcessToken(
            h_process, TOKEN_QUERY, ctypes.byref(h_token)
        ):
            ctypes.windll.kernel32.CloseHandle(h_process)
            return False

        # TokenElevation = 20
        elevation = ctypes.wintypes.DWORD()
        size = ctypes.wintypes.DWORD()
        ctypes.windll.advapi32.GetTokenInformation(
            h_token, 20,
            ctypes.byref(elevation), ctypes.sizeof(elevation),
            ctypes.byref(size)
        )
        ctypes.windll.kernel32.CloseHandle(h_token)
        ctypes.windll.kernel32.CloseHandle(h_process)
        return bool(elevation.value)
    except Exception:
        return False


def resource_path(relative_path):
    """
    Return path to a resource file.
    - First checks PyInstaller's temp extraction dir (_MEIPASS) for bundled files.
    - Falls back to the folder containing the EXE (frozen) or script (dev).
    """
    if getattr(sys, 'frozen', False):
        # Check bundled resources first
        bundled = os.path.join(sys._MEIPASS, relative_path)
        if os.path.exists(bundled):
            return bundled
        # Fall back to folder next to the EXE
        return os.path.join(os.path.dirname(sys.executable), relative_path)
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def elevate():
    """
    Re-launch the current process with admin privileges.
    Called only when Bongo Cat is detected as running as admin.
    """
    if not is_admin():
        print("  🔒 Elevating to admin...", flush=True)
        if getattr(sys, 'frozen', False):
            script = sys.executable
            args = None
        else:
            script = sys.executable
            args = "-u " + " ".join([f'"{os.path.abspath(sys.argv[0])}"'] +
                                    [f'"{a}"' for a in sys.argv[1:]])
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", script, args, None, 1
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
        print("  ✅ Quick Edit disabled", flush=True)
    except Exception as e:
        print(f"  ⚠️  Could not disable Quick Edit: {e}", flush=True)


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
            print(f"  ❌ Template not found: {template_path}", flush=True)
            sys.exit(1)

        self.template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if self.template is None:
            print(f"  ❌ Failed to load: {template_path}", flush=True)
            sys.exit(1)

        self.template_h, self.template_w = self.template.shape[:2]
        print(f"  ✅ Template loaded ({self.template_w}x{self.template_h}px)", flush=True)

    def _find_window(self):
        def enum_cb(hwnd, results):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if WINDOW_TITLE.lower() in title.lower():
                    results.append((hwnd, title))

        results = []
        win32gui.EnumWindows(enum_cb, results)

        if not results:
            print(f"  ❌ '{WINDOW_TITLE}' window not found. Is Bongo Cat running?", flush=True)
            sys.exit(1)

        self.hwnd = results[0][0]
        print(f"  🪟 Window: \"{results[0][1]}\"", flush=True)

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
        print(f"  {status}", flush=True)

    def _stop(self):
        self.running = False
        self._stop_event.set()  # Wake up any sleeping wait immediately
        print(f"\n🛑 Stopping...", flush=True)

    def _toggle_keep_alive(self):
        self.keep_alive = not self.keep_alive
        self._apply_keep_alive()
        status = "🔆 ON" if self.keep_alive else "🌙 OFF"
        print(f"  Keep Alive: {status}", flush=True)

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
                print("  ⚠️  Window lost! Re-finding...", flush=True)
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
        Click the chest by stealing focus from the fullscreen app,
        clicking BongoCat, then restoring.

        1) Persistent un-clip thread (prevents game from re-clipping cursor)
        2) Alt+Tab to force-minimize the fullscreen app
        3) Forcing BongoCat to foreground
        4) SendInput click with retry
        5) Restoring the previous app
        """
        HWND_TOPMOST    = -1
        HWND_NOTOPMOST  = -2
        SWP_NOMOVE      = 0x0002
        SWP_NOSIZE      = 0x0001
        SWP_NOACTIVATE  = 0x0010
        SWP_SHOWWINDOW  = 0x0040
        VK_MENU         = 0x12   # Alt key
        VK_TAB          = 0x09   # Tab key
        KEYEVENTF_KEYUP = 0x0002
        SW_RESTORE      = 9

        try:
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

            win_rect = win32gui.GetWindowRect(self.hwnd)
            screen_x = win_rect[0] + region_x
            screen_y = win_rect[1] + region_y

            prev_hwnd = None
            try:
                prev_hwnd = win32gui.GetForegroundWindow()
            except Exception:
                pass

            # ── Persistent un-clip thread ──
            unclip_stop = threading.Event()

            def _unclip_loop():
                while not unclip_stop.is_set():
                    ctypes.windll.user32.ClipCursor(None)
                    unclip_stop.wait(0.01)

            unclip_thread = threading.Thread(target=_unclip_loop, daemon=True)
            unclip_thread.start()

            # Alt key to unlock SetForegroundWindow restriction
            ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.05)

            ctypes.windll.user32.AllowSetForegroundWindow(-1)

            # Force BongoCat to front
            ctypes.windll.user32.SetWindowPos(
                self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            )
            win32gui.ShowWindow(self.hwnd, SW_RESTORE)
            win32gui.BringWindowToTop(self.hwnd)

            try:
                win32gui.SetForegroundWindow(self.hwnd)
            except Exception:
                try:
                    fg = win32gui.GetForegroundWindow()
                    fg_thread = ctypes.windll.user32.GetWindowThreadProcessId(fg, None)
                    our_thread = ctypes.windll.kernel32.GetCurrentThreadId()
                    ctypes.windll.user32.AttachThreadInput(fg_thread, our_thread, True)
                    win32gui.SetForegroundWindow(self.hwnd)
                    ctypes.windll.user32.AttachThreadInput(fg_thread, our_thread, False)
                except Exception:
                    pass

            time.sleep(0.5)  # Wait for BongoCat to fully appear

            # Move cursor with retries
            for _ in range(3):
                try:
                    win32api.SetCursorPos((screen_x, screen_y))
                except Exception:
                    pass
                time.sleep(0.02)
                try:
                    cur = win32api.GetCursorPos()
                    if abs(cur[0] - screen_x) <= 2 and abs(cur[1] - screen_y) <= 2:
                        break
                except Exception:
                    pass

            # Click via SendInput
            MOUSEEVENTF_LEFTDOWN = 0x0002
            MOUSEEVENTF_LEFTUP = 0x0004

            class MOUSEINPUT(ctypes.Structure):
                _fields_ = [
                    ("dx", ctypes.wintypes.LONG),
                    ("dy", ctypes.wintypes.LONG),
                    ("mouseData", ctypes.wintypes.DWORD),
                    ("dwFlags", ctypes.wintypes.DWORD),
                    ("time", ctypes.wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
                ]

            class INPUT(ctypes.Structure):
                class _INPUT(ctypes.Union):
                    _fields_ = [("mi", MOUSEINPUT)]
                _fields_ = [
                    ("type", ctypes.wintypes.DWORD),
                    ("_input", _INPUT),
                ]

            inp_down = INPUT()
            inp_down.type = 0  # INPUT_MOUSE
            inp_down._input.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
            inp_up = INPUT()
            inp_up.type = 0
            inp_up._input.mi.dwFlags = MOUSEEVENTF_LEFTUP

            # 1st click — wake up cursor (fullscreen hides it)
            ctypes.windll.user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
            time.sleep(0.01)
            ctypes.windll.user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))
            time.sleep(0.1)

            # 2nd click — actual chest click
            ctypes.windll.user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
            time.sleep(0.01)
            ctypes.windll.user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))
            time.sleep(0.03)

            print(f"  [{timestamp}] 🖱️  Click at ({screen_x}, {screen_y})",
                  flush=True)

            # ══════════════════════════════════════════════
            #  RESTORE everything
            # ══════════════════════════════════════════════
            unclip_stop.set()

            ctypes.windll.user32.SetWindowPos(
                self.hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            )

            if orig:
                try:
                    win32api.SetCursorPos(orig)
                except Exception:
                    pass

            ctypes.windll.user32.ClipCursor(None)
            if prev_hwnd and win32gui.IsWindow(prev_hwnd):
                time.sleep(0.1)
                try:
                    ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
                    win32gui.SetForegroundWindow(prev_hwnd)
                except Exception:
                    pass

        except Exception as e:
            try:
                unclip_stop.set()
            except Exception:
                pass
            try:
                ctypes.windll.user32.SetWindowPos(
                    self.hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                )
            except Exception:
                pass
            print(f"  ⚠️  Click error: {e}", flush=True)

    def run(self):
        alive_status = "ON" if self.keep_alive else "OFF"
        print(flush=True)
        print(f"  ⌨️  F6 = Pause/Resume", flush=True)
        print(f"  ⌨️  F7 = Stop", flush=True)
        print(f"  ⌨️  F8 = Keep Alive ({alive_status})", flush=True)
        print(flush=True)
        print(f"  📋 Check every {CHECK_INTERVAL}s | "
              f"Confidence ≥ {CONFIDENCE_THRESHOLD} | "
              f"Cooldown {POST_CLICK_COOLDOWN}s", flush=True)
        print("─" * 50, flush=True)
        print(f"  👀 Scanning...", flush=True)

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

                        elapsed = int(time.time() - start_time)
                        mins, secs = divmod(elapsed, 60)
                        hrs, mins = divmod(mins, 60)
                        print(
                            f"  [{ts}] 📦 #{self.loot_count} "
                            f"({confidence:.0%}) ⏱️{hrs:02d}:{mins:02d}:{secs:02d}",
                            flush=True
                        )

                        self.click_chest(x, y)
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
            print("─" * 50, flush=True)
            print(f"  📊 Session: {self.loot_count} chests in {hrs:02d}:{mins:02d}:{secs:02d}", flush=True)
            print(flush=True)
            # Clear any stale buffered input before waiting for user
            try:
                import msvcrt
                while msvcrt.kbhit():
                    msvcrt.getch()
            except Exception:
                pass
            input("  Press Enter to exit...")


def main():
    # stdout/stderr are already write-through, but flush once at startup
    # in case anything was buffered before reconfigure
    sys.stdout.flush()
    sys.stderr.flush()

    # Prevent mouse clicks on the console from freezing output
    disable_quick_edit()

    template_path = resource_path("chest_template.png")

    print()
    print("═" * 50, flush=True)
    print("  🐱 Bongo Cat Auto-Loot", flush=True)
    print("═" * 50, flush=True)

    # ── Check if Bongo Cat runs as admin; elevate only if needed ─
    import win32process
    results = []
    def _enum_cb(hwnd, data):
        if win32gui.IsWindowVisible(hwnd) and WINDOW_TITLE.lower() in win32gui.GetWindowText(hwnd).lower():
            data.append(hwnd)
    win32gui.EnumWindows(_enum_cb, results)

    if results:
        try:
            _, pid = win32process.GetWindowThreadProcessId(results[0])
            if is_process_elevated(pid) and not is_admin():
                elevate()  # re-launch with admin and exit current process
        except Exception as e:
            print(f"  ⚠️  Could not check Bongo Cat elevation: {e}", flush=True)
    # ────────────────────────────────────────────────────────────

    looter = BongoCatAutoLooter(template_path)
    looter.run()


if __name__ == "__main__":
    main()
