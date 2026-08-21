import SwiftUI

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
            VStack(alignment: .leading, spacing: 10) {
                Text("Provider Ledger")
                    .font(.headline)
                
                if let error = monitor.lastFetchError {
                    Text("Error: \(error)")
                        .foregroundColor(.red)
                        .font(.caption)
                }
                
                if monitor.accounts.isEmpty && monitor.lastFetchError == nil {
                    Text("Fetching data...")
                        .foregroundColor(.secondary)
                        .font(.caption)
                } else {
                    ForEach(monitor.accounts, id: \.account_id) { account in
                        AccountView(account: account)
                    }
                }
                
                Divider()
                
                HStack {
                    Button("Refresh") {
                        Task { await monitor.fetchUsage() }
                    }
                    .keyboardShortcut("r", modifiers: .command)
                    
                    Spacer()
                    
                    Button("Quit") {
                        BackendRunner.shared.stop()
                        NSApplication.shared.terminate(nil)
                    }
                }
            }
            .padding()
            .frame(width: 320)
        } label: {
            HStack(spacing: 4) {
                if let img = NSImage(named: "MenuIcon") {
                    let _ = img.isTemplate = true
                    Image(nsImage: img)
                } else {
                    Image(systemName: "chart.bar.fill")
                }
                
                if monitor.needsAttention {
                    Image(systemName: "exclamationmark.circle.fill")
                }
            }
        }
        .menuBarExtraStyle(.window)
    }
}

struct AccountView: View {
    let account: Account
    
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(account.provider.capitalized)
                    .font(.subheadline)
                    .fontWeight(.bold)
                Spacer()
                Text(account.status.capitalized)
                    .font(.caption)
                    .foregroundColor(statusColor(account.status))
            }
            
            if let email = account.configured_email {
                Text(email)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            
            if let windows = account.windows {
                ForEach(windows, id: \.id) { window in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text(formatWindowId(window.id))
                                .font(.caption2)
                            Spacer()
                            Text(String(format: "%.1f%%", window.used_percent))
                                .font(.caption2)
                        }
                        ProgressView(value: min(100, max(0, window.used_percent)), total: 100)
                            .progressViewStyle(.linear)
                            .tint(window.used_percent > 90 ? .red : .accentColor)
                            
                        if let resetsText = formatResetsAt(window.resets_at), !resetsText.isEmpty {
                            Text(resetsText)
                                .font(.system(size: 9))
                                .foregroundColor(.secondary)
                        }
                    }
                }
            }
            
            if let message = account.message {
                Text(message)
                    .font(.caption2)
                    .foregroundColor(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(.vertical, 4)
    }
    
    private func statusColor(_ status: String) -> Color {
        switch status {
        case "live": return .green
        case "unavailable", "rate_limited": return .red
        case "cached", "stale": return .orange
        default: return .secondary
        }
    }
    
    private func formatWindowId(_ id: String) -> String {
        return id.split(separator: "_").map { $0.capitalized }.joined(separator: " ")
    }
    
    private func formatResetsAt(_ dateString: String?) -> String? {
        guard let dateString = dateString else { return nil }
        
        let isoFormatter = ISO8601DateFormatter()
        var date = isoFormatter.date(from: dateString)
        
        if date == nil {
            isoFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            date = isoFormatter.date(from: dateString)
        }
        
        guard let validDate = date else { return nil }
        
        let displayFormatter = DateFormatter()
        displayFormatter.dateFormat = "EEE, MMM d, h:mm a"
        return "Resets \(displayFormatter.string(from: validDate))"
    }
}
