# macOS 27 Clean APFS Disk Builder

Automated builder for clean Apple Silicon macOS disk images using native Apple tools (`asr`, `hdiutil`, `diskutil`) on GitHub Actions macOS runners.

## How it works

1. Downloads official macOS IPSW restore image from Apple CDN.
2. Decrypts RootFS and Cryptex AEA containers.
3. Creates a 64 GB raw disk with GUID Partition Table and native APFS Container.
4. Restores RootFS via Apple Software Restore (`asr`).
5. Stages Cryptex libraries into `/Volumes/Preboot/Cryptexes/OS`.
6. Compresses and splits the result into release parts under 2 GB.

## How to extract on Windows

After downloading all `disk.raw.zst.part_*` files from the GitHub Release into one directory:

```bash
# 1. Concatenate all parts
cat disk.raw.zst.part_* > disk.raw.zst

# 2. Decompress with zstd
zstd -d disk.raw.zst -o disk.raw
```

Then attach `disk.raw` directly to QEMU as an NVMe or virtio block device.
