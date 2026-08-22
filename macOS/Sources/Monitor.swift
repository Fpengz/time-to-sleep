import Foundation
import Combine
import UserNotifications

@MainActor
class UsageMonitor: ObservableObject {
    @Published var accounts: [Account] = []
    @Published var accountHistory: [String: [HistoryPointModel]] = [:]
    @Published var needsAttention: Bool = false
    @Published var lastFetchError: String? = nil
    @Published var isRefreshing: Bool = false
    
    private var timer: Timer?
    private var previousUsageLevels: [String: Double] = [:]
    private var hasInitializedLevels: Bool = false
    
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
        Task { await fetchUsage() }
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in
            Task { @MainActor in
                await self.fetchUsage()
            }
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
        let envPath = (NSHomeDirectory() as NSString).appendingPathComponent("projects/time-to-sleep/.env")
        if let content = try? String(contentsOfFile: envPath, encoding: .utf8) {
            for line in content.split(separator: "\n") {
                let parts = line.split(separator: "=", maxSplits: 1)
                if parts.count == 2, parts[0].trimmingCharacters(in: .whitespaces) == "PORT" {
                    if let port = Int(parts[1].trimmingCharacters(in: .whitespacesAndNewlines)) {
                        return port
                    }
                }
            }
        }
        return 4141
    }
    
    func fetchUsage(forceRefresh: Bool = false) async {
        isRefreshing = true
        defer { isRefreshing = false }
        
        let port = getPort()
        let endpoint = forceRefresh ? "http://127.0.0.1:\(port)/v1/usage?force_refresh=true" : "http://127.0.0.1:\(port)/v1/usage"
        guard let url = URL(string: endpoint) else { return }
        
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let decoder = JSONDecoder()
            let response = try decoder.decode(UsageResponse.self, from: data)
            
            checkThresholdsAndNotify(newAccounts: response.accounts)
            
            self.accounts = response.accounts
            self.needsAttention = response.accounts.contains { 
                $0.status != "live" 
            }
            self.lastFetchError = nil
            
            // Also fetch 24h history for sparklines
            await fetchHistory()
        } catch {
            self.lastFetchError = error.localizedDescription
            self.needsAttention = true
        }
    }
    
    private func fetchHistory() async {
        let port = getPort()
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/history?hours=24") else { return }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let points = try JSONDecoder().decode([HistoryPointModel].self, from: data)
            var grouped: [String: [HistoryPointModel]] = [:]
            for p in points {
                grouped[p.account_id, default: []].append(p)
            }
            self.accountHistory = grouped
        } catch {
            // History fetch is non-fatal
        }
    }
    
    private func checkThresholdsAndNotify(newAccounts: [Account]) {
        for account in newAccounts {
            guard let windows = account.windows else { continue }
            for window in windows {
                let key = "\(account.account_id):\(window.id)"
                let currentPct = window.used_percent
                let prevPct = previousUsageLevels[key]
                
                if let prev = prevPct, hasInitializedLevels {
                    // Alert when crossing 95%
                    if currentPct >= 95.0 && prev < 95.0 {
                        sendNotification(
                            title: "Time-to-Sleep: Critical Quota Warning",
                            body: "\(account.provider.capitalized) (\(account.configured_email ?? account.account_id)) is at \(Int(round(currentPct)))%."
                        )
                    }
                    // Alert when crossing 80%
                    else if currentPct >= 80.0 && prev < 80.0 {
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

