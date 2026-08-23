import Foundation

class BackendRunner {
    static let shared = BackendRunner()
    private var process: Process?

    private init() {}

    func start() {
        guard process == nil else { return }
        
        let projectPath = (NSHomeDirectory() as NSString).appendingPathComponent("projects/time-to-sleep")
        let releaseBinary = "\(projectPath)/target/release/time-to-sleep"
        let bundleBinary = Bundle.main.resourceURL?.appendingPathComponent("time-to-sleep").path
        
        let task = Process()
        if let bundlePath = bundleBinary, FileManager.default.isExecutableFile(atPath: bundlePath) {
            task.executableURL = URL(fileURLWithPath: bundlePath)
            task.arguments = ["serve"]
        } else if FileManager.default.isExecutableFile(atPath: releaseBinary) {
            task.executableURL = URL(fileURLWithPath: releaseBinary)
            task.arguments = ["serve"]
        } else {
            let zshPath = "/bin/zsh"
            let command = """
            export PATH="$HOME/.cargo/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
            if command -v time-to-sleep >/dev/null 2>&1; then
                exec time-to-sleep serve
            else
                cd "\(projectPath)"
                exec cargo run --release -- serve
            fi
            """
            task.executableURL = URL(fileURLWithPath: zshPath)
            task.arguments = ["-c", command]
        }
        
        do {
            try task.run()
            self.process = task
            print("Native Rust backend process started")
        } catch {
            print("Failed to start backend: \(error)")
        }
    }

    func stop() {
        if let process = process, process.isRunning {
            process.terminate()
            self.process = nil
            print("Backend process terminated")
        }
    }
}
