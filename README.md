# AI Short Video Clip Generator

Автоматизированный AI-конвейер для превращения длинного видеоконтента (стримы, подкасты,
интервью, геймплеи, реакции) в короткие вертикальные клипы 9:16 для TikTok, YouTube Shorts,
Reels и других clip-based платформ.

Полностью **локальная** обработка — никаких облачных API. Используются Ollama (LLM),
WhisperX (распознавание речи), FFmpeg (NVENC) и PyQt6 (GUI).

## Возможности (ранняя версия)

- 🎬 Загрузка локальных видео или скачивание с YouTube/Twitch/любых yt-dlp источников
- 🧠 Поиск high-engagement моментов через локальный LLM (Ollama)
- 🗣 Word-level транскрипция через WhisperX (GPU, batched)
- ✂️ Автоматическая нарезка клипов FFmpeg-ом с NVENC-ускорением
- 📱 Адаптация под вертикальный 9:16 (center crop + размытый фон)
- 💬 Два стиля субтитров на выбор: word-by-word (анимация как CapCut/Opus Clip)
  и классические по фразам
- 🔁 Batch-обработка: очередь из нескольких видео подряд
- ⚙️ Выбор моделей Whisper и Ollama прямо в настройках GUI

## Системные требования

Оптимизировано под:
- **CPU:** Ryzen 7 5800X3D (8 ядер / 16 потоков)
- **GPU:** RTX 4070 Ti (12 ГБ VRAM, CUDA 12, NVENC)
- **RAM:** 48 ГБ
- **OS:** Windows 10/11 или Linux

Для других конфигураций конвейер автоматически подстраивается (CPU fallback,
выбор compute_type, размер batch).

## Установка

```bash
# 1. Установи Python 3.10–3.11
# 2. Установи FFmpeg с NVENC поддержкой (https://www.gyan.dev/ffmpeg/builds/)
# 3. Установи Ollama (https://ollama.com)
ollama pull llama3.1:8b
ollama pull qwen2.5:14b

# 4. PyTorch с CUDA 12.1 (обязательно для GPU-ускорения WhisperX):
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 5. Остальные зависимости
pip install -r requirements.txt

# 6. Запусти GUI
python main.py
```

## Архитектура

```
main.py                — точка входа (PyQt6)
config.yaml            — настройки по умолчанию
src/
├── app_config.py      — загрузка/сохранение конфига
├── gui/
│   ├── main_window.py — главное окно
│   ├── settings_dialog.py — диалог настроек
│   └── workers.py     — QThread воркеры для пайплайна
└── core/
    ├── hardware.py    — определение GPU/CPU/NVENC
    ├── downloader.py  — yt-dlp обёртка
    ├── transcriber.py — WhisperX (word-level timestamps)
    ├── analyzer.py    — Ollama LLM для поиска моментов
    ├── reframer.py    — 9:16 кадрирование (center + blur)
    ├── subtitler.py   — ASS-субтитры (word-by-word / классика)
    ├── clipper.py     — FFmpeg + NVENC рендер
    ├── pipeline.py    — оркестрация
    └── utils.py
```

## Roadmap

- [ ] Face/person tracking для smart auto-reframe (YOLO)
- [ ] A/B варианты одного клипа (разные hook'и, обложки)
- [ ] Встроенный preview-плеер
- [ ] Автопубликация в TikTok/YouTube Shorts через API
- [ ] Папка-вотчер для авто-импорта
- [ ] Self-improving feedback loop (анализ статистики опубликованных клипов)
