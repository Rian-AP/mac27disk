# macOS 27 Clean APFS Disk Builder

Automated builder for clean Apple Silicon macOS virtual machine disks using Apple's official `Virtualization.framework` (`VZMacOSInstaller`) on GitHub Actions Apple Silicon runners.

## How it works

1. Runs on a real Apple Silicon (`macos-15`) runner.
2. Downloads official macOS IPSW restore image from Apple CDN.
3. Automatically sets up GPT, APFS container, and all 4 required volumes:
   - `Macintosh HD` (Sealed System snapshot)
   - `Preboot` (Containing complete `Cryptexes/OS` with `dyld_shared_cache_arm64e`, boot manifests and tickets)
   - `Recovery` (Apple Recovery environment)
   - `Data` (APFS Data volume)
4. Compresses and splits the result into release parts under 2 GB.

## How to extract on Windows

After downloading all `disk.img.zst.part_*` files from the GitHub Release into one directory:

```bash
# 1. Concatenate all parts
cat disk.img.zst.part_* > disk.img.zst

# 2. Decompress with zstd (or 7-Zip with zstd support)
zstd -d disk.img.zst -o disk.img
```

Then attach `disk.img` directly to QEMU as a block device.
