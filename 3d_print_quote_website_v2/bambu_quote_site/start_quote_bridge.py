"""Start the quote bridge without saving or displaying its credential."""

import getpass
import os
from pathlib import Path
import subprocess
import sys

from step_converter import OCP_PACKAGE, dependency_dir

MIN_TOKEN_LENGTH = 32


def read_token_in_console():
    if not sys.stdin.isatty():
        return ""
    print("無法開啟輸入框。請輸入原有橋接金鑰後按 Enter，輸入時不會顯示字元。")
    try:
        return getpass.getpass("QUOTE_BRIDGE_TOKEN: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def read_token():
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        return read_token_in_console()
    try:
        window = tk.Tk()
    except tk.TclError:
        return read_token_in_console()
    window.withdraw()
    window.title("3D 列印估價 · 啟動切片橋接")
    window.resizable(False, False)
    window.attributes("-topmost", True)

    panel = ttk.Frame(window, padding=20)
    panel.grid()
    ttk.Label(panel, text="請輸入 Render 原本設定的 QUOTE_BRIDGE_TOKEN。").grid(
        row=0, column=0, columnspan=3, sticky="w"
    )
    entry = ttk.Entry(panel, show="*", width=43, exportselection=False)
    entry.grid(row=1, column=0, columnspan=2, pady=12, sticky="ew")
    feedback = ttk.Label(panel, text=" ", foreground="#a22222")
    feedback.grid(row=2, column=0, columnspan=3, sticky="w")
    token = ""

    def paste():
        try:
            value = window.clipboard_get().strip()
        except tk.TclError:
            value = ""
        if not value:
            feedback.config(text="剪貼簿是空的。請先複製原本的金鑰。")
            return
        entry.delete(0, "end")
        entry.insert(0, value)
        feedback.config(text=" ")
        entry.focus_set()

    def start(_event=None):
        nonlocal token
        value = entry.get().strip()
        if len(value) < MIN_TOKEN_LENGTH:
            feedback.config(text="金鑰至少要有 32 個字元，請確認已複製完整。")
            entry.focus_set()
            return
        token = value
        window.destroy()

    ttk.Button(panel, text="貼上金鑰", command=paste).grid(row=1, column=2, padx=(8, 0))
    ttk.Button(panel, text="啟動切片橋接", command=start).grid(row=3, column=2, pady=(10, 0))
    ttk.Button(panel, text="取消", command=window.destroy).grid(row=3, column=1, pady=(10, 0), sticky="e")
    window.bind("<Escape>", lambda _event: window.destroy())
    window.bind("<Return>", start)
    window.deiconify()
    entry.focus_set()
    window.mainloop()
    return token


def confirm_step_installation():
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        return input("安裝 STEP 轉檔元件（約 50 MB）？[Y/n] ").strip().lower() != "n"
    window = tk.Tk()
    window.withdraw()
    window.attributes("-topmost", True)
    try:
        return messagebox.askyesno(
            "啟用 STEP 匯入",
            "STEP 匯入需要下載一次轉檔元件（約 50 MB）。\n要現在安裝嗎？",
            default="yes", parent=window,
        )
    finally:
        window.destroy()


def prepare_step(converter):
    def can_convert():
        return subprocess.run([sys.executable, "-I", str(converter), "--check"],
                              capture_output=True, timeout=20, check=False).returncode == 0

    try:
        if can_convert() or not confirm_step_installation():
            return
        print("正在安裝 STEP 轉檔元件，請保持視窗開著。", flush=True)
        install_env = dict(os.environ)
        install_env.pop("QUOTE_BRIDGE_TOKEN", None)
        subprocess.run(
            [sys.executable, "-I", "-m", "pip", "--isolated", "install", "--upgrade",
             "--index-url", "https://pypi.org/simple", "--only-binary=:all:",
             "--target", str(dependency_dir()), OCP_PACKAGE],
            env=install_env, timeout=240, check=True,
        )
        if not can_convert():
            print("剛安裝的 STEP 元件無法載入。STL、3MF 仍可使用。", flush=True)
    except (OSError, EOFError, subprocess.SubprocessError) as error:
        print(f"STEP 元件安裝未完成。STL、3MF 仍可使用。{type(error).__name__}", flush=True)


def main():
    worker = Path(__file__).with_name("windows_worker.py")
    converter = Path(__file__).with_name("step_converter.py")
    if not worker.is_file() or not converter.is_file():
        print("請先將 ZIP 裡的所有檔案解壓縮到同一個資料夾。", file=sys.stderr)
        return 1

    token = os.environ.get("QUOTE_BRIDGE_TOKEN", "").strip()
    if len(token) < MIN_TOKEN_LENGTH:
        token = read_token()
        if len(token) < MIN_TOKEN_LENGTH:
            print("未啟動橋接。請重新開啟啟動檔並輸入原本的完整金鑰。", file=sys.stderr)
            return 1

    try:
        prepare_step(converter)
        return subprocess.call([sys.executable, "-u", str(worker)],
                               env={**os.environ, "QUOTE_BRIDGE_TOKEN": token})
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
