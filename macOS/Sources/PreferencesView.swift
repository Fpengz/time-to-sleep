import SwiftUI
import AppKit

enum PrefsTab: String, CaseIterable, Identifiable {
    case accounts = "Accounts"
    case autoRetrieval = "Auto-Retrieval"
    
    var id: String { rawValue }
    
    var icon: String {
        switch self {
        case .accounts: return "person.2.badge.gearshape"
        case .autoRetrieval: return "arrow.clockwise.circle"
        }
    }
}

struct PreferencesView: View {
    @ObservedObject var monitor: UsageMonitor
    @State private var selectedTab: PrefsTab = .accounts
    @State private var accounts: [AccountConfigModel] = []
    @State private var autoRetrieval: AutoRetrievalConfig = AutoRetrievalConfig()
    @State private var discovered: [AccountConfigModel] = []
    @State private var isShowingAddSheet = false
    @State private var isScanning = false
    @State private var isSaving = false
    @State private var isSavingRetrieval = false
    @State private var errorMessage: String? = nil
    @State private var successMessage: String? = nil
    
    // Account Form fields
    @State private var editingAccount: AccountConfigModel? = nil
    @State private var accId = ""
    @State private var accProvider = "codex"
    @State private var accEmail = ""
    @State private var accHome = ""
    @State private var accWarning: Double = 80
    @State private var accCritical: Double = 95
    @State private var accAutoRetrieval: Bool = true
    
    // Auto-retrieval form fields
    @State private var autoRetrievalEnabled: Bool = true
    @State private var pollIntervalSecs: Int = 60
    @State private var codexTtlSecs: Int = 180
    @State private var claudeTtlSecs: Int = 300
    @State private var antigravityTtlSecs: Int = 90

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack(spacing: 11) {
                RoundedRectangle(cornerRadius: 8)
                    .fill(LinearGradient(colors: [Palette.accent, Palette.accent.opacity(0.7)],
                                         startPoint: .topLeading, endPoint: .bottomTrailing))
                    .frame(width: 30, height: 30)
                    .overlay(
                        Image(systemName: "gearshape.fill")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundColor(Color(NSColor.windowBackgroundColor))
                    )
                VStack(alignment: .leading, spacing: 2) {
                    Text("Preferences")
                        .font(.title3)
                        .fontWeight(.semibold)
                    Text("Manage accounts, refresh rates, and alert thresholds")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                Spacer()
                
                Picker("", selection: $selectedTab) {
                    ForEach(PrefsTab.allCases) { tab in
                        Label(tab.rawValue, systemImage: tab.icon).tag(tab)
                    }
                }
                .pickerStyle(.segmented)
                .frame(width: 220)
            }
            .padding(16)

            Divider()
            
            if let error = errorMessage {
                HStack {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundColor(.red)
                    Text(error)
                        .font(.caption)
                    Spacer()
                    Button("Dismiss") { errorMessage = nil }
                        .font(.caption)
                }
                .padding(8)
                .background(Color.red.opacity(0.1))
            }
            
            if let success = successMessage {
                HStack {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(.green)
                    Text(success)
                        .font(.caption)
                    Spacer()
                    Button("Dismiss") { successMessage = nil }
                        .font(.caption)
                }
                .padding(8)
                .background(Color.green.opacity(0.1))
            }
            
            // Tab Content
            switch selectedTab {
            case .accounts:
                accountsTabView
            case .autoRetrieval:
                autoRetrievalTabView
            }
        }
        .frame(width: 540, height: 460)
        .task {
            await loadSettings()
        }
        .sheet(isPresented: $isShowingAddSheet) {
            accountEditSheet
        }
    }
    
    // MARK: - Accounts Tab View
    private var accountsTabView: some View {
        VStack(spacing: 0) {
            // Action bar
            HStack {
                Text("\(accounts.count) Configured Account(s)")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Spacer()
                Button {
                    Task { await discoverAccounts() }
                } label: {
                    HStack(spacing: 4) {
                        if isScanning {
                            ProgressView().controlSize(.mini)
                        } else {
                            Image(systemName: "magnifyingglass")
                        }
                        Text("Auto-Discover")
                    }
                }
                .disabled(isScanning)
                
                Button {
                    openNewAccountSheet()
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "plus")
                        Text("Add Account")
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(Palette.accent)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(Color(NSColor.controlBackgroundColor).opacity(0.5))
            
            // Discovered banner
            if !discovered.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("Discovered \(discovered.count) Account(s) on Disk:")
                            .font(.caption)
                            .fontWeight(.semibold)
                        Spacer()
                        Button("Import All") {
                            Task { await applyDiscovered(nil) }
                        }
                        .controlSize(.mini)
                    }
                    ForEach(discovered) { disc in
                        HStack {
                            Text("\(disc.provider.capitalized) (\(disc.id)): \(disc.email)")
                                .font(.caption2)
                            Spacer()
                            Button("Import") {
                                Task { await applyDiscovered(disc.id) }
                            }
                            .controlSize(.mini)
                        }
                    }
                }
                .padding(10)
                .background(Color.accentColor.opacity(0.1))
                .cornerRadius(6)
                .padding(.horizontal, 16)
                .padding(.top, 8)
            }
            
            // Accounts list
            List {
                ForEach(accounts) { acc in
                    let color = Palette.provider(acc.provider, id: acc.id)
                    let isAutoEnabled = acc.auto_retrieval ?? true
                    HStack(alignment: .center, spacing: 12) {
                        Text(String(acc.provider.prefix(2)).uppercased())
                            .font(.system(size: 11, weight: .heavy))
                            .foregroundColor(color)
                            .frame(width: 32, height: 32)
                            .background(RoundedRectangle(cornerRadius: 9).fill(color.opacity(0.14)))
                            .overlay(RoundedRectangle(cornerRadius: 9).stroke(color.opacity(0.35), lineWidth: 1))

                        VStack(alignment: .leading, spacing: 3) {
                            HStack(spacing: 6) {
                                Text(acc.id)
                                    .fontWeight(.semibold)
                                Text(acc.provider.capitalized)
                                    .font(.system(size: 9, weight: .bold))
                                    .foregroundColor(color)
                                    .padding(.horizontal, 5)
                                    .padding(.vertical, 1.5)
                                    .background(color.opacity(0.14))
                                    .clipShape(Capsule())
                            }
                            Text(acc.email)
                                .font(.caption)
                                .foregroundColor(.secondary)
                            Text(acc.home)
                                .font(.caption2)
                                .foregroundColor(.secondary)
                            HStack(spacing: 6) {
                                thresholdPill("WARN \(Int(acc.warning_threshold ?? 80))%", color: Palette.warn)
                                thresholdPill(isAutoEnabled ? "AUTO-SYNC: ON" : "AUTO-SYNC: OFF", color: isAutoEnabled ? .green : .secondary)
                            }
                            .padding(.top, 1)
                        }

                        Spacer()

                        Button("Edit") {
                            openEditAccountSheet(acc)
                        }
                        .controlSize(.small)

                        Button(role: .destructive) {
                            Task { await deleteAccount(acc.id) }
                        } label: {
                            Image(systemName: "trash")
                        }
                        .controlSize(.small)
                    }
                    .padding(.vertical, 5)
                }
            }
            .listStyle(.inset)
        }
    }
    
    // MARK: - Auto-Retrieval Tab View
    private var autoRetrievalTabView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                // Master Toggle
                VStack(alignment: .leading, spacing: 6) {
                    Toggle("Enable Background Auto-Retrieval", isOn: $autoRetrievalEnabled)
                        .font(.headline)
                    Text("Automatically query assistant quotas and rate limits in the background at regular intervals.")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                .padding(14)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(NSColor.controlBackgroundColor)))

                // Polling Interval
                VStack(alignment: .leading, spacing: 8) {
                    Text("Background Poll Interval")
                        .font(.headline)
                    Text("How frequently Time-to-Sleep checks and refreshes local metrics.")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    
                    Picker("Poll Interval", selection: $pollIntervalSecs) {
                        Text("30 seconds (Aggressive)").tag(30)
                        Text("1 minute (Default)").tag(60)
                        Text("2 minutes").tag(120)
                        Text("5 minutes (Recommended for Claude)").tag(300)
                        Text("10 minutes").tag(600)
                        Text("15 minutes").tag(900)
                        Text("30 minutes").tag(1800)
                    }
                    .pickerStyle(.menu)
                    .disabled(!autoRetrievalEnabled)
                }
                .padding(14)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(NSColor.controlBackgroundColor)))

                // Provider Cache TTLs
                VStack(alignment: .leading, spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Provider Cache Lifetimes (TTLs)")
                            .font(.headline)
                        Text("Minimum duration cached data is reused before making new network or process queries. Protects against upstream rate limits (such as Claude HTTP 429).")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text("Codex Cache TTL:")
                                .font(.subheadline)
                                .frame(width: 140, alignment: .leading)
                            TextField("180", value: $codexTtlSecs, format: .number)
                                .textFieldStyle(.roundedBorder)
                                .frame(width: 80)
                            Text("seconds")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                        
                        HStack {
                            Text("Claude Cache TTL:")
                                .font(.subheadline)
                                .frame(width: 140, alignment: .leading)
                            TextField("300", value: $claudeTtlSecs, format: .number)
                                .textFieldStyle(.roundedBorder)
                                .frame(width: 80)
                            Text("seconds (Anthropic API)")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                        
                        HStack {
                            Text("Antigravity Cache TTL:")
                                .font(.subheadline)
                                .frame(width: 140, alignment: .leading)
                            TextField("90", value: $antigravityTtlSecs, format: .number)
                                .textFieldStyle(.roundedBorder)
                                .frame(width: 80)
                            Text("seconds (Language Server)")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                    }
                }
                .padding(14)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(NSColor.controlBackgroundColor)))

                // Save button
                HStack {
                    Spacer()
                    Button {
                        Task { await saveRetrievalSettings() }
                    } label: {
                        HStack(spacing: 4) {
                            if isSavingRetrieval {
                                ProgressView().controlSize(.mini)
                            }
                            Text("Save Retrieval Preferences")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Palette.accent)
                    .disabled(isSavingRetrieval)
                }
            }
            .padding(16)
        }
    }
    
    // MARK: - Account Edit Sheet
    private var accountEditSheet: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(editingAccount == nil ? "Add Account" : "Edit Account")
                .font(.headline)
            
            VStack(alignment: .leading, spacing: 4) {
                Text("Account ID").font(.caption).fontWeight(.semibold)
                TextField("e.g. codex-primary", text: $accId)
                    .textFieldStyle(.roundedBorder)
                    .disabled(editingAccount != nil)
            }
            
            VStack(alignment: .leading, spacing: 4) {
                Text("Provider").font(.caption).fontWeight(.semibold)
                Picker("", selection: $accProvider) {
                    Text("Codex").tag("codex")
                    Text("Claude Code").tag("claude")
                    Text("Antigravity").tag("antigravity")
                }
                .labelsHidden()
            }
            
            VStack(alignment: .leading, spacing: 4) {
                Text("Email").font(.caption).fontWeight(.semibold)
                TextField("developer@example.com", text: $accEmail)
                    .textFieldStyle(.roundedBorder)
            }
            
            VStack(alignment: .leading, spacing: 4) {
                Text("Home Directory").font(.caption).fontWeight(.semibold)
                TextField("~/.codex", text: $accHome)
                    .textFieldStyle(.roundedBorder)
            }
            
            VStack(alignment: .leading, spacing: 4) {
                Text("Warning Threshold: \(Int(accWarning))%").font(.caption).fontWeight(.semibold)
                Slider(value: $accWarning, in: 10...100, step: 5)
            }
            
            Toggle("Auto-Retrieve Usage in Background", isOn: $accAutoRetrieval)
                .font(.subheadline)
            
            HStack {
                Spacer()
                Button("Cancel") {
                    isShowingAddSheet = false
                }
                Button(editingAccount == nil ? "Add Account" : "Save Changes") {
                    Task { await saveAccount() }
                }
                .buttonStyle(.borderedProminent)
                .disabled(accId.trimmingCharacters(in: .whitespaces).isEmpty || accEmail.isEmpty)
            }
            .padding(.top, 8)
        }
        .padding(20)
        .frame(width: 400)
    }
    
    private func thresholdPill(_ text: String, color: Color) -> some View {
        Text(text)
            .font(.system(size: 9, weight: .bold))
            .foregroundColor(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 1.5)
            .background(color.opacity(0.12))
            .clipShape(Capsule())
    }

    // MARK: - API Calls
    private func loadSettings() async {
        let port = monitor.getPort()
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/settings") else { return }
        do {
            let (data, resp) = try await URLSession.shared.data(from: url)
            guard let http = resp as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
                let status = (resp as? HTTPURLResponse)?.statusCode ?? -1
                self.errorMessage = "Failed to load settings (HTTP \(status))"
                return
            }
            let settings = try JSONDecoder().decode(SettingsModel.self, from: data)
            self.accounts = settings.accounts
            self.autoRetrieval = settings.auto_retrieval
            self.autoRetrievalEnabled = settings.auto_retrieval.enabled
            self.pollIntervalSecs = settings.auto_retrieval.poll_interval_secs
            self.codexTtlSecs = settings.auto_retrieval.codex_ttl_secs
            self.claudeTtlSecs = settings.auto_retrieval.claude_ttl_secs
            self.antigravityTtlSecs = settings.auto_retrieval.antigravity_ttl_secs
        } catch {
            self.errorMessage = "Failed to load settings: \(error.localizedDescription)"
        }
    }
    
    private func saveRetrievalSettings() async {
        isSavingRetrieval = true
        defer { isSavingRetrieval = false }
        
        let newConfig = AutoRetrievalConfig(
            enabled: autoRetrievalEnabled,
            poll_interval_secs: max(10, pollIntervalSecs),
            codex_ttl_secs: max(10, codexTtlSecs),
            claude_ttl_secs: max(10, claudeTtlSecs),
            antigravity_ttl_secs: max(10, antigravityTtlSecs)
        )
        
        let settings = SettingsModel(
            accounts: self.accounts,
            auto_retrieval: newConfig
        )
        
        let port = monitor.getPort()
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/settings") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(settings)
        
        do {
            let (data, resp) = try await URLSession.shared.data(for: request)
            guard let http = resp as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
                let status = (resp as? HTTPURLResponse)?.statusCode ?? -1
                let detail = (try? JSONDecoder().decode(ApiErrorResponse.self, from: data))?.detail ?? "HTTP \(status)"
                self.errorMessage = "Failed to save auto-retrieval preferences: \(detail)"
                return
            }
            self.autoRetrieval = newConfig
            self.monitor.autoRetrieval = newConfig
            self.monitor.setupTimer(interval: newConfig.poll_interval_secs, enabled: newConfig.enabled)
            self.successMessage = "Auto-retrieval preferences saved successfully."
            Task {
                try? await Task.sleep(nanoseconds: 3_000_000_000)
                await MainActor.run { self.successMessage = nil }
            }
        } catch {
            self.errorMessage = "Failed to save auto-retrieval preferences: \(error.localizedDescription)"
        }
    }
    
    private func discoverAccounts() async {
        isScanning = true
        defer { isScanning = false }
        let port = monitor.getPort()
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/accounts/discover") else { return }
        do {
            let (data, resp) = try await URLSession.shared.data(from: url)
            guard let http = resp as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
                let status = (resp as? HTTPURLResponse)?.statusCode ?? -1
                let detail = (try? JSONDecoder().decode(ApiErrorResponse.self, from: data))?.detail ?? "HTTP \(status)"
                self.errorMessage = "Discovery failed: \(detail)"
                return
            }
            self.discovered = try JSONDecoder().decode([AccountConfigModel].self, from: data)
            if self.discovered.isEmpty {
                self.errorMessage = "No new AI assistant configurations found on disk."
            }
        } catch {
            self.errorMessage = "Discovery failed: \(error.localizedDescription)"
        }
    }
    
    private func executeApiRequest(_ request: URLRequest, actionDescription: String) async throws {
        let (data, resp) = try await URLSession.shared.data(for: request)
        guard let http = resp as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            let status = (resp as? HTTPURLResponse)?.statusCode ?? -1
            let detail = (try? JSONDecoder().decode(ApiErrorResponse.self, from: data))?.detail ?? "HTTP \(status)"
            throw NSError(domain: "TTSPreferences", code: status, userInfo: [NSLocalizedDescriptionKey: "\(actionDescription): \(detail)"])
        }
    }

    private func applyDiscovered(_ specificId: String?) async {
        let port = monitor.getPort()
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/accounts/discover/apply") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let bodyObj: [String: [String]] = specificId != nil ? ["account_ids": [specificId!]] : [:]
        request.httpBody = try? JSONEncoder().encode(bodyObj)
        
        do {
            try await executeApiRequest(request, actionDescription: "Failed to import account")
            await loadSettings()
            await monitor.fetchUsage(forceRefresh: true)
            if let id = specificId {
                self.discovered.removeAll { $0.id == id }
            } else {
                self.discovered.removeAll()
            }
        } catch {
            self.errorMessage = error.localizedDescription
        }
    }
    
    private func saveAccount() async {
        isSaving = true
        defer { isSaving = false }
        let port = monitor.getPort()
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/accounts/config") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let model = AccountConfigModel(
            id: accId.trimmingCharacters(in: .whitespaces),
            provider: accProvider,
            email: accEmail.trimmingCharacters(in: .whitespaces),
            home: accHome.trimmingCharacters(in: .whitespaces),
            priority: 0,
            warning_threshold: accWarning,
            auto_retrieval: accAutoRetrieval
        )
        request.httpBody = try? JSONEncoder().encode(model)
        
        do {
            try await executeApiRequest(request, actionDescription: "Failed to save account")
            isShowingAddSheet = false
            await loadSettings()
            await monitor.fetchUsage(forceRefresh: true)
        } catch {
            self.errorMessage = error.localizedDescription
        }
    }
    
    private func deleteAccount(_ accountId: String) async {
        let port = monitor.getPort()
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/accounts/config/\(accountId)") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        do {
            try await executeApiRequest(request, actionDescription: "Failed to delete account")
            await loadSettings()
            await monitor.fetchUsage(forceRefresh: true)
        } catch {
            self.errorMessage = error.localizedDescription
        }
    }
    
    private func openNewAccountSheet() {
        editingAccount = nil
        accId = ""
        accProvider = "codex"
        accEmail = ""
        accHome = ""
        accWarning = 80
        accCritical = 95
        accAutoRetrieval = true
        isShowingAddSheet = true
    }
    
    private func openEditAccountSheet(_ account: AccountConfigModel) {
        editingAccount = account
        accId = account.id
        accProvider = account.provider
        accEmail = account.email
        accHome = account.home
        accWarning = account.warning_threshold ?? 80
        accCritical = 95
        accAutoRetrieval = account.auto_retrieval ?? true
        isShowingAddSheet = true
    }
}

class PreferencesWindowManager {
    static let shared = PreferencesWindowManager()
    private var window: NSWindow?
    
    func show(monitor: UsageMonitor) {
        if let win = window {
            win.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        
        let contentView = PreferencesView(monitor: monitor)
        let hostingController = NSHostingController(rootView: contentView)
        
        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 540, height: 460),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        win.center()
        win.title = "Time-to-Sleep Preferences"
        win.contentViewController = hostingController
        win.isReleasedWhenClosed = false
        
        self.window = win
        win.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}
