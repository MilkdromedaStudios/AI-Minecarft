from __future__ import annotations

from pathlib import Path
import argparse
import shutil
import yaml


def read_names(data_yaml: Path) -> list[str]:
    data = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    names = data.get("names", [])
    if isinstance(names, dict):
        return [str(names[i]) for i in sorted(names, key=lambda x: int(x))]
    return [str(x) for x in names]


def find_data_yaml(root: Path) -> Path:
    direct = root / "data.yaml"
    if direct.exists():
        return direct
    matches = list(root.rglob("data.yaml"))
    if not matches:
        raise FileNotFoundError(f"No data.yaml found under {root}")
    return matches[0]


def normalize(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def copy_split(source_root: Path, source_names: list[str], split: str, target_split: str,
               unified_names: list[str], output: Path, prefix: str) -> int:
    images_dir = source_root / split / "images"
    labels_dir = source_root / split / "labels"
    if not images_dir.exists():
        return 0

    out_images = output / target_split / "images"
    out_labels = output / target_split / "labels"
    out_images.mkdir(parents=True, exist_ok=True)
    out_labels.mkdir(parents=True, exist_ok=True)

    class_map = {}
    for source_id, source_name in enumerate(source_names):
        n = normalize(source_name)
        target_id = next(i for i, x in enumerate(unified_names) if normalize(x) == n)
        class_map[source_id] = target_id

    count = 0
    for image in images_dir.iterdir():
        if not image.is_file() or image.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue

        new_stem = f"{prefix}_{image.stem}"
        destination = out_images / f"{new_stem}{image.suffix.lower()}"
        shutil.copy2(image, destination)

        label = labels_dir / f"{image.stem}.txt"
        out_label = out_labels / f"{new_stem}.txt"
        if label.exists():
            converted = []
            for raw in label.read_text(encoding="utf-8").splitlines():
                parts = raw.split()
                if not parts:
                    continue
                old_id = int(parts[0])
                parts[0] = str(class_map[old_id])
                converted.append(" ".join(parts))
            out_label.write_text("\n".join(converted) + ("\n" if converted else ""), encoding="utf-8")
        else:
            out_label.write_text("", encoding="utf-8")
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--objects", type=Path, required=True)
    parser.add_argument("--mobs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    object_yaml = find_data_yaml(args.objects)
    mob_yaml = find_data_yaml(args.mobs)
    object_root = object_yaml.parent
    mob_root = mob_yaml.parent

    object_names = read_names(object_yaml)
    mob_names = read_names(mob_yaml)

    unified_names: list[str] = []
    seen = set()
    for name in object_names + mob_names:
        key = normalize(name)
        if key not in seen:
            seen.add(key)
            unified_names.append(name)

    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)

    total = 0
    total += copy_split(object_root, object_names, "train", "train", unified_names, args.output, "objects")
    total += copy_split(object_root, object_names, "valid", "valid", unified_names, args.output, "objects")
    total += copy_split(object_root, object_names, "val", "valid", unified_names, args.output, "objects")
    total += copy_split(object_root, object_names, "test", "test", unified_names, args.output, "objects")

    total += copy_split(mob_root, mob_names, "train", "train", unified_names, args.output, "mobs")
    total += copy_split(mob_root, mob_names, "valid", "valid", unified_names, args.output, "mobs")
    total += copy_split(mob_root, mob_names, "val", "valid", unified_names, args.output, "mobs")
    total += copy_split(mob_root, mob_names, "test", "test", unified_names, args.output, "mobs")

    data = {
        "path": str(args.output.resolve()),
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "names": {i: name for i, name in enumerate(unified_names)},
        "nc": len(unified_names),
    }
    (args.output / "data.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    print(f"Merged {total} images")
    print(f"Classes ({len(unified_names)}): {unified_names}")
    print(args.output / "data.yaml")


if __name__ == "__main__":
    main()
