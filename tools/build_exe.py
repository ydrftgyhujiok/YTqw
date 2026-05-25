"""Сборка standalone EXE через PyInstaller (Windows).

Usage:
    pip install pyinstaller
    python tools/build_exe.py

Результат в dist/ai-clip-gen/ai-clip-gen.exe — запускается без консоли.
Конфиг и профили лежат в %USERPROFILE%\\.ai_clip_gen\\ независимо от EXE.

Внешние зависимости (НЕ упаковываются — нужны в системе или в PATH):
- ffmpeg.exe / ffprobe.exe  (путь задаётся в Настройки → Пути)
- Ollama (запущен отдельно, http://localhost:11434)
- NVIDIA GPU driver + CUDA-сборка PyTorch

Если хочешь упаковать ffmpeg вместе с EXE — положи ffmpeg.exe и ffprobe.exe
рядом со скриптом перед сборкой, скрипт их подхватит автоматически.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "ai-clip-gen.spec"


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller не установлен. Поставь: pip install pyinstaller")
        sys.exit(2)


def write_spec() -> None:
    # Опциональные внешние бинарники
    extras: list[str] = []
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        p = ROOT / name
        if p.exists():
            extras.append(f"        (r'{p}', '.'),")
    binaries_block = "[\n" + "\n".join(extras) + "\n    ]" if extras else "[]"

    config_path = ROOT / "config.yaml"
    datas_entries = []
    if config_path.exists():
        datas_entries.append(f"        (r'{config_path}', '.'),")
    datas_block = "[\n" + "\n".join(datas_entries) + "\n    ]" if datas_entries else "[]"

    spec = f"""# -*- mode: python ; coding: utf-8 -*-
# Авто-сгенерированный PyInstaller spec. Не редактируй вручную — пересоздаётся
# через `python tools/build_exe.py`.

block_cipher = None


a = Analysis(
    [r'{ROOT / "main.py"}'],
    pathex=[r'{ROOT}'],
    binaries={binaries_block},
    datas={datas_block},
    hiddenimports=[
        'PyQt6.sip',
        'yaml',
        'yt_dlp',
        'ollama',
        'faster_whisper',
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[
        # whisperx тащит за собой torch — не исключаем torch
        'tkinter',
        'matplotlib',
        'IPython',
        'notebook',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ai-clip-gen',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                # GUI-only, без чёрного окна консоли
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ai-clip-gen',
)
"""
    SPEC.write_text(spec, encoding="utf-8")
    print(f"Spec записан: {SPEC}")


def run_pyinstaller() -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        str(SPEC),
    ]
    print("Запускаю:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)


def cleanup() -> None:
    # build/ можно сносить, dist/ оставляем
    build_dir = ROOT / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)


def main() -> int:
    ensure_pyinstaller()
    write_spec()
    run_pyinstaller()
    cleanup()
    print()
    print("Готово.")
    print(f"EXE: {ROOT / 'dist' / 'ai-clip-gen' / 'ai-clip-gen.exe'}")
    print("Папку dist/ai-clip-gen можно переносить целиком.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
