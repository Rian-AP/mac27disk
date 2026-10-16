#!/usr/bin/env python3
"""
Native APFS macOS 27 Disk Image Builder for Apple Silicon / QEMU
Uses macOS system utilities (hdiutil, asr, diskutil, ditto) via plistlib.
Deterministic, robust, zero fragile regex/grep.
"""

import sys
import os
import glob
import json
import plistlib
import subprocess
import zipfile
import shutil
import time

def log(msg):
    print(f"\n{'='*15} {msg} {'='*15}", flush=True)

def run_cmd(cmd, check=True, capture=False):
    print(f">> Running: {' '.join(cmd)}", flush=True)
    if capture:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if check and res.returncode != 0:
            print(f"ERROR ({res.returncode}): {res.stderr}", flush=True)
            sys.exit(res.returncode)
        return res.stdout
    else:
        res = subprocess.run(cmd)
        if check and res.returncode != 0:
            print(f"ERROR: Command failed with exit code {res.returncode}", flush=True)
            sys.exit(res.returncode)
        return None

def main():
    ipsw_file = sys.argv[1] if len(sys.argv) > 1 else "restore.ipsw"
    disk_target = "target_disk.dmg"
    disk_size = "64g"
    
    log(f"1. Extracting encrypted AEA images from {ipsw_file}")
    os.makedirs("aea_in", exist_ok=True)
    os.makedirs("dec_out", exist_ok=True)
    
    with zipfile.ZipFile(ipsw_file, 'r') as z:
        for name in z.namelist():
            if ("043-70867" in name or "043-70701" in name) and name.endswith(".dmg.aea"):
                print(f"Extracting {name}...", flush=True)
                z.extract(name, "aea_in")
                
    log("Deleting IPSW file to free 26 GB of disk space")
    if os.path.exists(ipsw_file):
        os.remove(ipsw_file)
    subprocess.run(["df", "-h", "/"])

    log("2. Decrypting RootFS and Cryptex with ipsw")
    aea_files = glob.glob("aea_in/*.dmg.aea")
    if not aea_files:
        print("ERROR: No .dmg.aea files found in aea_in!", flush=True)
        sys.exit(1)
        
    for aea in aea_files:
        print(f"Decrypting {aea}...", flush=True)
        run_cmd(["ipsw", "fw", "aea", aea, "-o", "dec_out/"])
        os.remove(aea)
        
    shutil.rmtree("aea_in", ignore_errors=True)
    subprocess.run(["df", "-h", "/"])
    
    rootfs_matches = glob.glob("dec_out/043-70867*.dmg")
    cryptex_matches = glob.glob("dec_out/043-70701*.dmg")
    if not rootfs_matches or not cryptex_matches:
        print(f"ERROR: Decrypted DMGs not found: rootfs={rootfs_matches}, cryptex={cryptex_matches}", flush=True)
        sys.exit(1)
        
    rootfs_dmg = rootfs_matches[0]
    cryptex_dmg = cryptex_matches[0]
    print(f"RootFS DMG:  {rootfs_dmg}", flush=True)
    print(f"Cryptex DMG: {cryptex_dmg}", flush=True)

    log(f"3. Creating {disk_size} target disk image")
    if os.path.exists(disk_target):
        os.remove(disk_target)
    run_cmd(["hdiutil", "create", "-size", disk_size, "-layout", "GPTSPUD", "-fs", "APFS", "-volname", "Macintosh HD", disk_target])
    
    log("Attaching target disk image")
    attach_xml = subprocess.check_output(["hdiutil", "attach", "-nomount", "-plist", disk_target])
    attach_data = plistlib.loads(attach_xml)
    
    raw_dev = None
    base_dev = None
    for entity in attach_data.get("system-entities", []):
        hint = entity.get("content-hint", "")
        dev = entity.get("dev-entry", "")
        if hint == "Apple_APFS":
            raw_dev = dev
        if hint == "GUID_partition_scheme":
            base_dev = dev
            
    if not raw_dev:
        print(f"ERROR: Could not find Apple_APFS partition in attach entities: {attach_data}", flush=True)
        sys.exit(1)
    print(f"Attached physical store partition: {raw_dev} (base: {base_dev})", flush=True)

    log("4. Running native Apple Software Restore (ASR)")
    run_cmd(["sudo", "asr", "restore", "--source", rootfs_dmg, "--target", raw_dev, "--erase", "--noprompt", "--noverify"])

    log("5. Resolving container & volume info via diskutil plist")
    apfs_xml = subprocess.check_output(["diskutil", "apfs", "list", "-plist"])
    apfs_data = plistlib.loads(apfs_xml)
    
    target_container = None
    system_uuid = None
    raw_dev_id = os.path.basename(raw_dev)
    
    for container in apfs_data.get("Containers", []):
        stores = [ps.get("DeviceIdentifier") for ps in container.get("PhysicalStores", [])]
        if raw_dev_id in stores:
            target_container = container.get("ContainerReference")
            for vol in container.get("Volumes", []):
                roles = vol.get("Roles", [])
                name = vol.get("Name", "")
                if "System" in roles or "Macintosh HD" in name:
                    system_uuid = vol.get("APFSVolumeUUID")
            break
            
    if not target_container:
        print(f"ERROR: Could not find container for physical store {raw_dev_id} in {apfs_data}", flush=True)
        sys.exit(1)
        
    print(f"Target APFS Container: {target_container}", flush=True)
    print(f"System Volume UUID:   {system_uuid}", flush=True)

    log(f"6. Adding Preboot volume with Role B to {target_container}")
    run_cmd(["sudo", "diskutil", "apfs", "addVolume", target_container, "APFS", "Preboot", "-role", "B", "-mountpoint", "/Volumes/TargetPreboot"])
    run_cmd(["sudo", "chmod", "-R", "777", "/Volumes/TargetPreboot"], check=False)

    log("7. Mounting Cryptex DMG and populating Preboot")
    cryptex_mount = "/tmp/cryptex_mnt"
    os.makedirs(cryptex_mount, exist_ok=True)
    run_cmd(["hdiutil", "attach", cryptex_dmg, "-mountpoint", cryptex_mount, "-readonly", "-nobrowse"])
    
    # 1. Official Cryptexes/OS tree
    run_cmd(["sudo", "mkdir", "-p", "/Volumes/TargetPreboot/Cryptexes/OS"])
    print("Copying Cryptex tree via ditto...", flush=True)
    run_cmd(["sudo", "ditto", "--noextattr", cryptex_mount, "/Volumes/TargetPreboot/Cryptexes/OS"])
    
    # 2. Raw os.dmg placed inside UUID/cryptex1/current/os.dmg
    uuids_to_seed = ["AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"]
    if system_uuid:
        uuids_to_seed.append(system_uuid)
        
    for u in uuids_to_seed:
        target_dir = f"/Volumes/TargetPreboot/{u}/cryptex1/current"
        run_cmd(["sudo", "mkdir", "-p", target_dir])
        print(f"Seeding {target_dir}/os.dmg...", flush=True)
        run_cmd(["sudo", "cp", cryptex_dmg, f"{target_dir}/os.dmg"])

    log("8. Adding Data & Recovery volumes to container")
    run_cmd(["sudo", "diskutil", "apfs", "addVolume", target_container, "APFS", "Data", "-role", "D", "-nomount"], check=False)
    run_cmd(["sudo", "diskutil", "apfs", "addVolume", target_container, "APFS", "Recovery", "-role", "R", "-nomount"], check=False)

    log("9. Unmounting and cleaning up")
    run_cmd(["hdiutil", "detach", cryptex_mount], check=False)
    run_cmd(["sudo", "diskutil", "unmount", "/Volumes/TargetPreboot"], check=False)
    if base_dev:
        run_cmd(["hdiutil", "detach", base_dev], check=False)
    shutil.rmtree("dec_out", ignore_errors=True)
    
    log(f"Disk build complete! Generated {disk_target}")
    subprocess.run(["ls", "-lh", disk_target])

if __name__ == "__main__":
    main()
