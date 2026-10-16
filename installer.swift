import Foundation
import Virtualization

guard CommandLine.arguments.count >= 4 else {
    print("Usage: swift installer.swift <path-to-ipsw> <path-to-disk-img> <path-to-aux-img> [disk-size-gb]")
    exit(1)
}

let ipswPath = CommandLine.arguments[1]
let diskPath = CommandLine.arguments[2]
let auxPath = CommandLine.arguments[3]
let diskSizeGB = CommandLine.arguments.count >= 5 ? (UInt64(CommandLine.arguments[4]) ?? 64) : 64

let ipswURL = URL(fileURLWithPath: ipswPath)
let diskURL = URL(fileURLWithPath: diskPath)
let auxURL = URL(fileURLWithPath: auxPath)

print("=== Apple Silicon macOS Installer ===")
print("IPSW: \(ipswPath)")
print("Target Disk: \(diskPath) (\(diskSizeGB) GB)")
print("Auxiliary Storage: \(auxPath)")

print("1. Loading restore image metadata...")
let sem = DispatchSemaphore(value: 0)
var restoreImageOpt: VZMacOSRestoreImage?

VZMacOSRestoreImage.load(from: ipswURL) { result in
    switch result {
    case .success(let image):
        restoreImageOpt = image
    case .failure(let err):
        print("Failed to load restore image: \(err.localizedDescription)")
        exit(1)
    }
    sem.signal()
}
sem.wait()

guard let restoreImage = restoreImageOpt else {
    print("Error: Restore image object is nil")
    exit(1)
}

guard let configReq = restoreImage.mostFeaturefulSupportedConfiguration else {
    print("Error: No supported hardware configuration found in IPSW for this host")
    exit(1)
}

let hardwareModel = configReq.hardwareModel
guard hardwareModel.isSupported else {
    print("Error: Hardware model is not supported on this host")
    exit(1)
}

print("2. Creating sparse target disk (\(diskSizeGB) GB)...")
FileManager.default.createFile(atPath: diskPath, contents: nil)
let fileHandle = try FileHandle(forWritingTo: diskURL)
try fileHandle.truncate(atOffset: diskSizeGB * 1024 * 1024 * 1024)
try fileHandle.close()

print("3. Initializing NVRAM/Auxiliary storage...")
if FileManager.default.fileExists(atPath: auxPath) {
    try? FileManager.default.removeItem(at: auxURL)
}
let auxStorage = try VZMacAuxiliaryStorage(creatingStorageAt: auxURL, hardwareModel: hardwareModel, options: [.allowOverwrite])

print("4. Building VM configuration...")
let vmConfig = VZVirtualMachineConfiguration()
vmConfig.cpuCount = max(2, configReq.minimumSupportedCPUCount)
vmConfig.memorySize = max(4 * 1024 * 1024 * 1024, configReq.minimumSupportedMemorySize)
vmConfig.bootLoader = VZMacOSBootLoader()

let platform = VZMacPlatformConfiguration()
platform.hardwareModel = hardwareModel
platform.auxiliaryStorage = auxStorage
let machineId = VZMacMachineIdentifier()
platform.machineIdentifier = machineId
vmConfig.platform = platform

let diskAttachment = try VZDiskImageStorageDeviceAttachment(url: diskURL, readOnly: false)
let storageDevice = VZVirtioBlockDeviceConfiguration(attachment: diskAttachment)
vmConfig.storageDevices = [storageDevice]

try vmConfig.validate()

let vm = VZVirtualMachine(configuration: vmConfig)
print("5. Starting VZMacOSInstaller...")
let installer = VZMacOSInstaller(virtualMachine: vm, restoringFromImageAt: ipswURL)

var lastPercent = -1
let observer = installer.progress.observe(\.fractionCompleted, options: [.initial, .new]) { (progress, change) in
    let pct = Int(progress.fractionCompleted * 100)
    if pct != lastPercent {
        lastPercent = pct
        print("Installation progress: \(pct)%")
        fflush(stdout)
    }
}

var installError: Error?
installer.install { result in
    switch result {
    case .success:
        print("\n=== macOS Installation Completed Successfully! ===")
    case .failure(let err):
        installError = err
        print("\nInstallation failed: \(err.localizedDescription)")
    }
    sem.signal()
}

// Keep runloop alive for progress observation and async completion
while sem.wait(timeout: .now()) == .timedOut {
    RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.5))
}

_ = observer

if let err = installError {
    exit(2)
}

print("Done! disk.img and aux.img are ready.")
