import SwiftUI
import AppKit

struct PreferencesView: View {
    @ObservedObject var monitor: UsageMonitor
    @State private var accounts: [AccountConfigModel] = []
    @State private var discovered: [AccountConfigModel] = []
    @State private var isShowingAddSheet = false
    @State private var isScanning = false
    @State private var isSaving = false
    @State private var errorMessage: String? = nil
    
    // Form fields
    @State private var editingAccount: AccountConfigModel? = nil
    @State private var accId = ""
    @State private var accProvider = "codex"
    @State private var accEmail = ""
    @State private var accHome = ""
    @State private var accWarning: Double = 80
    @State private var accCritical: Double = 95

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
                    Text("Manage accounts and alert thresholds")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
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
                .padding(.top, 10)
            }
            
            // Accounts list
            List {
                ForEach(accounts) { acc in
                    let color = Palette.provider(acc.provider, id: acc.id)
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
                                thresholdPill("CRIT \(Int(acc.critical_threshold ?? 95))%", color: Palette.danger)
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
        .frame(width: 520, height: 420)
        .task {
            await loadAccounts()
        }
        .sheet(isPresented: $isShowingAddSheet) {
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
                
                HStack(spacing: 16) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Warning Threshold: \(Int(accWarning))%").font(.caption).fontWeight(.semibold)
                        Slider(value: $accWarning, in: 10...100, step: 5)
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Critical Threshold: \(Int(accCritical))%").font(.caption).fontWeight(.semibold)
                        Slider(value: $accCritical, in: 10...100, step: 5)
                    }
                }
                
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

    private func loadAccounts() async {
        let port = monitor.getPort()
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/accounts") else { return }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            struct ViewItem: Codable {
                let account_id: String
                let provider: String
                let configured_email: String
                let configured_home: String
            }
            let list = try JSONDecoder().decode([ViewItem].self, from: data)
            self.accounts = list.map {
                AccountConfigModel(
                    id: $0.account_id,
                    provider: $0.provider,
                    email: $0.configured_email,
                    home: $0.configured_home,
                    warning_threshold: 80,
                    critical_threshold: 95
                )
            }
        } catch {
            self.errorMessage = "Failed to load accounts: \(error.localizedDescription)"
        }
    }
    
    private func discoverAccounts() async {
        isScanning = true
        defer { isScanning = false }
        let port = monitor.getPort()
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/accounts/discover") else { return }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            self.discovered = try JSONDecoder().decode([AccountConfigModel].self, from: data)
            if self.discovered.isEmpty {
                self.errorMessage = "No new AI assistant configurations found on disk."
            }
        } catch {
            self.errorMessage = "Discovery failed: \(error.localizedDescription)"
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
            let _ = try await URLSession.shared.data(for: request)
            await loadAccounts()
            await monitor.fetchUsage(forceRefresh: true)
            if let id = specificId {
                self.discovered.removeAll { $0.id == id }
            } else {
                self.discovered.removeAll()
            }
        } catch {
            self.errorMessage = "Failed to import account: \(error.localizedDescription)"
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
            warning_threshold: accWarning,
            critical_threshold: accCritical
        )
        request.httpBody = try? JSONEncoder().encode(model)
        
        do {
            let _ = try await URLSession.shared.data(for: request)
            isShowingAddSheet = false
            await loadAccounts()
            await monitor.fetchUsage(forceRefresh: true)
        } catch {
            self.errorMessage = "Failed to save account: \(error.localizedDescription)"
        }
    }
    
    private func deleteAccount(_ accountId: String) async {
        let port = monitor.getPort()
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/accounts/config/\(accountId)") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        do {
            let _ = try await URLSession.shared.data(for: request)
            await loadAccounts()
            await monitor.fetchUsage(forceRefresh: true)
        } catch {
            self.errorMessage = "Failed to delete account: \(error.localizedDescription)"
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
        isShowingAddSheet = true
    }
    
    private func openEditAccountSheet(_ account: AccountConfigModel) {
        editingAccount = account
        accId = account.id
        accProvider = account.provider
        accEmail = account.email
        accHome = account.home
        accWarning = account.warning_threshold ?? 80
        accCritical = account.critical_threshold ?? 95
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
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 420),
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
