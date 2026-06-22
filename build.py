#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py — собирает каталог сайта из папок projects/.

Что делает:
  1. Сканирует projects/<NN>/ — находит картинки по именам (facade*, plan*, 3d*).
  2. Генерирует/обновляет миниатюры в projects/<NN>/thumbs/ (только изменённые).
  3. Читает метаданные из projects/<NN>/project.json.
  4. Пишет catalog.data.js (его грузит index.html).
  5. Проверяет структуру и печатает отчёт с предупреждениями.

Запуск:
    python3 build.py          # обычная сборка
    python3 build.py --force  # пересоздать ВСЕ миниатюры заново

Зависимость: Pillow  →  pip3 install Pillow
"""

import sys, json, re
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("✗ Нужна библиотека Pillow.  Установи:  pip3 install Pillow")

ROOT      = Path(__file__).resolve().parent
PROJECTS  = ROOT / "projects"
CATALOG   = ROOT / "catalog.data.js"
THUMB_MAX = 360                              # макс. сторона миниатюры, px
FULL_MAX  = 1600                             # макс. сторона «полной» картинки, px
JPG_Q     = 80                               # качество jpg-миниатюр
IMG_EXT   = (".png", ".jpg", ".jpeg", ".webp")
FORCE     = "--force" in sys.argv

# Категории картинок: ключ в каталоге → префикс имени файла
KINDS = [("facade", "facade"), ("plan", "plan"), ("r3d", "3d")]


def natural(name: str):
    """Натуральная сортировка: plan-2 идёт перед plan-10."""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r'(\d+)', name)]


def detect(folder: Path, prefix: str):
    """Все картинки в папке, чьё имя начинается с prefix (без thumbs/)."""
    files = [f for f in folder.iterdir()
             if f.is_file()
             and f.suffix.lower() in IMG_EXT
             and f.stem.lower().startswith(prefix)]
    return sorted(files, key=lambda f: natural(f.name))


def normalize_full(src: Path) -> bool:
    """Если картинка больше FULL_MAX — ужимает её на месте под web. True если ужал."""
    with Image.open(src) as im:
        if max(im.size) <= FULL_MAX:
            return False
        im = im.copy()
    im.thumbnail((FULL_MAX, FULL_MAX))
    if src.suffix.lower() in (".jpg", ".jpeg"):
        im.convert("RGB").save(src, "JPEG", quality=85, optimize=True)
    else:
        im.save(src, optimize=True)
    return True


def make_thumb(src: Path, dst: Path) -> bool:
    """Создаёт миниатюру, если её нет или исходник новее. Возвращает True если создал."""
    if not FORCE and dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return False
    im = Image.open(src)
    im.thumbnail((THUMB_MAX, THUMB_MAX))
    if dst.suffix.lower() in (".jpg", ".jpeg"):
        im.convert("RGB").save(dst, "JPEG", quality=JPG_Q, optimize=True)
    else:
        im.save(dst, optimize=True)
    return True


def main():
    if not PROJECTS.is_dir():
        sys.exit(f"✗ Нет папки {PROJECTS}")

    folders = sorted([f for f in PROJECTS.iterdir()
                      if f.is_dir() and not f.name.startswith((".", "_"))],
                     key=lambda f: natural(f.name))

    catalog, warnings = [], []
    thumbs_made = thumbs_removed = resized = 0

    for folder in folders:
        label = folder.name
        if not re.fullmatch(r"\d{2,}", label):
            warnings.append(f"{label}: имя папки не число (ожидается 01, 02, …)")

        # --- метаданные ---
        pj = folder / "project.json"
        meta = {}
        if pj.exists():
            try:
                meta = json.loads(pj.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                warnings.append(f"{label}: битый project.json ({e})")
        else:
            warnings.append(f"{label}: нет project.json")

        # --- картинки ---
        imgs = {key: detect(folder, prefix) for key, prefix in KINDS}
        if not imgs["facade"]:
            warnings.append(f"{label}: нет файла facade.*")

        # --- миниатюры ---
        thdir = folder / "thumbs"
        thdir.mkdir(exist_ok=True)
        wanted = set()
        for key, _ in KINDS:
            for f in imgs[key]:
                wanted.add(f.name)
                if normalize_full(f):
                    resized += 1
                if make_thumb(f, thdir / f.name):
                    thumbs_made += 1
        # подчистить миниатюры, у которых больше нет исходника
        for t in thdir.iterdir():
            if t.is_file() and t.name not in wanted:
                t.unlink()
                thumbs_removed += 1

        # --- этажность: из project.json, иначе по числу планировок ---
        floors = meta.get("floors") or (2 if len(imgs["plan"]) >= 2 else 1)

        catalog.append({
            "id":     label,
            "label":  label,
            "floors": floors,
            "a":      meta.get("area"),
            "w":      meta.get("width"),
            "d":      meta.get("depth"),
            "pages":  meta.get("pages", ""),
            "facade": [f.name for f in imgs["facade"]],
            "plan":   [f.name for f in imgs["plan"]],
            "r3d":    [f.name for f in imgs["r3d"]],
        })

    # --- запись catalog.data.js ---
    header = ("// АВТО-СГЕНЕРИРОВАНО build.py — вручную не редактировать.\n"
              "// Правь projects/<NN>/project.json и картинки, затем: python3 build.py\n"
              "window.CATALOG = [\n")
    body = ",\n".join("  " + json.dumps(e, ensure_ascii=False) for e in catalog)
    CATALOG.write_text(header + body + "\n];\n", encoding="utf-8")

    # --- отчёт ---
    with_3d = sum(1 for e in catalog if e["r3d"])
    print(f"✓ Проектов:         {len(catalog)}")
    print(f"✓ С 3D-видами:      {with_3d}")
    print(f"✓ Миниатюр создано: {thumbs_made}" + ("  (--force: все)" if FORCE else ""))
    if resized:
        print(f"✓ Картинок ужато до {FULL_MAX}px: {resized}")
    if thumbs_removed:
        print(f"✓ Лишних миниатюр удалено: {thumbs_removed}")
    print(f"✓ Записан:          {CATALOG.name}")
    if warnings:
        print(f"\n⚠ Предупреждения ({len(warnings)}):")
        for w in warnings:
            print("   •", w)
    else:
        print("\n✓ Предупреждений нет — всё чисто.")


if __name__ == "__main__":
    main()
