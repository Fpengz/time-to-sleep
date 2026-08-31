import SwiftUI
import AppKit

private enum CommandPalette {
    static let accent = Color(hex: 0xB7F36B)
    static let codex = Color(hex: 0x66C7E8)
    static let codexSecondary = Color(hex: 0x9F9AEF)
    static let claude = Color(hex: 0xEF9D69)
    static let antigravity = Color(hex: 0xB7F36B)
    static let live = Color(hex: 0x74D99F)
    static let warning = Color(hex: 0xF0B35D)
    static let danger = Color(hex: 0xEF756D)

    static func provider(_ account: Account) -> Color {
        switch account.provider.lowercased() {
        case "codex":
            return (account.account_id.contains("secondary") || account.account_id.contains("-2"))
                ? codexSecondary
                : codex
        case "claude": return claude
        case "antigravity": return antigravity
        default: return accent
        }
    }

    static func usage(_ percent: Double) -> Color {
        if percent >= 90 { return danger }
        if percent >= 75 { return warning }
        return accent
    }

    static func status(_ status: String) -> Color {
        switch status {
        case "live": return live
        case "cached", "stale": return warning
        case "rate_limited", "unavailable": return danger
        default: return .secondary
        }
    }
}

private func commandProviderLabel(_ provider: String) -> String {
    switch provider.lowercased() {
    case "codex": return "Codex"
    case "claude": return "Claude Code"
    case "antigravity": return "Antigravity"
    default: return provider.capitalized
    }
}

private func commandAccountLabel(_ account: Account) -> String {
    if account.account_id == "codex-1" || account.account_id == "codex-primary" {
        return "Codex · 1"
    }
    if account.account_id == "codex-2" || account.account_id == "codex-secondary" {
        return "Codex · 2"
    }
    return commandProviderLabel(account.provider)
}

private func commandWindowLabel(_ id: String) -> String {
    switch id {
    case "five_hour": return "5-hour"
    case "seven_day": return "7-day"
    case "primary": return "Session"
    case "secondary": return "Weekly"
    case "weekly": return "Weekly"
    case "monthly": return "Monthly"
    case "gemini_weekly": return "Gemini weekly"
    case "gemini_five_hour": return "Gemini 5-hour"
    case "third_party_weekly": return "Claude & GPT weekly"
    case "third_party_five_hour": return "Claude & GPT 5-hour"
    default:
        return id.replacingOccurrences(of: "_", with: " ").capitalized
    }
}

private func commandPressure(_ account: Account) -> Double {
    account.maxUsedPercent ?? .infinity
}

private func commandFocusAccount(_ accounts: [Account]) -> Account? {
    accounts
        .filter { $0.status == "live" && $0.maxUsedPercent != nil }
        .sorted { commandPressure($0) < commandPressure($1) }
        .first
}

private func commandSortedAccounts(_ accounts: [Account]) -> [Account] {
    let focusId = commandFocusAccount(accounts)?.account_id
    return accounts.sorted { lhs, rhs in
        if lhs.account_id == focusId && rhs.account_id != focusId { return true }
        if rhs.account_id == focusId && lhs.account_id != focusId { return false }

        let lhsRank = lhs.status == "live" ? 0 : 1
        let rhsRank = rhs.status == "live" ? 0 : 1
        if lhsRank != rhsRank { return lhsRank < rhsRank }

        let lhsPressure = commandPressure(lhs)
        let rhsPressure = commandPressure(rhs)
        if lhsPressure != rhsPressure { return lhsPressure < rhsPressure }
        return lhs.account_id < rhs.account_id
    }
}

struct CommandMenuBarLabel: View {
    @ObservedObject var monitor: UsageMonitor

    var body: some View {
        HStack(spacing: 4) {
            if let img = NSImage(named: "MenuIcon") {
                let _ = img.isTemplate = true
                Image(nsImage: img)
            } else {
                Image(systemName: "moon.fill")
            }

            if let peak = monitor.highestUsagePercent, !monitor.accounts.isEmpty {
                Text("\(Int(round(peak)))%")
                    .font(.system(size: 11, weight: .semibold, design: .rounded))
            }

            if monitor.needsAttention {
                Circle()
                    .fill(CommandPalette.warning)
                    .frame(width: 5, height: 5)
            }
        }
    }
}

struct CommandMenuContentView: View {
    @ObservedObject var monitor: UsageMonitor

    private var sortedAccounts: [Account] {
        commandSortedAccounts(monitor.accounts)
    }

    private var focusAccount: Account? {
        commandFocusAccount(monitor.accounts)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().opacity(0.65)

            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if let error = monitor.lastFetchError {
                        errorBanner(error)
                    }

                    decisionCard

                    if monitor.accounts.isEmpty && monitor.lastFetchError == nil {
                        loadingState
                    } else {
                        accountSection
                    }
                }
                .padding(14)
            }
            .frame(maxHeight: 560)

            Divider().opacity(0.65)
            footer
        }
        .frame(width: 388)
        .background(Color(NSColor.windowBackgroundColor))
        .onAppear {
            monitor.popoverVisible = true
            Task { await monitor.fetchUsage() }
        }
        .onDisappear {
            monitor.popoverVisible = false
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            RoundedRectangle(cornerRadius: 7)
                .fill(CommandPalette.accent)
                .frame(width: 27, height: 27)
                .overlay(
                    Text("TS")
                        .font(.system(size: 8.5, weight: .black))
                        .foregroundColor(Color(hex: 0x10160B))
                )

            VStack(alignment: .leading, spacing: 1) {
                Text("time-to-sleep")
                    .font(.system(size: 12.5, weight: .bold))
                Text("quota command center")
                    .font(.system(size: 9.5, weight: .medium))
                    .foregroundColor(.secondary)
            }

            Spacer()

            if let dashboardURL = monitor.dashboardURL {
                Button {
                    NSWorkspace.shared.open(dashboardURL)
                } label: {
                    Image(systemName: "arrow.up.right.square")
                        .font(.system(size: 12, weight: .semibold))
                }
                .buttonStyle(.plain)
                .foregroundColor(.secondary)
                .help("Open dashboard")
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
    }

    @ViewBuilder
    private var decisionCard: some View {
        if let focus = focusAccount, let pressure = focus.maxUsedPercent {
            let headroom = max(0, 100 - pressure)
            let accent = CommandPalette.provider(focus)

            HStack(alignment: .center, spacing: 14) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("USE NOW")
                        .font(.system(size: 8, weight: .black))
                        .tracking(1.1)
                        .foregroundColor(CommandPalette.accent)

                    Text(commandAccountLabel(focus))
                        .font(.system(size: 20, weight: .bold, design: .rounded))
                        .foregroundColor(.primary)

                    Text(focus.displayEmail ?? focus.account_id)
                        .font(.system(size: 10))
                        .foregroundColor(.secondary)
                        .lineLimit(1)

                    Text("Lowest usable pressure among live accounts")
                        .font(.system(size: 9.5, weight: .medium))
                        .foregroundColor(.secondary)
                }

                Spacer(minLength: 8)

                VStack(spacing: 1) {
                    Text("\(Int(round(headroom)))%")
                        .font(.system(size: 28, weight: .bold, design: .rounded))
                        .foregroundColor(accent)
                    Text("HEADROOM")
                        .font(.system(size: 7.5, weight: .black))
                        .tracking(0.7)
                        .foregroundColor(.secondary)
                    Text("\(Int(round(pressure)))% used")
                        .font(.system(size: 8.5, weight: .medium))
                        .foregroundColor(.secondary)
                }
                .frame(width: 82)
            }
            .padding(14)
            .background(
                RoundedRectangle(cornerRadius: 14)
                    .fill(Color(NSColor.controlBackgroundColor).opacity(0.52))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 14)
                    .stroke(CommandPalette.accent.opacity(0.30), lineWidth: 1)
            )
        } else {
            HStack(spacing: 10) {
                if monitor.accounts.isEmpty {
                    ProgressView().controlSize(.small)
                } else {
                    Image(systemName: "exclamationmark.circle")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(CommandPalette.warning)
                }

                VStack(alignment: .leading, spacing: 2) {
                    Text(monitor.accounts.isEmpty ? "Syncing accounts" : "No live account is ready")
                        .font(.system(size: 11.5, weight: .semibold))
                    Text(
                        monitor.accounts.isEmpty
                            ? "Reading provider quota windows before making a recommendation."
                            : "Cached and stale readings stay visible below, but Time-to-Sleep will not recommend one until a provider reports live quota data."
                    )
                        .font(.system(size: 9.5))
                        .foregroundColor(.secondary)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 14)
                    .fill(Color(NSColor.controlBackgroundColor).opacity(0.45))
            )
        }
    }

    private var accountSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("ACCOUNTS")
                    .font(.system(size: 8, weight: .black))
                    .tracking(1.0)
                    .foregroundColor(.secondary)
                Spacer()
                Text("\(monitor.accounts.count)")
                    .font(.system(size: 9, weight: .bold, design: .rounded))
                    .foregroundColor(.secondary)
            }
            .padding(.horizontal, 2)

            ForEach(sortedAccounts) { account in
                CommandAccountRow(
                    account: account,
                    isFocus: account.account_id == focusAccount?.account_id
                )
            }
        }
    }

    private var loadingState: some View {
        HStack(spacing: 8) {
            ProgressView().controlSize(.small)
            Text("Reading local provider usage…")
                .font(.system(size: 10))
                .foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .center)
        .padding(.vertical, 24)
    }

    private func errorBanner(_ message: String) -> some View {
        HStack(alignment: .top, spacing: 7) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 10))
                .foregroundColor(CommandPalette.warning)
            Text(message)
                .font(.system(size: 9.5))
                .foregroundColor(.secondary)
                .lineLimit(3)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CommandPalette.warning.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private var footer: some View {
        HStack(spacing: 10) {
            Button {
                Task { await monitor.fetchUsage(forceRefresh: true) }
            } label: {
                if monitor.isRefreshing {
                    ProgressView().controlSize(.mini)
                } else {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
            }
            .controlSize(.small)
            .disabled(monitor.isRefreshing)
            .keyboardShortcut("r", modifiers: .command)

            Button {
                PreferencesWindowManager.shared.show(monitor: monitor)
            } label: {
                Label("Preferences", systemImage: "gearshape")
            }
            .controlSize(.small)
            .keyboardShortcut(",", modifiers: .command)

            Spacer()

            Button {
                BackendRunner.shared.stop()
                NSApplication.shared.terminate(nil)
            } label: {
                Image(systemName: "power")
            }
            .controlSize(.small)
            .help("Quit Time-to-Sleep")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
    }
}

private struct CommandAccountRow: View {
    let account: Account
    let isFocus: Bool

    private var accent: Color {
        CommandPalette.provider(account)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 9) {
                RoundedRectangle(cornerRadius: 6)
                    .fill(accent.opacity(0.16))
                    .frame(width: 29, height: 29)
                    .overlay(
                        Text(String(commandProviderLabel(account.provider).prefix(2)).uppercased())
                            .font(.system(size: 8, weight: .black))
                            .foregroundColor(accent)
                    )

                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 5) {
                        Text(commandAccountLabel(account))
                            .font(.system(size: 11.5, weight: .bold))
                        if isFocus {
                            Text("BEST")
                                .font(.system(size: 6.5, weight: .black))
                                .tracking(0.5)
                                .foregroundColor(CommandPalette.accent)
                                .padding(.horizontal, 5)
                                .padding(.vertical, 2)
                                .background(CommandPalette.accent.opacity(0.10))
                                .clipShape(Capsule())
                        }
                    }
                    Text(account.displayEmail ?? account.account_id)
                        .font(.system(size: 9))
                        .foregroundColor(.secondary)
                        .lineLimit(1)
                }

                Spacer()

                CommandStatusPill(status: account.status)
            }

            if let windows = account.windows, !windows.isEmpty {
                VStack(spacing: 7) {
                    ForEach(windows) { window in
                        CommandWindowRow(window: window, accent: accent)
                    }
                }
            }

            if let message = account.message, !message.isEmpty {
                Text(message)
                    .font(.system(size: 8.5))
                    .foregroundColor(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(11)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color(NSColor.controlBackgroundColor).opacity(isFocus ? 0.64 : 0.42))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(isFocus ? CommandPalette.accent.opacity(0.26) : Color.secondary.opacity(0.11), lineWidth: 1)
        )
    }
}

private struct CommandStatusPill: View {
    let status: String

    var body: some View {
        let color = CommandPalette.status(status)
        HStack(spacing: 4) {
            Circle()
                .fill(color)
                .frame(width: 5, height: 5)
            Text(status.replacingOccurrences(of: "_", with: " ").uppercased())
                .font(.system(size: 6.5, weight: .black))
                .tracking(0.35)
                .foregroundColor(color)
        }
        .padding(.horizontal, 6)
        .padding(.vertical, 3)
        .background(color.opacity(0.08))
        .clipShape(Capsule())
    }
}

private struct CommandWindowRow: View {
    let window: UsageWindow
    let accent: Color

    var body: some View {
        VStack(spacing: 5) {
            HStack {
                Text(commandWindowLabel(window.id))
                    .font(.system(size: 8.5, weight: .semibold))
                    .foregroundColor(.secondary)
                Spacer()
                Text("\(Int(round(window.used_percent)))%")
                    .font(.system(size: 10, weight: .bold, design: .rounded))
                    .foregroundColor(.primary)
                Text("used")
                    .font(.system(size: 7.5))
                    .foregroundColor(.secondary)
            }

            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(Color.secondary.opacity(0.12))
                    Capsule()
                        .fill(CommandPalette.usage(window.used_percent))
                        .frame(
                            width: max(
                                3,
                                geometry.size.width * CGFloat(max(0, min(100, window.used_percent)) / 100)
                            )
                        )
                }
            }
            .frame(height: 4)
        }
    }
}
