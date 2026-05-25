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

# 4. PyTorch с CUDA 12.1 (ОБЯЗАТЕЛЬНО для GPU-ускорения WhisperX):
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 5. Остальные зависимости
pip install -r requirements.txt

# 6. Проверь что всё настроено правильно (особенно CUDA!)
python tools/check_cuda.py

# 7. Запусти GUI
python main.py
```

## ⚠ Если транскрипция идёт МЕДЛЕННО (GPU не используется)

Самая частая проблема — **PyTorch установлен в CPU-only сборке**. Симптомы:
- Процессор загружен на 100%, видеокарта простаивает
- 10-минутное видео транскрибируется час и больше

Запусти `python tools/check_cuda.py` — он покажет точную причину и команду для починки.
Скорее всего тебе нужно:

```bash
pip uninstall -y torch torchaudio torchvision
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```

На правильно настроенной RTX 4070 Ti с `large-v3` транскрипция должна идти
**×15–30 быстрее реального времени** (час видео — ~2–4 минуты).
В логе ты увидишь строку вида `Транскрипция: 120.3с (×15.2 от реального времени)`.

### Способы дополнительно ускорить транскрипцию

1. **Понизь модель** в настройках: `medium` ≈ в 2 раза быстрее `large-v3`,
   `small` — ещё в 2 раза, точность отличная для речи на основных языках.
2. **Включи `skip_alignment`** в настройках Whisper — пропустит word-level
   alignment (×2 быстрее), но субтитры будут на уровне фраз, не word-by-word.
3. **Увеличь `batch_size`** до 24-32 (на RTX 4070 Ti 12 ГБ это безопасно для
   `medium`, для `large-v3` лучше 16).

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
