import Foundation
import ServiceManagement

class LaunchAtLoginHelper {
    static let shared = LaunchAtLoginHelper()
    private let plistName = "com.zhoufuwang.TimeToSleep.plist"
    
    private var launchAgentURL: URL {
        let libraryURL = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask).first!
        return libraryURL.appendingPathComponent("LaunchAgents").appendingPathComponent(plistName)
    }
    
    var isEnabled: Bool {
        get {
            // First check SMAppService if supported and registered
            if #available(macOS 13.0, *) {
                if SMAppService.mainApp.status == .enabled {
                    return true
                }
            }
            // Fallback to LaunchAgent plist existence
            return FileManager.default.fileExists(atPath: launchAgentURL.path)
        }
        set {
            setLaunchAtLogin(enabled: newValue)
        }
    }
    
    func setLaunchAtLogin(enabled: Bool) {
        // Try modern SMAppService first
        if #available(macOS 13.0, *) {
            do {
                if enabled {
                    try SMAppService.mainApp.register()
                    print("Registered via SMAppService")
                    return
                } else if SMAppService.mainApp.status == .enabled {
                    try SMAppService.mainApp.unregister()
                    print("Unregistered via SMAppService")
                    return
                }
            } catch {
                print("SMAppService failed (\(error.localizedDescription)); using LaunchAgent fallback")
            }
        }
        
        // Robust LaunchAgent Fallback
        let fileManager = FileManager.default
        let launchAgentsDir = launchAgentURL.deletingLastPathComponent()
        
        if enabled {
            guard let appPath = Bundle.main.bundlePath as String? else { return }
            let plistContent: [String: Any] = [
                "Label": "com.zhoufuwang.TimeToSleep",
                "ProgramArguments": ["/usr/bin/open", "-a", appPath],
                "RunAtLoad": true,
                "ProcessType": "Interactive"
            ]
            
            do {
                try fileManager.createDirectory(at: launchAgentsDir, withIntermediateDirectories: true)
                let data = try PropertyListSerialization.data(fromPropertyList: plistContent, format: .xml, options: 0)
                try data.write(to: launchAgentURL)
                print("LaunchAgent created at \(launchAgentURL.path)")
            } catch {
                print("Failed to write LaunchAgent plist: \(error)")
            }
        } else {
            if fileManager.fileExists(atPath: launchAgentURL.path) {
                try? fileManager.removeItem(at: launchAgentURL)
                print("LaunchAgent removed")
            }
        }
    }
}
