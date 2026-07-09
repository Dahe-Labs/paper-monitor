import AppKit
import PaperMonitorCore

let app = NSApplication.shared
let launchOptions = AppLaunchOptions()
let delegate = AppDelegate(launchOptions: launchOptions)
app.delegate = delegate
app.setActivationPolicy(LaunchPresentationPolicy.activationPolicy(for: launchOptions.launchReason))
app.run()
