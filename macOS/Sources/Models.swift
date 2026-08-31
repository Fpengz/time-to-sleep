import Foundation

struct UsageResponse: Codable {
    let accounts: [Account]
    let generated_at: String?
}

struct Account: Codable, Identifiable {
    var id: String { account_id }
    
    let account_id: String
    let provider: String
    let configured_email: String?
    let observed_email: String?
    let status: String
    let windows: [UsageWindow]?
    let plan_type: String?
    let message: String?
    
    var displayEmail: String? {
        if let obs = observed_email, !obs.isEmpty {
            return obs
        }
        return configured_email
    }
    
    var maxUsedPercent: Double? {
        guard let windows = windows, !windows.isEmpty else { return nil }
        return windows.map { $0.used_percent }.max()
    }
}

struct UsageWindow: Codable, Identifiable {
    let id: String
    let used_percent: Double
    let resets_at: String?
    let window_minutes: Int?
}

struct AutoRetrievalConfig: Codable {
    var enabled: Bool = true
    var poll_interval_secs: Int = 60
    var codex_ttl_secs: Int = 180
    var claude_ttl_secs: Int = 300
    var antigravity_ttl_secs: Int = 90

    func ttl(for provider: String) -> Int {
        switch provider.lowercased() {
        case "codex": return codex_ttl_secs
        case "claude": return claude_ttl_secs
        case "antigravity": return antigravity_ttl_secs
        default: return 180
        }
    }
}

struct SettingsModel: Codable {
    var accounts: [AccountConfigModel]
    var auto_retrieval: AutoRetrievalConfig
}

struct AccountConfigModel: Codable, Identifiable {
    var id: String
    var provider: String
    var email: String
    var home: String
    var priority: Int?
    var warning_threshold: Double?
    var auto_retrieval: Bool?
}

struct HistoryPointModel: Codable, Identifiable {
    var id: String { "\(account_id)-\(observed_at)" }
    let account_id: String
    let provider: String
    let window_id: String
    let used_percent: Double
    let observed_at: String
}

struct ApiErrorResponse: Codable {
    let detail: String
}
