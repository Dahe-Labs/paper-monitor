import AppKit
import WebKit

@MainActor
public final class DashboardWindowController: NSWindowController {
    private let webView: WKWebView
    private let commandController: DashboardCommandController?

    public init(commandController: DashboardCommandController? = nil) {
        self.commandController = commandController
        let configuration = WKWebViewConfiguration()
        if let commandController {
            configuration.userContentController.add(commandController, name: "paperMonitor")
        }
        let webView = WKWebView(frame: .zero, configuration: configuration)
        self.webView = webView
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1100, height: 760),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = AppIdentity.displayName
        window.center()
        window.contentView = webView
        super.init(window: window)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        commandController?.setJavaScriptEvaluator { [weak webView] script in
            webView?.evaluateJavaScript(script, completionHandler: nil)
        }
    }

    public required init?(coder: NSCoder) {
        nil
    }

    public func load(fileURL: URL) {
        webView.loadFileURL(fileURL, allowingReadAccessTo: fileURL.deletingLastPathComponent())
        showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}

extension DashboardWindowController: WKNavigationDelegate, WKUIDelegate {
    public func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void
    ) {
        let externalURL = DashboardNavigationPolicy.externalURLToOpen(
            for: navigationAction.request.url,
            isUserClick: navigationAction.navigationType == .linkActivated,
            targetFrameIsMissing: navigationAction.targetFrame == nil
        )
        if let externalURL {
            NSWorkspace.shared.open(externalURL)
            decisionHandler(.cancel)
            return
        }

        decisionHandler(.allow)
    }

    public func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        let externalURL = DashboardNavigationPolicy.externalURLToOpen(
            for: navigationAction.request.url,
            isUserClick: navigationAction.navigationType == .linkActivated,
            targetFrameIsMissing: true
        )
        if let externalURL {
            NSWorkspace.shared.open(externalURL)
        }
        return nil
    }
}
