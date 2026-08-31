import Foundation
import Combine
import UserNotifications

@MainActor
class UsageMonitor: ObservableObject {
    @Published var accounts: [Account] = []
    @Published var accountHistory: [String: [HistoryPointModel]] = [:]
    @Published var needsAttention: Bool = false
    @Published var autoRetrieval: AutoRetrievalConfig = AutoRetrievalConfig()
    @Published var lastFetchError: String? = nil
    @Published var isRefreshing: Bool = false
    /// Set by the menu bar popover on appear/disappear. The 24h history query is only
    /// needed while the popover's sparklines are on screen, so we skip fetching and
    /// decoding it on every background tick otherwise.
    var popoverVisible: Bool = false

    private struct AlertThresholds {
        let warning: Double
        let critical: Double
    }

    private var timer: Timer?
    private var previousUsageLevels: [String: Double] = [:]
    private var accountAlertThresholds: [String: AlertThresholds] = [:]
    private var hasInitializedLevels: Bool = false
    private var cachedPort: Int?
    
    var highestUsagePercent: Double? {
        accounts.compactMap { $0.maxUsedPercent }.max()
    }
    
    var dashboardURL: URL? {
        URL(string: "http://127.0.0.1:\(getPort())/")
    }
    
    var trendsURL: URL? {
        URL(string: "http://127.0.0.1:\(getPort())/#trends")
    }
    
    init() {
        requestNotificationPermission()
        Task {
            await fetchSettings()
            await fetchUsage()
        }
        setupTimer(interval: autoRetrieval.poll_interval_secs, enabled: autoRetrieval.enabled)
    }
    
    func setupTimer(interval: Int, enabled: Bool) {
        timer?.invalidate()
        timer = nil
        guard enabled, interval > 0 else { return }
        
        let t = Timer.scheduledTimer(withTimeInterval: TimeInterval(interval), repeats: true) { [weak self] _ in
            Task { @MainActor in
                await self?.fetchUsage()
            }
        }
        t.tolerance = Double(interval) * 0.1
        self.timer = t
    }
    
    func fetchSettings() async {
        let port = getPort()
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/settings") else { return }
        guard let (data, resp) = try? await URLSession.shared.data(from: url),
              let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let settings = try? Self.jsonDecoder.decode(SettingsModel.self, from: data) else {
            return
        }
        let intervalChanged = self.autoRetrieval.poll_interval_secs != settings.auto_retrieval.poll_interval_secs
        let enabledChanged = self.autoRetrieval.enabled != settings.auto_retrieval.enabled
        self.autoRetrieval = settings.auto_retrieval
        self.accountAlertThresholds = Dictionary(uniqueKeysWithValues: settings.accounts.map { account in
            (
                account.id,
                AlertThresholds(
                    warning: account.warning_threshold ?? 80.0,
                    critical: account.critical_threshold ?? 95.0
                )
            )
        })
        if intervalChanged || enabledChanged || timer == nil {
            self.setupTimer(interval: settings.auto_retrieval.poll_interval_secs, enabled: settings.auto_retrieval.enabled)
        }
    }
    
    func requestNotificationPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { granted, error in
            if let error = error {
                print("Notification permission error: \(error)")
            }
        }
    }
    
    func getPort() -> Int {
        if let port = cachedPort { return port }
        let envPath = (NSHomeDirectory() as NSString).appendingPathComponent("projects/time-to-sleep/.env")
        if let content = try? String(contentsOfFile: envPath, encoding: .utf8) {
            for line in content.split(separator: "\n") {
                let parts = line.split(separator: "=", maxSplits: 1)
                if parts.count == 2, parts[0].trimmingCharacters(in: .whitespaces) == "PORT" {
                    if let port = Int(parts[1].trimmingCharacters(in: .whitespacesAndNewlines)) {
                        cachedPort = port
                        return port
                    }
                }
            }
        }
        cachedPort = 4141
        return 4141
    }
    
    private static let jsonDecoder = JSONDecoder()

    func fetchUsage(forceRefresh: Bool = false) async {
        isRefreshing = true
        defer { isRefreshing = false }
        
        await fetchSettings()

        let port = getPort()
        let endpoint = forceRefresh ? "http://127.0.0.1:\(port)/v1/usage?force_refresh=true" : "http://127.0.0.1:\(port)/v1/usage"
        guard let url = URL(string: endpoint) else { return }
        
        do {
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
                throw URLError(.badServerResponse)
            }
            let usageResponse = try Self.jsonDecoder.decode(UsageResponse.self, from: data)

            checkThresholdsAndNotify(newAccounts: usageResponse.accounts)

            self.accounts = usageResponse.accounts
            self.needsAttention = usageResponse.accounts.contains {
                $0.status != "live"
            }
            self.lastFetchError = nil

            // /v1/usage persists the newest provider observation. Fetch history only after
            // that request completes so visible sparklines cannot lag by one refresh.
            if popoverVisible, let points = await fetchHistoryPoints(port: port) {
                var grouped: [String: [HistoryPointModel]] = [:]
                for p in points {
                    grouped[p.account_id, default: []].append(p)
                }
                self.accountHistory = grouped
            }
        } catch {
            self.lastFetchError = error.localizedDescription
            self.needsAttention = true
        }
    }
    
    private func fetchHistoryPoints(port: Int) async -> [HistoryPointModel]? {
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/history?hours=24") else { return nil }
        do {
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
                return nil
            }
            return try Self.jsonDecoder.decode([HistoryPointModel].self, from: data)
        } catch {
            return nil
        }
    }
    
    private func checkThresholdsAndNotify(newAccounts: [Account]) {
        for account in newAccounts {
            guard let windows = account.windows else { continue }
            let thresholds = accountAlertThresholds[account.account_id]
                ?? AlertThresholds(warning: 80.0, critical: 95.0)
            for window in windows {
                let key = "\(account.account_id):\(window.id)"
                let currentPct = window.used_percent
                let prevPct = previousUsageLevels[key]
                
                if let prev = prevPct, hasInitializedLevels {
                    if currentPct >= thresholds.critical && prev < thresholds.critical {
                        sendNotification(
                            title: "Time-to-Sleep: Critical Quota Warning",
                            body: "\(account.provider.capitalized) (\(account.configured_email ?? account.account_id)) is at \(Int(round(currentPct)))%."
                        )
                    } else if currentPct >= thresholds.warning && prev < thresholds.warning {
                        sendNotification(
                            title: "Time-to-Sleep: Quota Warning",
                            body: "\(account.provider.capitalized) (\(account.configured_email ?? account.account_id)) reached \(Int(round(currentPct)))%."
                        )
                    }
                    // Alert on quota reset (was >= 70% and dropped by >= 40%)
                    else if prev >= 70.0 && (prev - currentPct) >= 40.0 {
                        sendNotification(
                            title: "Time-to-Sleep: Quota Reset",
                            body: "\(account.provider.capitalized) quota has reset (now at \(Int(round(currentPct)))%)."
                        )
                    }
                }
                previousUsageLevels[key] = currentPct
            }
        }
        hasInitializedLevels = true
    }
    
    private func sendNotification(title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        
        let request = UNNotificationRequest(
            identifier: UUID().uuidString,
            content: content,
            trigger: nil
        )
        
        UNUserNotificationCenter.current().add(request) { error in
            if let error = error {
                print("Failed to dispatch notification: \(error)")
            }
        }
    }
}

