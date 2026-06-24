import Foundation

public enum BundledRuntimeInstaller {
    public static func installFromMainBundle(appSupportDirectory: URL) {
        guard let resourcesURL = Bundle.main.resourceURL else {
            return
        }
        try? install(resourcesURL: resourcesURL, appSupportDirectory: appSupportDirectory)
    }

    public static func install(resourcesURL: URL, appSupportDirectory: URL) throws {
        let fileManager = FileManager.default
        try fileManager.createDirectory(at: appSupportDirectory, withIntermediateDirectories: true)

        try copyDirectoryIfPresent(
            from: resourcesURL.appendingPathComponent("paper_monitor"),
            to: appSupportDirectory.appendingPathComponent("paper_monitor"),
            fileManager: fileManager
        )
        try copyFileIfPresent(
            from: resourcesURL.appendingPathComponent("config.example.json"),
            to: appSupportDirectory.appendingPathComponent("config.example.json"),
            overwrite: true,
            fileManager: fileManager
        )
        try copyFileIfPresent(
            from: resourcesURL.appendingPathComponent("journal_metrics.json"),
            to: appSupportDirectory.appendingPathComponent("journal_metrics.json"),
            overwrite: true,
            fileManager: fileManager
        )
        try copyFileIfPresent(
            from: resourcesURL.appendingPathComponent("README.md"),
            to: appSupportDirectory.appendingPathComponent("README.md"),
            overwrite: true,
            fileManager: fileManager
        )

        let configURL = appSupportDirectory.appendingPathComponent("config.json")
        if !fileManager.fileExists(atPath: configURL.path) {
            try copyFileIfPresent(
                from: resourcesURL.appendingPathComponent("config.example.json"),
                to: configURL,
                overwrite: false,
                fileManager: fileManager
            )
        }
    }

    private static func copyDirectoryIfPresent(from source: URL, to destination: URL, fileManager: FileManager) throws {
        guard fileManager.fileExists(atPath: source.path) else {
            return
        }
        if fileManager.fileExists(atPath: destination.path) {
            try fileManager.removeItem(at: destination)
        }
        try fileManager.copyItem(at: source, to: destination)
    }

    private static func copyFileIfPresent(
        from source: URL,
        to destination: URL,
        overwrite: Bool,
        fileManager: FileManager
    ) throws {
        guard fileManager.fileExists(atPath: source.path) else {
            return
        }
        if fileManager.fileExists(atPath: destination.path) {
            guard overwrite else {
                return
            }
            try fileManager.removeItem(at: destination)
        }
        try fileManager.copyItem(at: source, to: destination)
    }
}
