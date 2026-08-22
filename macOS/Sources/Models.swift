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
    let status: String
    let windows: [UsageWindow]?
    let plan_type: String?
    let message: String?
    
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

struct AccountConfigModel: Codable, Identifiable {
    var id: String
    var provider: String
    var email: String
    var home: String
    var warning_threshold: Double?
    var critical_threshold: Double?
}

struct HistoryPointModel: Codable, Identifiable {
    var id: String { "\(account_id)-\(observed_at)" }
    let account_id: String
    let provider: String
    let window_id: String
    let used_percent: Double
    let observed_at: String
}
