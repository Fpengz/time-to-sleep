import SwiftUI
import AppKit

// MARK: - Design tokens

extension Color {
    init(hex: UInt, alpha: Double = 1) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: alpha
        )
    }
}

enum Palette {
    // Matches the web dashboard's --accent so the two surfaces read as one product.
    static let accent = Color(hex: 0x38BDF8)
    static let codex = Color(hex: 0x38AECB)
    static let codexSecondary = Color(hex: 0x7B78E0)
    static let claude = Color(hex: 0xE08A45)
    static let antigravity = Color(hex: 0x8FB02E)

    static let live = Color(hex: 0x53A867)
    static let warn = Color(hex: 0xD08A3C)
    static let danger = Color(hex: 0xD05A50)

    static func provider(_ provider: String, id: String) -> Color {
        switch provider {
        case "codex": return id.contains("secondary") ? codexSecondary : codex
        case "claude": return claude
        case "antigravity": return antigravity
        default: return accent
        }
    }

    static func status(_ status: String) -> Color {
        switch status {
        case "live": return live
        case "unavailable", "rate_limited": return danger
        case "cached", "stale": return warn
        default: return .secondary
        }
    }

    static func usage(_ percent: Double) -> Color {
        if percent >= 90 { return danger }
        if percent >= 75 { return warn }
        return live
    }
}

enum SharedFormatters {
    static let isoStandard = ISO8601DateFormatter()
    static let isoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    static let displayReset: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "EEE, MMM d, h:mm a"
        return f
    }()
}

// MARK: - Reusable components

struct RingGauge: View {
    let percent: Double
    var color: Color
    var size: CGFloat = 44
    var lineWidth: CGFloat = 5

    var body: some View {
        let value = max(0, min(100, percent)) / 100
        ZStack {
            Circle()
                .stroke(Color.secondary.opacity(0.18), lineWidth: lineWidth)
            Circle()
                .trim(from: 0, to: value)
                .stroke(color, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(.easeOut(duration: 0.5), value: value)
            VStack(spacing: -1) {
                Text("\(Int(round(percent)))")
                    .font(.system(size: size * 0.32, weight: .bold, design: .rounded))
                    .foregroundColor(.primary)
                Text("%")
                    .font(.system(size: size * 0.17, weight: .semibold))
                    .foregroundColor(.secondary)
            }
        }
        .frame(width: size, height: size)
    }
}

struct Meter: View {
    let value: Double
    let color: Color

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.secondary.opacity(0.16))
                Capsule()
                    .fill(
                        LinearGradient(
                            colors: [color.opacity(0.6), color],
                            startPoint: .leading, endPoint: .trailing
                        )
                    )
                    .frame(width: max(3, geo.size.width * CGFloat(max(0, min(100, value)) / 100)))
            }
        }
        .frame(height: 6)
    }
}

struct StatusPill: View {
    let status: String

    var body: some View {
        let color = Palette.status(status)
        HStack(spacing: 4) {
            Circle().fill(color).frame(width: 6, height: 6)
            Text(status.replacingOccurrences(of: "_", with: " ").capitalized)
                .font(.system(size: 10, weight: .bold))
                .textCase(.uppercase)
                .tracking(0.4)
                .foregroundColor(color)
        }
        .padding(.horizontal, 7)
        .padding(.vertical, 3)
        .background(Capsule().fill(color.opacity(0.14)))
        .overlay(Capsule().stroke(color.opacity(0.3), lineWidth: 1))
    }
}

// MARK: - Menu bar label

struct MenuBarLabel: View {
    @ObservedObject var monitor: UsageMonitor

    var body: some View {
        HStack(spacing: 4) {
            if let img = NSImage(named: "MenuIcon") {
                let _ = img.isTemplate = true
                Image(nsImage: img)
            } else {
                Image(systemName: "moon.stars.fill")
            }

            if let maxPct = monitor.highestUsagePercent, !monitor.accounts.isEmpty {
                Text("\(Int(round(maxPct)))%")
                    .font(.system(size: 11, weight: .semibold, design: .rounded))
            }

            if monitor.needsAttention {
                Image(systemName: "exclamationmark.circle.fill")
                    .foregroundColor(.orange)
            }
        }
    }
}

// MARK: - Menu content

struct MenuContentView: View {
    @ObservedObject var monitor: UsageMonitor

    private var liveCount: Int { monitor.accounts.filter { $0.status == "live" }.count }
    private var attentionCount: Int { monitor.accounts.filter { $0.status != "live" }.count }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().padding(.horizontal, 16)

            if let error = monitor.lastFetchError {
                errorBanner(error)
            }

            if !monitor.accounts.isEmpty {
                summaryStrip
            }

            ScrollView {
                VStack(spacing: 10) {
                    if monitor.accounts.isEmpty && monitor.lastFetchError == nil {
                        loadingState
                    } else {
                        ForEach(monitor.accounts, id: \.account_id) { account in
                            AccountView(
                                account: account,
                                history: monitor.accountHistory[account.account_id] ?? []
                            )
                        }
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
            }
            .frame(maxHeight: 520)

            Divider().padding(.horizontal, 16)
            footer
        }
        .frame(width: 372)
        .fixedSize(horizontal: true, vertical: true)
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
        HStack(alignment: .center, spacing: 10) {
            RoundedRectangle(cornerRadius: 8)
                .fill(LinearGradient(colors: [Palette.accent, Palette.accent.opacity(0.7)],
                                     startPoint: .topLeading, endPoint: .bottomTrailing))
                .frame(width: 28, height: 28)
                .overlay(
                    Image(systemName: "moon.stars.fill")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundColor(Color(NSColor.windowBackgroundColor))
                )

            VStack(alignment: .leading, spacing: 1) {
                Text("Time-to-Sleep")
                    .font(.system(size: 14, weight: .bold))
                Text("Usage observatory")
                    .font(.system(size: 10.5))
                    .foregroundColor(.secondary)
            }

            Spacer()

            HStack(spacing: 6) {
                if let dashboardURL = monitor.dashboardURL {
                    linkButton("Ledger", systemImage: "list.bullet.rectangle", url: dashboardURL)
                }
                if let trendsURL = monitor.trendsURL {
                    linkButton("Trends", systemImage: "chart.xyaxis.line", url: trendsURL)
                }
            }
        }
        .padding(16)
    }

    private func linkButton(_ title: String, systemImage: String, url: URL) -> some View {
        Button {
            NSWorkspace.shared.open(url)
        } label: {
            HStack(spacing: 3) {
                Image(systemName: systemImage)
                Text(title)
            }
            .font(.system(size: 11, weight: .semibold))
        }
        .buttonStyle(.borderless)
        .foregroundColor(Palette.accent)
    }

    private var summaryStrip: some View {
        HStack(spacing: 8) {
            summaryTile(label: "Peak load") {
                if let peak = monitor.highestUsagePercent {
                    AnyView(RingGauge(percent: peak, color: Palette.usage(peak), size: 40, lineWidth: 4.5))
                } else {
                    AnyView(Text("—").font(.system(size: 18, weight: .bold)))
                }
            }
            summaryTile(label: "Live") {
                AnyView(
                    Text("\(liveCount)/\(monitor.accounts.count)")
                        .font(.system(size: 20, weight: .bold, design: .rounded))
                        .foregroundColor(Palette.live)
                )
            }
            summaryTile(label: "Attention") {
                AnyView(
                    Text("\(attentionCount)")
                        .font(.system(size: 20, weight: .bold, design: .rounded))
                        .foregroundColor(attentionCount == 0 ? .secondary : Palette.warn)
                )
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 12)
    }

    private func summaryTile(label: String, content: () -> AnyView) -> some View {
        VStack(spacing: 6) {
            content()
                .frame(height: 40)
            Text(label.uppercased())
                .font(.system(size: 8.5, weight: .heavy))
                .tracking(0.6)
                .foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(NSColor.controlBackgroundColor).opacity(0.6))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.secondary.opacity(0.12), lineWidth: 1)
        )
    }

    private var loadingState: some View {
        HStack {
            ProgressView().controlSize(.small)
            Text("Fetching quota data…")
                .foregroundColor(.secondary)
                .font(.caption)
        }
        .frame(maxWidth: .infinity, alignment: .center)
        .padding(.vertical, 24)
    }

    private func errorBanner(_ error: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundColor(.orange)
            Text(error)
                .font(.caption2)
                .foregroundColor(.secondary)
                .lineLimit(2)
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.1))
        .cornerRadius(8)
        .padding(.horizontal, 16)
        .padding(.top, 12)
    }

    private var footer: some View {
        HStack {
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

            Button("Quit") {
                BackendRunner.shared.stop()
                NSApplication.shared.terminate(nil)
            }
            .controlSize(.small)
            .keyboardShortcut("q", modifiers: .command)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
    }
}

// MARK: - Account card

struct SparklineView: View {
    let points: [HistoryPointModel]
    var color: Color = Palette.accent

    var body: some View {
        if points.count >= 2 {
            GeometryReader { geo in
                let w = geo.size.width
                let h = geo.size.height
                let maxPct = max(100.0, points.map { $0.used_percent }.max() ?? 100.0)
                let pointAt: (Int) -> CGPoint = { index in
                    let x = (CGFloat(index) / CGFloat(points.count - 1)) * w
                    let normY = max(0, min(100, points[index].used_percent)) / maxPct
                    let y = h - (CGFloat(normY) * (h - 3)) - 2
                    return CGPoint(x: x, y: y)
                }

                ZStack {
                    Path { path in
                        path.move(to: CGPoint(x: 0, y: h))
                        for index in points.indices { path.addLine(to: pointAt(index)) }
                        path.addLine(to: CGPoint(x: w, y: h))
                        path.closeSubpath()
                    }
                    .fill(color.opacity(0.14))

                    Path { path in
                        for index in points.indices {
                            let pt = pointAt(index)
                            if index == 0 { path.move(to: pt) } else { path.addLine(to: pt) }
                        }
                    }
                    .stroke(color, style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
                }
            }
            .frame(height: 26)
        }
    }
}

struct AccountView: View {
    let account: Account
    var history: [HistoryPointModel] = []

    private var accentColor: Color {
        Palette.provider(account.provider, id: account.account_id)
    }

    private var peakPercent: Double? {
        account.windows?.map { $0.used_percent }.max()
    }

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            RoundedRectangle(cornerRadius: 2)
                .fill(account.status == "live" ? accentColor : Palette.status(account.status))
                .frame(width: 3)
                .padding(.vertical, 2)

            VStack(alignment: .leading, spacing: 9) {
                header
                if let windows = account.windows, !windows.isEmpty {
                    VStack(spacing: 8) {
                        ForEach(windows, id: \.id) { window in
                            windowRow(window)
                        }
                    }
                }
                if !history.isEmpty {
                    SparklineView(points: history, color: accentColor)
                }
                if let message = account.message {
                    Text(message)
                        .font(.caption2)
                        .foregroundColor(.secondary)
                        .lineLimit(2)
                        .padding(.top, 1)
                }
            }
            .padding(12)
        }
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color(NSColor.controlBackgroundColor).opacity(0.55))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color.secondary.opacity(0.12), lineWidth: 1)
        )
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 10) {
            Text(monogram)
                .font(.system(size: 11, weight: .heavy))
                .foregroundColor(accentColor)
                .frame(width: 30, height: 30)
                .background(RoundedRectangle(cornerRadius: 9).fill(accentColor.opacity(0.14)))
                .overlay(RoundedRectangle(cornerRadius: 9).stroke(accentColor.opacity(0.35), lineWidth: 1))

            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 5) {
                    Text(accountDisplayName)
                        .font(.system(size: 13, weight: .semibold))
                    if let plan = account.plan_type, !plan.isEmpty {
                        Text(plan.uppercased())
                            .font(.system(size: 8.5, weight: .bold))
                            .padding(.horizontal, 5).padding(.vertical, 1.5)
                            .background(Color.secondary.opacity(0.14))
                            .clipShape(Capsule())
                            .foregroundColor(.secondary)
                    }
                }
                if let email = account.configured_email {
                    Text(email)
                        .font(.system(size: 10.5))
                        .foregroundColor(.secondary)
                        .lineLimit(1)
                }
            }

            Spacer(minLength: 6)

            if let peak = peakPercent {
                RingGauge(percent: peak, color: Palette.usage(peak), size: 34, lineWidth: 4)
            } else {
                StatusPill(status: account.status)
            }
        }
    }

    private func windowRow(_ window: UsageWindow) -> some View {
        // Provider hue while healthy; escalate to warn/danger as usage climbs — mirrors the web meters.
        let meterColor = window.used_percent >= 75 ? Palette.usage(window.used_percent) : accentColor
        let color = Palette.usage(window.used_percent)
        return VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(formatWindowId(window.id))
                    .font(.system(size: 10.5, weight: .medium))
                    .foregroundColor(.secondary)
                if let badge = windowBadge(window) {
                    Text(badge)
                        .font(.system(size: 8, weight: .bold))
                        .padding(.horizontal, 4).padding(.vertical, 1)
                        .background(Color.secondary.opacity(0.12))
                        .clipShape(Capsule())
                        .foregroundColor(.secondary)
                }
                Spacer()
                Text(String(format: "%.0f%%", window.used_percent))
                    .font(.system(size: 12, weight: .bold, design: .rounded))
                    .foregroundColor(color)
            }
            Meter(value: window.used_percent, color: meterColor)
            if let resetsText = formatResetsAt(window.resets_at) {
                HStack(spacing: 5) {
                    Text(resetsText)
                        .font(.system(size: 9))
                        .foregroundColor(.secondary)
                    if let countdown = resetCountdown(window.resets_at) {
                        Text(countdown)
                            .font(.system(size: 8.5, weight: .semibold))
                            .padding(.horizontal, 5).padding(.vertical, 1)
                            .background(accentColor.opacity(0.14))
                            .clipShape(Capsule())
                            .foregroundColor(accentColor)
                    }
                }
            }
        }
    }

    // MARK: helpers

    private var monogram: String {
        String(account.provider.prefix(2)).uppercased()
    }

    private var accountDisplayName: String {
        if account.account_id == "codex-primary" { return "Codex · Primary" }
        if account.account_id == "codex-secondary" { return "Codex · Second" }
        switch account.provider {
        case "claude": return "Claude Code"
        case "antigravity": return "Antigravity"
        default: return account.provider.capitalized
        }
    }

    private func windowBadge(_ window: UsageWindow) -> String? {
        guard let minutes = window.window_minutes else { return nil }
        return minutes >= 1000 ? "7-DAY" : "5-HOUR"
    }

    private func formatWindowId(_ id: String) -> String {
        let labels = ["third_party_weekly": "Claude + GPT Weekly",
                      "third_party_five_hour": "Claude + GPT 5-Hour"]
        if let mapped = labels[id] { return mapped }
        return id.split(separator: "_").map { $0.capitalized }.joined(separator: " ")
    }

    private func parseDate(_ dateString: String?) -> Date? {
        guard let dateString = dateString else { return nil }
        if let date = SharedFormatters.isoStandard.date(from: dateString) { return date }
        return SharedFormatters.isoFractional.date(from: dateString)
    }

    private func formatResetsAt(_ dateString: String?) -> String? {
        guard let date = parseDate(dateString) else { return nil }
        return "Resets \(SharedFormatters.displayReset.string(from: date))"
    }

    private func resetCountdown(_ dateString: String?) -> String? {
        guard let date = parseDate(dateString) else { return nil }
        let diff = date.timeIntervalSinceNow
        if diff <= 0 { return "overdue" }
        let minutes = Int(diff / 60)
        if minutes < 60 { return "in \(minutes)m" }
        let hours = minutes / 60
        if hours < 24 { return minutes % 60 > 0 ? "in \(hours)h \(minutes % 60)m" : "in \(hours)h" }
        let days = hours / 24
        return hours % 24 > 0 ? "in \(days)d \(hours % 24)h" : "in \(days)d"
    }
}
