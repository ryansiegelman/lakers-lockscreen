#!/bin/bash
# Installs an image as the wallpaper background and re-renders.
#   ./install-background.sh ~/Downloads/water.jpg
# With no argument, grabs the newest image from ~/Downloads.
set -e
cd "$(dirname "$0")"
SRC="$1"
if [ -z "$SRC" ]; then
  SRC=$(ls -t ~/Downloads/*.{jpg,jpeg,png,JPG,JPEG,PNG} 2>/dev/null | head -1)
  [ -z "$SRC" ] && { echo "No image found in ~/Downloads. Pass a path explicitly."; exit 1; }
  echo "Using newest image from Downloads: $SRC"
fi
mkdir -p assets/backgrounds
rm -f assets/backgrounds/default.*
cp "$SRC" "assets/backgrounds/default.${SRC##*.}"
./.venv/bin/python -c "
from PIL import Image; im = Image.open('$SRC')
print('Installed %dx%d background' % im.size)
if im.width < 1206 or im.height < 2622:
    print('NOTE: smaller than the screen (1206x2622) in at least one axis - it will be upscaled and may look soft.')"
./.venv/bin/python generate.py -o out/wallpaper.png
