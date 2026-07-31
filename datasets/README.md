# Training datasets

The repository treats the datasets as reproducible build inputs instead of committing gigabytes of raw images to normal Git history.

## Minecraft-Objects

- Source: Roboflow Universe
- Dataset ID: `minecraftdataset/minecraft-objects/2`
- Used for gameplay objects, blocks, ores, and mobs.
- Downloaded automatically by GitHub Actions.

## Minecraft Mobs YOLO Dataset

- Source: Hugging Face: `hmnshudhmn24/minecraft-mobs-yolo-dataset`
- License: CC BY 4.0
- Credit: Draco TLW (Muhammad Alimuhammadi)
- 2,585 gameplay images
- Classes: creeper, skeleton, spider, zombie, enderman
- Downloaded automatically by GitHub Actions.

`prepare_dataset.py` merges the two YOLO datasets into one training set and remaps their class IDs before `train_ci.py` trains `models/best.pt`.
