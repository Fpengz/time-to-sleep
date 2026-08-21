import Foundation
import Combine

@MainActor
class UsageMonitor: ObservableObject {
    @Published var accounts: [Account] = []
    @Published var needsAttention: Bool = false
    @Published var lastFetchError: String? = nil
    
    private var timer: Timer?
    
    init() {
        Task { await fetchUsage() }
        timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in
            Task { @MainActor in
                await self.fetchUsage()
            }
        }
    }
    
    private func getPort() -> Int {
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
    
    func fetchUsage() async {
        let port = getPort()
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/usage") else { return }
        
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let decoder = JSONDecoder()
            let response = try decoder.decode(UsageResponse.self, from: data)
            self.accounts = response.accounts
            
            // Check if any account has a status that requires attention
            self.needsAttention = response.accounts.contains { 
                $0.status != "live" 
            }
            self.lastFetchError = nil
        } catch {
            self.lastFetchError = error.localizedDescription
            self.needsAttention = true
        }
    }
}
