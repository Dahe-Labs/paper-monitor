import AppKit
import PaperMonitorCore

let app = NSApplication.shared
let delegate = AppDelegate(launchOptions: AppLaunchOptions())
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
