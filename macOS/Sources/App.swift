import SwiftUI
import AppKit
import ServiceManagement

class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        BackendRunner.shared.start()
    }

    func applicationWillTerminate(_ notification: Notification) {
        BackendRunner.shared.stop()
    }
}

@main
struct TimeToSleepApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var monitor = UsageMonitor()

    var body: some Scene {
        MenuBarExtra {
            CommandMenuContentView(monitor: monitor)
        } label: {
            CommandMenuBarLabel(monitor: monitor)
        }
        .menuBarExtraStyle(.window)
    }
}
