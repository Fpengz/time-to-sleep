import Foundation

struct UsageResponse: Codable {
    let accounts: [Account]
    let generated_at: String?
}

struct Account: Codable {
    let account_id: String
    let provider: String
    let configured_email: String?
    let status: String
    let windows: [UsageWindow]?
    let message: String?
}

struct UsageWindow: Codable {
    let id: String
    let used_percent: Double
    let resets_at: String?
    let window_minutes: Int?
}
