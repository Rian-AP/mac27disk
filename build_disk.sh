#!/bin/bash
set -euo pipefail

IPSW_FILE="${1:-restore.ipsw}"
DISK_TARGET="target_disk.dmg"
DISK_SIZE="64g"

echo "=== 1. Extracting encrypted AEA images from IPSW ==="
mkdir -p aea_in dec_out

python3 -c "
import zipfile, os
with zipfile.ZipFile('$IPSW_FILE') as z:
    for name in z.namelist():
        if ('043-70867' in name or '043-70701' in name) and name.endswith('.dmg.aea'):
            print(f'Extracting {name}...')
            z.extract(name, 'aea_in')
"

echo "Deleting $IPSW_FILE to free 25 GB of disk space..."
rm -f "$IPSW_FILE"
df -h /

echo "=== 2. Decrypting RootFS and Cryptex with ipsw ==="
for aea in aea_in/*.dmg.aea; do
    echo "Decrypting $aea..."
    ipsw fw aea "$aea" -o dec_out/
done
rm -rf aea_in
df -h /

ROOTFS_DMG=$(ls dec_out/043-70867*.dmg | head -n 1)
CRYPTEX_DMG=$(ls dec_out/043-70701*.dmg | head -n 1)

echo "RootFS DMG:  $ROOTFS_DMG"
echo "Cryptex DMG: $CRYPTEX_DMG"

echo "=== 3. Creating 64 GB disk image ==="
hdiutil create -size "$DISK_SIZE" -layout GPTSPUD -fs APFS -volname "Macintosh HD" "$DISK_TARGET"
ls -lh "$DISK_TARGET"

echo "Attaching target disk image..."
RAW_DEV=$(hdiutil attach -nomount "$DISK_TARGET" | grep Apple_APFS | awk '{print $1}')
echo "Attached target APFS physical store: $RAW_DEV"

echo "=== 4. Running native Apple Software Restore (ASR) ==="
sudo asr restore --source "$ROOTFS_DMG" --target "$RAW_DEV" --erase --noprompt --noverify

echo "=== 5. Setting up Preboot volume in the target container ==="
diskutil list

# Query APFS container ID directly from diskutil info for the physical store partition
TARGET_CONTAINER=$(diskutil apfs list | grep -E "Container disk[0-9]+" | tail -n 1 | awk '{print $NF}')
echo "Target APFS Container: $TARGET_CONTAINER"

echo "Adding Preboot volume with Role B to $TARGET_CONTAINER..."
sudo diskutil apfs addVolume "$TARGET_CONTAINER" APFS Preboot -role B -mountpoint /Volumes/TargetPreboot

echo "Mounting Cryptex DMG..."
mkdir -p /tmp/cryptex_mnt
hdiutil attach "$CRYPTEX_DMG" -mountpoint /tmp/cryptex_mnt -readonly -nobrowse

echo "Copying Cryptex into TargetPreboot/Cryptexes/OS with ditto..."
sudo mkdir -p /Volumes/TargetPreboot/Cryptexes/OS
sudo ditto --noextattr /tmp/cryptex_mnt /Volumes/TargetPreboot/Cryptexes/OS

echo "Adding Data volume with Role D..."
sudo diskutil apfs addVolume "$TARGET_CONTAINER" APFS Data -role D -nomount || true

echo "Adding Recovery volume with Role R..."
sudo diskutil apfs addVolume "$TARGET_CONTAINER" APFS Recovery -role R -nomount || true

echo "Unmounting cleanly..."
hdiutil detach /tmp/cryptex_mnt
sudo diskutil unmount /Volumes/TargetPreboot || true

# Detach target disk image
BASE_DEV=$(echo "$RAW_DEV" | sed -E 's/s[0-9]+$//')
hdiutil detach "$BASE_DEV" || true

rm -rf dec_out
echo "=== Disk build complete! Generated $DISK_TARGET ==="
ls -lh "$DISK_TARGET"
