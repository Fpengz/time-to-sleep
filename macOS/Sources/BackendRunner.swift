import Foundation

class BackendRunner {
    static let shared = BackendRunner()
    private var process: Process?

    private init() {}

    func start() {
        guard process == nil else { return }
        
        let task = Process()
        let zshPath = "/bin/zsh"
        let projectPath = (NSHomeDirectory() as NSString).appendingPathComponent("projects/time-to-sleep")
        let command = """
        [ -f "$HOME/.zshrc" ] && source "$HOME/.zshrc"
        cd "\(projectPath)"
        exec uv run time-to-sleep
        """
        
        task.executableURL = URL(fileURLWithPath: zshPath)
        task.arguments = ["-il", "-c", command]
        
        do {
            try task.run()
            self.process = task
            print("Backend process started")
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
