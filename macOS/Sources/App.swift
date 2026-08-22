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
    @State private var launchAtLogin: Bool = false

    var body: some Scene {
        MenuBarExtra {
            VStack(alignment: .leading, spacing: 12) {
                // Header
                HStack(alignment: .center) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Time-to-Sleep")
                            .font(.headline)
                        Text("Provider Ledger")
                            .font(.caption2)
                            .foregroundColor(.secondary)
                    }
                    Spacer()
                    HStack(spacing: 8) {
                        if let dashboardURL = monitor.dashboardURL {
                            Button {
                                NSWorkspace.shared.open(dashboardURL)
                            } label: {
                                HStack(spacing: 3) {
                                    Text("Ledger")
                                    Image(systemName: "arrow.up.right")
                                }
                                .font(.caption)
                            }
                            .buttonStyle(.borderless)
                            .foregroundColor(.accentColor)
                        }
                        
                        if let trendsURL = monitor.trendsURL {
                            Button {
                                NSWorkspace.shared.open(trendsURL)
                            } label: {
                                HStack(spacing: 3) {
                                    Text("Trends")
                                    Image(systemName: "chart.xyaxis.line")
                                }
                                .font(.caption)
                            }
                            .buttonStyle(.borderless)
                            .foregroundColor(.accentColor)
                        }
                    }
                }
                
                if let error = monitor.lastFetchError {
                    HStack(spacing: 4) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundColor(.orange)
                        Text(error)
                            .font(.caption2)
                            .foregroundColor(.secondary)
                            .lineLimit(2)
                    }
                    .padding(6)
                    .background(Color.orange.opacity(0.1))
                    .cornerRadius(6)
                }
                
                Divider()
                
                // Account list
                if monitor.accounts.isEmpty && monitor.lastFetchError == nil {
                    HStack {
                        ProgressView()
                            .controlSize(.small)
                        Text("Fetching quota data...")
                            .foregroundColor(.secondary)
                            .font(.caption)
                    }
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 16)
                } else {
                    VStack(spacing: 8) {
                        ForEach(monitor.accounts, id: \.account_id) { account in
                            AccountView(
                                account: account,
                                history: monitor.accountHistory[account.account_id] ?? []
                            )
                        }
                    }
                }
                
                Divider()
                
                // Launch at login toggle
                Toggle("Launch at Login", isOn: Binding(
                    get: { LaunchAtLoginHelper.shared.isEnabled },
                    set: { LaunchAtLoginHelper.shared.isEnabled = $0 }
                ))
                .font(.caption)
                
                // Footer
                HStack {
                    Button {
                        Task { await monitor.fetchUsage(forceRefresh: false) }
                    } label: {
                        if monitor.isRefreshing {
                            ProgressView().controlSize(.mini)
                        } else {
                            Text("Refresh")
                        }
                    }
                    .controlSize(.small)
                    .disabled(monitor.isRefreshing)
                    .keyboardShortcut("r", modifiers: .command)
                    
                    Button("Preferences…") {
                        PreferencesWindowManager.shared.show(monitor: monitor)
                    }
                    .controlSize(.small)
                    .keyboardShortcut(",", modifiers: .command)
                    
                    Spacer()
                    
                    Button("Quit") {
                        BackendRunner.shared.stop()
                        NSApplication.shared.terminate(nil)
                    }
                    .controlSize(.small)
                    .keyboardShortcut("q", modifiers: .command)
                }
            }
            .padding(14)
            .frame(width: 330)
            .fixedSize(horizontal: true, vertical: true)
        } label: {

            HStack(spacing: 4) {
                if let img = NSImage(named: "MenuIcon") {
                    let _ = img.isTemplate = true
                    Image(nsImage: img)
                } else {
                    Image(systemName: "chart.bar.fill")
                }
                
                if let maxPct = monitor.highestUsagePercent, !monitor.accounts.isEmpty {
                    Text("\(Int(round(maxPct)))%")
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                }
                
                if monitor.needsAttention {
                    Image(systemName: "exclamationmark.circle.fill")
                        .foregroundColor(.orange)
                }
            }
        }
        .menuBarExtraStyle(.window)
    }
}


struct SparklineView: View {
    let points: [HistoryPointModel]
    
    var body: some View {
        if points.count >= 2 {
            GeometryReader { geo in
                let w = geo.size.width
                let h = geo.size.height
                let maxPct = max(100.0, points.map { $0.used_percent }.max() ?? 100.0)
                
                Path { path in
                    for (index, point) in points.enumerated() {
                        let x = (CGFloat(index) / CGFloat(points.count - 1)) * w
                        let normY = max(0, min(100, point.used_percent)) / maxPct
                        let y = h - (CGFloat(normY) * (h - 4)) - 2
                        if index == 0 {
                            path.move(to: CGPoint(x: x, y: y))
                        } else {
                            path.addLine(to: CGPoint(x: x, y: y))
                        }
                    }
                }
                .stroke(Color.accentColor.opacity(0.85), lineWidth: 1.5)
            }
            .frame(height: 18)
            .padding(.top, 2)
        }
    }
}

struct AccountView: View {
    let account: Account
    var history: [HistoryPointModel] = []
    
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .center) {
                Text(accountDisplayName(account))
                    .font(.subheadline)
                    .fontWeight(.semibold)
                
                if let plan = account.plan_type, !plan.isEmpty {
                    Text(plan.uppercased())
                        .font(.system(size: 9, weight: .bold))
                        .padding(.horizontal, 5)
                        .padding(.vertical, 2)
                        .background(Color.secondary.opacity(0.12))
                        .cornerRadius(4)
                        .foregroundColor(.secondary)
                }
                
                Spacer()
                
                HStack(spacing: 4) {
                    Circle()
                        .fill(statusColor(account.status))
                        .frame(width: 7, height: 7)
                    Text(account.status.replacingOccurrences(of: "_", with: " ").capitalized)
                        .font(.caption2)
                        .fontWeight(.medium)
                        .foregroundColor(statusColor(account.status))
                }
            }
            
            if let email = account.configured_email {
                Text(email)
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
            
            if let windows = account.windows, !windows.isEmpty {
                VStack(spacing: 5) {
                    ForEach(windows, id: \.id) { window in
                        VStack(alignment: .leading, spacing: 2) {
                            HStack {
                                Text(formatWindowId(window.id))
                                    .font(.system(size: 10))
                                    .foregroundColor(.secondary)
                                Spacer()
                                Text(String(format: "%.1f%%", window.used_percent))
                                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                                    .foregroundColor(windowColor(window.used_percent))
                            }
                            ProgressView(value: min(100, max(0, window.used_percent)), total: 100)
                                .progressViewStyle(.linear)
                                .tint(windowColor(window.used_percent))
                                
                            if let resetsText = formatResetsAt(window.resets_at), !resetsText.isEmpty {
                                Text(resetsText)
                                    .font(.system(size: 9))
                                    .foregroundColor(.secondary)
                            }
                        }
                    }
                }
                .padding(.top, 2)
            }
            
            if !history.isEmpty {
                SparklineView(points: history)
            }
            
            if let message = account.message {
                Text(message)
                    .font(.caption2)
                    .foregroundColor(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(10)
        .background(Color(NSColor.controlBackgroundColor).opacity(0.5))
        .cornerRadius(8)
    }
    
    private func accountDisplayName(_ account: Account) -> String {
        if account.account_id == "codex-primary" { return "Codex Primary" }
        if account.account_id == "codex-secondary" { return "Codex Secondary" }
        return account.provider.capitalized
    }
    
    private func statusColor(_ status: String) -> Color {
        switch status {
        case "live": return .green
        case "unavailable", "rate_limited": return .red
        case "cached", "stale": return .orange
        default: return .secondary
        }
    }
    
    private func windowColor(_ percent: Double) -> Color {
        if percent >= 90 { return .red }
        if percent >= 75 { return .orange }
        return .accentColor
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


