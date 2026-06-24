import Foundation
import AppKit
import UserNotifications
import XCTest
@testable import PaperMonitorCore

final class PaperMonitorAppUnitTests: XCTestCase {
    func testParsesRefreshResultJSON() throws {
        let json = """
        {
          "run_id": 12,
          "fetched": 793,
          "matched": 4,
          "new_matches": 1,
          "skipped": 789,
          "dashboard_path": "/tmp/latest.html",
          "articles": [
            {
              "title": "Solid electrolyte breakthrough",
              "journal": "Nature Energy",
              "url": "https://example.org/article",
              "doi": "10.1000/example",
              "published": "2026-06-22",
              "source": "Crossref",
              "matched_terms": ["solid-state battery"],
              "journal_match": "Nature Energy"
            }
          ]
        }
        """.data(using: .utf8)!

        let result = try JSONDecoder().decode(RefreshResult.self, from: json)

        XCTAssertEqual(result.runId, 12)
        XCTAssertEqual(result.fetched, 793)
        XCTAssertEqual(result.articles.count, 1)
        XCTAssertEqual(result.articles[0].url, "https://example.org/article")
    }

    func testBuildsPythonArguments() {
        let bridge = PythonBridge(
            appSupportDirectory: URL(fileURLWithPath: "/Users/example/Library/Application Support/PaperMonitor"),
            pythonPath: "/usr/bin/python3"
        )

        XCTAssertEqual(bridge.pythonPath, "/usr/bin/python3")
        XCTAssertEqual(bridge.arguments, [
            "-m",
            "paper_monitor.cli",
            "app-refresh",
            "--config",
            "/Users/example/Library/Application Support/PaperMonitor/config.json",
        ])
    }

    func testBuildsKeywordAnalysisPythonArguments() {
        let bridge = PythonBridge(
            appSupportDirectory: URL(fileURLWithPath: "/Users/example/Library/Application Support/PaperMonitor"),
            pythonPath: "/usr/bin/python3"
        )
        let request = KeywordAnalysisRequest(
            dateFrom: "2026-06-01",
            dateTo: "2026-06-24",
            sortMode: "impact_factor",
            analysisDepth: "fast",
            topN: 12,
            journals: ["Nature Energy", "Journal of Power Sources"]
        )

        XCTAssertEqual(bridge.analyzeArguments(request: request), [
            "-m",
            "paper_monitor.cli",
            "analyze-keywords",
            "--config",
            "/Users/example/Library/Application Support/PaperMonitor/config.json",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-06-24",
            "--sort-mode",
            "impact_factor",
            "--analysis-depth",
            "fast",
            "--top-n",
            "12",
            "--journal",
            "Nature Energy",
            "--journal",
            "Journal of Power Sources",
        ])
    }

    func testPythonBridgeReadsLargeKeywordAnalysisOutputWithoutPipeDeadlock() throws {
        let directory = try makeTemporaryDirectory()
        let runnerURL = directory.appendingPathComponent("large-output-runner.sh")
        try """
        #!/bin/sh
        /usr/bin/env python3 -c 'import json; print(json.dumps({"papers": ["x" * 200000]}))'
        """.write(to: runnerURL, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: runnerURL.path)
        let bridge = PythonBridge(appSupportDirectory: directory, pythonPath: runnerURL.path)

        let json = try bridge.analyzeKeywords(
            request: KeywordAnalysisRequest(
                dateFrom: "2026-01-01",
                dateTo: "2026-12-31",
                sortMode: "time",
                analysisDepth: "fast",
                topN: 15,
                journals: ["Nature Energy"]
            )
        )

        XCTAssertGreaterThan(json.utf8.count, 65_536)
        XCTAssertTrue(json.contains(#""papers""#))
    }

    func testArticleTargetPrefersArticleURL() {
        let article = ArticleNotification(
            title: "Solid electrolyte breakthrough",
            journal: "Nature Energy",
            url: "https://example.org/article",
            doi: "10.1000/example",
            published: "2026-06-22",
            source: "Crossref",
            matchedTerms: ["solid-state battery"],
            journalMatch: "Nature Energy"
        )

        XCTAssertEqual(
            NotificationController.articleTarget(for: article).absoluteString,
            "https://example.org/article"
        )
    }

    func testArticleTargetFallsBackToDOI() {
        let article = ArticleNotification(
            title: "Solid electrolyte breakthrough",
            journal: "Nature Energy",
            url: "",
            doi: "10.1000/example",
            published: "2026-06-22",
            source: "Crossref",
            matchedTerms: ["solid-state battery"],
            journalMatch: "Nature Energy"
        )

        XCTAssertEqual(
            NotificationController.articleTarget(for: article).absoluteString,
            "https://doi.org/10.1000/example"
        )
    }

    func testMenuBarUsesIconPresentation() {
        let presentation = MenuBarPresentation.default

        XCTAssertEqual(presentation.length, NSStatusItem.squareLength)
        XCTAssertEqual(presentation.title, "")
        XCTAssertEqual(presentation.toolTip, "Paper Monitor")
        XCTAssertEqual(presentation.iconName, "MenuBarIcon")
        XCTAssertEqual(presentation.iconPointSize, 20)
        XCTAssertTrue(presentation.isTemplate)
    }

    @MainActor
    func testMenuControllerDefaultStatusItemUsesReadablePaperMonitorLabel() {
        let controller = MenuController()

        XCTAssertEqual(controller.statusItemSnapshotForTesting.title, "")
        XCTAssertTrue(controller.statusItemSnapshotForTesting.hasImage)
        XCTAssertTrue(controller.statusItemSnapshotForTesting.isVisible)
        XCTAssertEqual(controller.statusItemAutosaveNameForTesting, "com.local.paper-monitor.app.status-item")
    }

    func testMenuBarIconLoaderReadsPNGFromAppBundleResources() throws {
        let bundleURL = try makeTemporaryDirectory().appendingPathComponent("Test.app", isDirectory: true)
        let contentsURL = bundleURL.appendingPathComponent("Contents", isDirectory: true)
        let resourcesURL = contentsURL.appendingPathComponent("Resources", isDirectory: true)
        try FileManager.default.createDirectory(at: resourcesURL, withIntermediateDirectories: true)
        try """
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
          <key>CFBundleIdentifier</key>
          <string>local.test.bundle</string>
          <key>CFBundlePackageType</key>
          <string>APPL</string>
        </dict>
        </plist>
        """.write(to: contentsURL.appendingPathComponent("Info.plist"), atomically: true, encoding: .utf8)
        try makeTestPNGData().write(to: resourcesURL.appendingPathComponent("MenuBarIcon.png"))

        let bundle = try XCTUnwrap(Bundle(url: bundleURL))
        let image = try XCTUnwrap(MenuBarIconLoader(bundle: bundle).image(for: .default))

        XCTAssertEqual(image.size, NSSize(width: 20, height: 20))
        XCTAssertTrue(image.isTemplate)
    }

    @MainActor
    func testMenuControllerUsesFallbackIconWhenResourceIsMissing() {
        let presentation = MenuBarPresentation(
            length: NSStatusItem.squareLength,
            title: "",
            toolTip: "Paper Monitor",
            iconName: "DefinitelyMissingMenuBarIcon",
            isTemplate: true,
            iconPointSize: 18
        )
        let controller = MenuController(presentation: presentation)

        XCTAssertTrue(controller.statusItemSnapshotForTesting.isVisible)
        XCTAssertTrue(controller.statusItemSnapshotForTesting.hasImage)
        XCTAssertEqual(controller.statusItemSnapshotForTesting.title, "")
    }

    @MainActor
    func testMenuControllerContainsSettingsMenuItem() {
        let controller = MenuController()

        XCTAssertEqual(controller.menuItemsForTesting, [
            MenuController.MenuItemSnapshot(title: "Paper Monitor", keyEquivalent: "", actionName: nil),
            MenuController.MenuItemSnapshot(title: "", keyEquivalent: "", actionName: nil),
            MenuController.MenuItemSnapshot(title: "Last Run: never", keyEquivalent: "", actionName: nil),
            MenuController.MenuItemSnapshot(title: "Last Result: none", keyEquivalent: "", actionName: nil),
            MenuController.MenuItemSnapshot(title: "Notification Permission: unknown", keyEquivalent: "", actionName: nil),
            MenuController.MenuItemSnapshot(title: "", keyEquivalent: "", actionName: nil),
            MenuController.MenuItemSnapshot(title: "Open Dashboard", keyEquivalent: "o", actionName: "openDashboardAction"),
            MenuController.MenuItemSnapshot(title: "Settings...", keyEquivalent: ",", actionName: "openSettingsAction"),
            MenuController.MenuItemSnapshot(title: "Refresh Now", keyEquivalent: "r", actionName: "refreshNowAction"),
            MenuController.MenuItemSnapshot(title: "Test Notification", keyEquivalent: "t", actionName: "testNotificationAction"),
            MenuController.MenuItemSnapshot(title: "", keyEquivalent: "", actionName: nil),
            MenuController.MenuItemSnapshot(title: "Quit", keyEquivalent: "q", actionName: "quitAction"),
        ])
    }

    @MainActor
    func testMenuControllerInvokesDashboardAndSettingsCallbacks() {
        let controller = MenuController()
        var didOpenDashboard = false
        var didOpenSettings = false
        controller.onOpenDashboard = {
            didOpenDashboard = true
        }
        controller.onOpenSettings = {
            didOpenSettings = true
        }

        controller.triggerMenuItemForTesting(title: "Open Dashboard")
        controller.triggerMenuItemForTesting(title: "Settings...")

        XCTAssertTrue(didOpenDashboard)
        XCTAssertTrue(didOpenSettings)
    }

    @MainActor
    func testMainApplicationMenuContainsSettingsFallbackChannel() {
        let controller = AppMainMenuController()

        XCTAssertEqual(controller.menuItemsForTesting, [
            AppMainMenuController.MenuItemSnapshot(title: "Paper Monitor", actionName: nil),
            AppMainMenuController.MenuItemSnapshot(title: "Open Dashboard", actionName: "openDashboardAction"),
            AppMainMenuController.MenuItemSnapshot(title: "Settings...", actionName: "openSettingsAction"),
            AppMainMenuController.MenuItemSnapshot(title: "Refresh Now", actionName: "refreshNowAction"),
            AppMainMenuController.MenuItemSnapshot(title: "Test Notification", actionName: "testNotificationAction"),
            AppMainMenuController.MenuItemSnapshot(title: "Quit Paper Monitor", actionName: "quitAction"),
        ])
    }

    @MainActor
    func testMainApplicationMenuInvokesSettingsFallbackChannel() {
        let controller = AppMainMenuController()
        var didOpenSettings = false
        controller.onOpenSettings = {
            didOpenSettings = true
        }

        controller.triggerMenuItemForTesting(title: "Settings...")

        XCTAssertTrue(didOpenSettings)
    }

    @MainActor
    func testSettingsWindowController() throws {
        let controller = SettingsWindowController(settings: .default, journalCatalog: nil) { _ in true }
        let window = try XCTUnwrap(controller.window)
        let tabViewController = try XCTUnwrap(window.contentViewController as? NSTabViewController)

        XCTAssertEqual(window.title, "Paper Monitor Settings")
        XCTAssertEqual(window.minSize, NSSize(width: 640, height: 420))
        XCTAssertFalse(window.isReleasedWhenClosed)
        XCTAssertEqual(tabViewController.tabViewItems.map(\.label), [
            "Search Settings",
            "Search Terms",
            "Journal Filter",
        ])
        XCTAssertTrue(tabViewController.tabViewItems[2].viewController is JournalFilterViewController)
    }

    func testActivationNotificationNameIsStable() {
        XCTAssertEqual(
            AppActivationCoordinator.openDashboardNotificationName.rawValue,
            "com.local.paper-monitor.open-dashboard"
        )
        XCTAssertEqual(
            AppActivationCoordinator.testNotificationName.rawValue,
            "com.local.paper-monitor.test-notification"
        )
    }

    func testLaunchOptionsParseTestNotificationFlag() {
        XCTAssertTrue(
            AppLaunchOptions(arguments: ["PaperMonitorApp", "--test-notification"]).postTestNotificationOnLaunch
        )
        XCTAssertFalse(
            AppLaunchOptions(arguments: ["PaperMonitorApp"]).postTestNotificationOnLaunch
        )
    }

    func testBuildsStableTestNotificationArticle() {
        let article = NotificationController.testArticle()

        XCTAssertEqual(article.title, "Paper Monitor test")
        XCTAssertEqual(article.journal, "Notification Test")
        XCTAssertEqual(
            NotificationController.articleTarget(for: article).absoluteString,
            "https://example.org/paper-monitor-test"
        )
    }

    func testNotificationPostReportsAddErrors() throws {
        let article = NotificationController.testArticle()
        let dashboardURL = URL(fileURLWithPath: "/tmp/latest.html")
        let recorder = NotificationTestRecorder()
        let controller = NotificationController(
            addRequest: { request, completion in
                recorder.capturedRequest = request
                completion(TestNotificationError.rejected)
            },
            notificationErrorLogger: { message in
                recorder.loggedMessage = message
            }
        )

        controller.post(article: article, dashboardURL: dashboardURL)

        XCTAssertEqual(recorder.capturedRequest?.content.title, "Paper Monitor test")
        XCTAssertEqual(recorder.loggedMessage, "Paper Monitor notification failed: rejected")
    }

    func testForegroundNotificationsArePresentedWhileAppIsActive() {
        let options = NotificationController.foregroundPresentationOptions

        XCTAssertTrue(options.contains(.banner))
        XCTAssertTrue(options.contains(.list))
        XCTAssertTrue(options.contains(.sound))
    }

    @MainActor
    func testDashboardWindowUsesPaperMonitorTitle() throws {
        let controller = DashboardWindowController()

        XCTAssertEqual(try XCTUnwrap(controller.window).title, "Paper Monitor")
    }

    @MainActor
    func testDashboardCommandControllerAddsSearchTermFromMessage() throws {
        let configURL = try makeDashboardCommandConfigURL()
        let store = SettingsStore(configURL: configURL)
        let controller = DashboardCommandController(settingsStore: store)

        XCTAssertTrue(controller.handle(messageBody: ["type": "addSearchTerm", "term": "halide electrolyte"]))

        XCTAssertEqual(try store.load().includeTerms, ["solid electrolyte", "halide electrolyte"])
    }

    @MainActor
    func testDashboardCommandControllerParsesKeywordAnalysisRequestFromMessage() throws {
        let request = DashboardCommandController.keywordAnalysisRequest(
            from: [
                "type": "analyzeKeywords",
                "date_from": "2026-06-01",
                "date_to": "2026-06-24",
                "sort_mode": "impact_factor",
                "analysis_depth": "exhaustive",
                "top_n": 12,
                "journals": ["Nature Energy", "Journal of Power Sources"],
            ]
        )

        XCTAssertEqual(
            request,
            KeywordAnalysisRequest(
                dateFrom: "2026-06-01",
                dateTo: "2026-06-24",
                sortMode: "impact_factor",
                analysisDepth: "exhaustive",
                topN: 12,
                journals: ["Nature Energy", "Journal of Power Sources"]
            )
        )
    }

    @MainActor
    func testDashboardCommandControllerBuildsKeywordAnalysisCallbackScript() throws {
        XCTAssertEqual(
            DashboardCommandController.keywordAnalysisCallbackScript(jsonPayload: #"{"papers":[]}"#),
            #"window.paperMonitorReceiveKeywordAnalysis({"papers":[]});"#
        )

        let errorScript = DashboardCommandController.keywordAnalysisErrorCallbackScript(message: "Crossref failed")

        XCTAssertTrue(errorScript.contains("paperMonitorReceiveKeywordAnalysis"))
        XCTAssertTrue(errorScript.contains(#""error":"Crossref failed""#))
    }

    @MainActor
    func testDashboardCommandControllerIgnoresConcurrentKeywordAnalysisRequests() throws {
        let configURL = try makeDashboardCommandConfigURL()
        let store = SettingsStore(configURL: configURL)
        let runCount = LockedCounter()
        let firstRunStarted = expectation(description: "first keyword analysis started")
        let firstRunCanFinish = DispatchSemaphore(value: 0)
        let callbackReceived = expectation(description: "keyword analysis callback received")
        let requestBody: [String: Any] = [
            "type": "analyzeKeywords",
            "date_from": "2026-06-01",
            "date_to": "2026-06-24",
            "sort_mode": "time",
            "analysis_depth": "fast",
            "top_n": 15,
            "journals": ["Nature Energy"],
        ]
        let controller = DashboardCommandController(
            settingsStore: store,
            keywordAnalysisRunner: { _ in
                let count = runCount.increment()
                if count == 1 {
                    firstRunStarted.fulfill()
                }
                firstRunCanFinish.wait()
                return #"{"papers":[]}"#
            },
            evaluateJavaScript: { _ in
                callbackReceived.fulfill()
            }
        )

        XCTAssertTrue(controller.handle(messageBody: requestBody))
        wait(for: [firstRunStarted], timeout: 2)

        XCTAssertTrue(controller.handle(messageBody: requestBody))
        XCTAssertEqual(runCount.current, 1)

        firstRunCanFinish.signal()
        wait(for: [callbackReceived], timeout: 2)
    }

    @MainActor
    func testDashboardCommandControllerRejectsInvalidMessageBodiesWithoutMutatingSettings() throws {
        let configURL = try makeDashboardCommandConfigURL()
        let store = SettingsStore(configURL: configURL)
        let controller = DashboardCommandController(settingsStore: store)

        let invalidBodies: [Any] = [
            NSNull(),
            ["type": "unknown", "term": "halide electrolyte"],
            ["type": "addSearchTerm"],
            ["type": "addSearchTerm", "term": 42],
        ]

        for body in invalidBodies {
            XCTAssertFalse(controller.handle(messageBody: body))
        }

        XCTAssertEqual(try store.load().includeTerms, ["solid electrolyte"])
    }

    @MainActor
    func testDashboardCommandControllerRejectsBlankSearchTermWithoutMutatingSettings() throws {
        let configURL = try makeDashboardCommandConfigURL()
        let store = SettingsStore(configURL: configURL)
        let controller = DashboardCommandController(settingsStore: store)

        XCTAssertFalse(controller.handle(messageBody: ["type": "addSearchTerm", "term": " \n\t "]))

        XCTAssertEqual(try store.load().includeTerms, ["solid electrolyte"])
    }

    @MainActor
    func testDashboardCommandControllerRejectsOversizedSearchTermWithoutMutatingSettings() throws {
        let configURL = try makeDashboardCommandConfigURL()
        let store = SettingsStore(configURL: configURL)
        let controller = DashboardCommandController(settingsStore: store)
        let oversizedTerm = String(repeating: "a", count: DashboardCommandController.maximumSearchTermLength + 1)

        XCTAssertFalse(controller.handle(messageBody: ["type": "addSearchTerm", "term": oversizedTerm]))

        XCTAssertEqual(try store.load().includeTerms, ["solid electrolyte"])
    }

    @MainActor
    func testDashboardCommandControllerRejectsNonWhitespaceControlCharactersWithoutMutatingSettings() throws {
        let configURL = try makeDashboardCommandConfigURL()
        let store = SettingsStore(configURL: configURL)
        let controller = DashboardCommandController(settingsStore: store)

        XCTAssertFalse(controller.handle(messageBody: ["type": "addSearchTerm", "term": "stack\u{0007}pressure"]))

        XCTAssertEqual(try store.load().includeTerms, ["solid electrolyte"])
    }

    @MainActor
    func testDashboardCommandControllerNormalizesWhitespaceSearchTermFromMessage() throws {
        let configURL = try makeDashboardCommandConfigURL()
        let store = SettingsStore(configURL: configURL)
        let controller = DashboardCommandController(settingsStore: store)

        XCTAssertTrue(controller.handle(messageBody: ["type": "addSearchTerm", "term": "  stack\n pressure\t "]))

        XCTAssertEqual(try store.load().includeTerms, ["solid electrolyte", "stack pressure"])
    }

    func testDashboardNavigationPolicyOpensClickedWebLinksExternally() {
        let target = DashboardNavigationPolicy.externalURLToOpen(
            for: URL(string: "https://example.org/article"),
            isUserClick: true,
            targetFrameIsMissing: false
        )

        XCTAssertEqual(target?.absoluteString, "https://example.org/article")
    }

    func testDashboardNavigationPolicyKeepsFileLoadsInternal() {
        let target = DashboardNavigationPolicy.externalURLToOpen(
            for: URL(fileURLWithPath: "/tmp/latest.html"),
            isUserClick: false,
            targetFrameIsMissing: false
        )

        XCTAssertNil(target)
    }

    func testRefreshRunGateRejectsConcurrentRefreshesUntilFinished() {
        var gate = RefreshRunGate()

        XCTAssertTrue(gate.begin())
        XCTAssertTrue(gate.isRefreshing)
        XCTAssertFalse(gate.begin())

        gate.finish()

        XCTAssertFalse(gate.isRefreshing)
        XCTAssertTrue(gate.begin())
    }

    @MainActor
    func testRefreshSchedulerReplacesExistingTimerWhenIntervalChanges() {
        var timers: [TestRefreshTimer] = []
        let scheduler = RefreshScheduler { interval, handler in
            let timer = TestRefreshTimer(interval: interval, handler: handler)
            timers.append(timer)
            return timer
        }
        var fireCount = 0

        scheduler.schedule(interval: 3600) {
            fireCount += 1
        }
        XCTAssertEqual(scheduler.currentInterval, 3600)
        XCTAssertTrue(scheduler.isScheduled)
        XCTAssertEqual(timers.count, 1)
        XCTAssertEqual(timers[0].interval, 3600)
        XCTAssertEqual(timers[0].invalidateCount, 0)

        scheduler.schedule(interval: 7200) {
            fireCount += 10
        }

        XCTAssertEqual(scheduler.currentInterval, 7200)
        XCTAssertTrue(scheduler.isScheduled)
        XCTAssertEqual(fireCount, 0)
        XCTAssertEqual(timers.count, 2)
        XCTAssertEqual(timers[0].invalidateCount, 1)
        XCTAssertEqual(timers[1].interval, 7200)
        XCTAssertEqual(timers[1].invalidateCount, 0)

        scheduler.invalidate()
        XCTAssertFalse(scheduler.isScheduled)
        XCTAssertNil(scheduler.currentInterval)
        XCTAssertEqual(timers[1].invalidateCount, 1)
    }

    @MainActor
    func testRefreshSchedulerInvalidatesAndSkipsNonPositiveIntervals() {
        var timers: [TestRefreshTimer] = []
        let scheduler = RefreshScheduler { interval, handler in
            let timer = TestRefreshTimer(interval: interval, handler: handler)
            timers.append(timer)
            return timer
        }

        scheduler.schedule(interval: 3600) {}
        scheduler.schedule(interval: 0) {}

        XCTAssertFalse(scheduler.isScheduled)
        XCTAssertNil(scheduler.currentInterval)
        XCTAssertEqual(timers.count, 1)
        XCTAssertEqual(timers[0].invalidateCount, 1)
    }

    @MainActor
    func testRefreshSchedulerInvalidatesTimerOnDeinit() {
        var timers: [TestRefreshTimer] = []
        var scheduler: RefreshScheduler? = RefreshScheduler { interval, handler in
            let timer = TestRefreshTimer(interval: interval, handler: handler)
            timers.append(timer)
            return timer
        }

        scheduler?.schedule(interval: 3600) {}
        scheduler = nil

        XCTAssertEqual(timers.count, 1)
        XCTAssertEqual(timers[0].invalidateCount, 1)
    }

    func testRefreshPresentationKeepsRefreshErrorsSeparateFromNotificationPermission() {
        XCTAssertEqual(RefreshPresentation.refreshingResultTitle, "Last Result: Refreshing...")
        XCTAssertEqual(RefreshPresentation.failedResultTitle, "Last Result: Refresh failed")
        XCTAssertEqual(
            RefreshPresentation.permissionTitle("Granted"),
            "Notification Permission: Granted"
        )
    }

    func testRefreshPresentationSurfacesSourceWarnings() throws {
        let json = """
        {
          "run_id": 12,
          "fetched": 793,
          "matched": 4,
          "new_matches": 1,
          "skipped": 789,
          "dashboard_path": "/tmp/latest.html",
          "warnings": ["warning: RSS source failed"],
          "articles": []
        }
        """.data(using: .utf8)!

        let result = try JSONDecoder().decode(RefreshResult.self, from: json)

        XCTAssertEqual(
            RefreshPresentation.resultTitle(for: result),
            "Last Result: Fetched 793 · Matched 4 · New 1 · Warnings 1"
        )
    }

    func testPythonBridgeExtractsOnlyWarningLinesFromStderr() {
        let stderr = """
        warning: RSS source failed

        debug: ignored
        warning: Crossref query failed
        """.data(using: .utf8)!

        XCTAssertEqual(
            PythonBridge.warningLines(from: stderr),
            ["warning: RSS source failed", "warning: Crossref query failed"]
        )
    }

    func testBundledRuntimeInstallerCopiesRuntimeResourcesAndPreservesUserConfig() throws {
        let directory = try makeTemporaryDirectory()
        let resourcesURL = directory.appendingPathComponent("Resources")
        let packageURL = resourcesURL.appendingPathComponent("paper_monitor")
        let appSupportURL = directory.appendingPathComponent("Application Support")
        try FileManager.default.createDirectory(at: packageURL, withIntermediateDirectories: true)
        try "print('cli')".write(to: packageURL.appendingPathComponent("cli.py"), atomically: true, encoding: .utf8)
        try #"{"interval_seconds":43200}"#.write(
            to: resourcesURL.appendingPathComponent("config.example.json"),
            atomically: true,
            encoding: .utf8
        )
        try #"{"journals":[]}"#.write(
            to: resourcesURL.appendingPathComponent("journal_metrics.json"),
            atomically: true,
            encoding: .utf8
        )
        try "Read me".write(to: resourcesURL.appendingPathComponent("README.md"), atomically: true, encoding: .utf8)
        try FileManager.default.createDirectory(at: appSupportURL, withIntermediateDirectories: true)
        try #"{"interval_seconds":3600}"#.write(
            to: appSupportURL.appendingPathComponent("config.json"),
            atomically: true,
            encoding: .utf8
        )

        try BundledRuntimeInstaller.install(resourcesURL: resourcesURL, appSupportDirectory: appSupportURL)

        XCTAssertTrue(FileManager.default.fileExists(atPath: appSupportURL.appendingPathComponent("paper_monitor/cli.py").path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: appSupportURL.appendingPathComponent("journal_metrics.json").path))
        XCTAssertEqual(
            try String(contentsOf: appSupportURL.appendingPathComponent("config.json"), encoding: .utf8),
            #"{"interval_seconds":3600}"#
        )
    }

    func testBundledRuntimeInstallerSeedsConfigWhenMissing() throws {
        let directory = try makeTemporaryDirectory()
        let resourcesURL = directory.appendingPathComponent("Resources")
        let appSupportURL = directory.appendingPathComponent("Application Support")
        try FileManager.default.createDirectory(at: resourcesURL, withIntermediateDirectories: true)
        try #"{"interval_seconds":43200}"#.write(
            to: resourcesURL.appendingPathComponent("config.example.json"),
            atomically: true,
            encoding: .utf8
        )

        try BundledRuntimeInstaller.install(resourcesURL: resourcesURL, appSupportDirectory: appSupportURL)

        XCTAssertEqual(
            try String(contentsOf: appSupportURL.appendingPathComponent("config.json"), encoding: .utf8),
            #"{"interval_seconds":43200}"#
        )
    }

    func testRefreshSettingsLoadsIntervalSecondsFromConfigJSON() throws {
        let data = #"{"interval_seconds": 7200}"#.data(using: .utf8)!

        XCTAssertEqual(AppRefreshSettings.intervalSeconds(from: data), 7200)
    }

    func testRefreshSettingsFallsBackForMissingOrInvalidInterval() throws {
        XCTAssertEqual(
            AppRefreshSettings.intervalSeconds(from: #"{}"#.data(using: .utf8)!),
            AppRefreshSettings.defaultIntervalSeconds
        )
        XCTAssertEqual(
            AppRefreshSettings.intervalSeconds(from: #"{"interval_seconds": 0}"#.data(using: .utf8)!),
            AppRefreshSettings.defaultIntervalSeconds
        )
    }

    func testSettingsStoreLoadsAndNormalizesConfig() throws {
        let directory = try makeTemporaryDirectory()
        let configURL = directory.appendingPathComponent("config.json")
        try """
        {
          "settings_schema_version": 1,
          "journal_scope": {
            "top_n": 55,
            "selected_journals": ["Nature Energy", "", "Nature Energy", "Advanced Materials"]
          },
          "interval_seconds": 3600,
          "include_terms": ["solid electrolyte", "", "solid electrolyte", "LLZO"],
          "exclude_terms": ["solid-state laser", "", "solid-state laser"],
          "sources": {
            "rss": [],
            "crossref": {"enabled": true, "journal_titles": [], "query": ""},
            "openalex": {"enabled": false, "query": ""}
          },
          "search_direction": {
            "preset": "solid_electrolyte",
            "label": "Solid electrolyte",
            "crossref_query": "solid electrolyte OR LLZO",
            "openalex_query": "solid electrolyte LLZO",
            "query_manually_edited": true
          }
        }
        """.write(to: configURL, atomically: true, encoding: .utf8)

        let store = SettingsStore(configURL: configURL)
        let settings = try store.load()

        XCTAssertEqual(settings.schemaVersion, 1)
        XCTAssertEqual(settings.journalScope.topN, 50)
        XCTAssertEqual(settings.journalScope.selectedJournals, ["Nature Energy", "Advanced Materials"])
        XCTAssertEqual(settings.intervalSeconds, 3600)
        XCTAssertEqual(settings.includeTerms, ["solid electrolyte", "LLZO"])
        XCTAssertEqual(settings.excludeTerms, ["solid-state laser"])
        XCTAssertEqual(settings.searchDirection.preset, "solid_electrolyte")
        XCTAssertEqual(settings.searchDirection.label, "Solid electrolyte")
        XCTAssertEqual(settings.searchDirection.crossrefQuery, "solid electrolyte OR LLZO")
        XCTAssertEqual(settings.searchDirection.openalexQuery, "solid electrolyte LLZO")
        XCTAssertTrue(settings.searchDirection.queryManuallyEdited)
    }

    func testSettingsStoreAddsIncludeTermAndRegeneratesQueries() throws {
        let directory = try makeTemporaryDirectory()
        let configURL = directory.appendingPathComponent("config.json")
        try """
        {
          "settings_schema_version": 1,
          "journal_scope": {
            "top_n": 1,
            "selected_journals": ["Nature Energy"]
          },
          "interval_seconds": 3600,
          "include_terms": ["solid electrolyte"],
          "exclude_terms": [],
          "search_direction": {
            "preset": "solid_state_battery_general",
            "label": "Solid-state battery general",
            "crossref_query": "solid electrolyte",
            "openalex_query": "solid electrolyte",
            "query_manually_edited": false
          },
          "sources": {
            "crossref": {"journal_titles": [], "query": ""},
            "openalex": {"query": ""}
          }
        }
        """.write(to: configURL, atomically: true, encoding: .utf8)
        let store = SettingsStore(configURL: configURL)

        let settings = try store.addIncludeTerm(" stack pressure ")

        XCTAssertEqual(settings.includeTerms, ["solid electrolyte", "stack pressure"])
        XCTAssertEqual(settings.searchDirection.crossrefQuery, "solid electrolyte OR stack pressure")
        let payload = try JSONSerialization.jsonObject(with: Data(contentsOf: configURL)) as? [String: Any]
        XCTAssertEqual(payload?["include_terms"] as? [String], ["solid electrolyte", "stack pressure"])
    }

    func testSettingsStoreAddsIncludeTermPreservesManualQueryStrings() throws {
        let configURL = try makeDashboardCommandConfigURL(queryManuallyEdited: true)
        let store = SettingsStore(configURL: configURL)

        let settings = try store.addIncludeTerm("stack pressure")

        XCTAssertEqual(settings.includeTerms, ["solid electrolyte", "stack pressure"])
        XCTAssertEqual(settings.searchDirection.crossrefQuery, "manual crossref query")
        XCTAssertEqual(settings.searchDirection.openalexQuery, "manual openalex query")
    }

    func testSettingsStoreAddIncludeTermDoesNotDuplicateExistingTerm() throws {
        let configURL = try makeDashboardCommandConfigURL()
        let store = SettingsStore(configURL: configURL)

        let settings = try store.addIncludeTerm(" solid electrolyte ")

        XCTAssertEqual(settings.includeTerms, ["solid electrolyte"])
        XCTAssertEqual(settings.searchDirection.crossrefQuery, "solid electrolyte")
        let payload = try JSONSerialization.jsonObject(with: Data(contentsOf: configURL)) as? [String: Any]
        XCTAssertEqual(payload?["include_terms"] as? [String], ["solid electrolyte"])
    }

    func testSearchPresetAppliesTermsAndQueriesUntilQueryIsManuallyEdited() {
        var settings = AppSettings.default
        let preset = SearchPreset.solidElectrolyte

        preset.apply(to: &settings)

        XCTAssertEqual(settings.searchDirection.preset, "solid_electrolyte")
        XCTAssertTrue(settings.includeTerms.contains("solid electrolyte"))
        XCTAssertTrue(settings.searchDirection.crossrefQuery.contains("solid electrolyte"))
        XCTAssertFalse(settings.searchDirection.queryManuallyEdited)

        settings.searchDirection.crossrefQuery = "custom query"
        settings.searchDirection.queryManuallyEdited = true
        settings.includeTerms = ["LLZO"]
        SearchPreset.regenerateQueriesIfAllowed(for: &settings)

        XCTAssertEqual(settings.searchDirection.crossrefQuery, "custom query")
    }

    func testSearchPresetDefaultTermsAndQueriesUseEnglishOnly() {
        var settings = AppSettings.default

        SearchPreset.solidStateBatteryGeneral.apply(to: &settings)

        XCTAssertFalse(settings.includeTerms.contains { containsHan($0) })
        XCTAssertFalse(containsHan(settings.searchDirection.crossrefQuery))
        XCTAssertFalse(containsHan(settings.searchDirection.openalexQuery))
        XCTAssertTrue(settings.includeTerms.contains("electrolyte"))
        XCTAssertTrue(settings.includeTerms.contains("electrode"))
    }

    func testEditingTermsDedupesAndRegeneratesQueriesWhenAllowed() {
        var settings = AppSettings.default
        settings.searchDirection.queryManuallyEdited = false

        SearchTermEditor.updateIncludeTerms(["solid electrolyte", "", "solid electrolyte", "LLZO"], in: &settings)

        XCTAssertEqual(settings.includeTerms, ["solid electrolyte", "LLZO"])
        XCTAssertEqual(settings.searchDirection.crossrefQuery, "solid electrolyte OR LLZO")
    }

    func testEditingExcludeTermsDedupesAndIgnoresEmptyTerms() {
        var settings = AppSettings.default

        SearchTermEditor.updateExcludeTerms(["solid-state laser", "", " solid-state laser ", "solid-state drive"], in: &settings)

        XCTAssertEqual(settings.excludeTerms, ["solid-state laser", "solid-state drive"])
    }

    func testSearchSettingsTopNAppliesCatalogJournalsWhenAvailable() {
        var settings = AppSettings.default
        settings.journalScope.selectedJournals = ["Existing"]
        let catalog = makeJournalCatalog(["Nature", "Science", "Cell"])

        SearchSettingsPolicy.applyTopN(2, to: &settings, catalog: catalog)

        XCTAssertEqual(settings.journalScope.topN, 2)
        XCTAssertEqual(settings.journalScope.selectedJournals, ["Nature", "Science"])
    }

    func testSearchSettingsTopNPreservesSelectedJournalsWhenCatalogIsEmpty() {
        var settings = AppSettings.default
        settings.journalScope.selectedJournals = ["Existing"]
        let catalog = JournalCatalog(entries: [])

        SearchSettingsPolicy.applyTopN(2, to: &settings, catalog: catalog)

        XCTAssertEqual(settings.journalScope.topN, 2)
        XCTAssertEqual(settings.journalScope.selectedJournals, ["Existing"])
    }

    func testJournalSelectionAppliesTopNAndManualOverrides() {
        let catalog = JournalCatalog(entries: (1...5).map {
            JournalCatalogEntry(
                rank: $0,
                journal: "Journal \($0)",
                aliases: [],
                impactFactor: nil,
                impactFactorYear: nil,
                fiveYearImpactFactor: nil,
                level: "",
                sourceURL: ""
            )
        })

        var selection = JournalSelection(topN: 3, selectedJournals: [])
        selection.applyTopN(catalog)
        selection.setSelected(false, journal: "Journal 2")
        selection.setSelected(true, journal: "Journal 5")

        XCTAssertEqual(selection.selectedJournals, ["Journal 1", "Journal 3", "Journal 5"])
    }

    func testJournalCatalogTopJournalsUsesImpactFactorDescendingOrder() {
        let catalog = JournalCatalog(entries: [
            JournalCatalogEntry(
                rank: 1,
                journal: "Low IF Journal",
                aliases: [],
                impactFactor: 7.1,
                impactFactorYear: 2025,
                fiveYearImpactFactor: nil,
                level: "Materials",
                sourceURL: "https://example.org/low"
            ),
            JournalCatalogEntry(
                rank: 2,
                journal: "No IF Journal",
                aliases: [],
                impactFactor: nil,
                impactFactorYear: nil,
                fiveYearImpactFactor: nil,
                level: "Materials",
                sourceURL: "https://example.org/no-if"
            ),
            JournalCatalogEntry(
                rank: 3,
                journal: "High IF Journal",
                aliases: [],
                impactFactor: 60.1,
                impactFactorYear: 2024,
                fiveYearImpactFactor: nil,
                level: "Energy",
                sourceURL: "https://example.org/high"
            ),
        ])

        XCTAssertEqual(catalog.topJournals(2).map(\.journal), ["High IF Journal", "Low IF Journal"])
    }

    @MainActor
    func testJournalFilterAppliesTopNAndAutoSaves() throws {
        var settings = AppSettings.default
        settings.journalScope = JournalScope(topN: 1, selectedJournals: ["Nature"])
        let catalog = makeJournalCatalog(["Nature", "Science", "Cell"])
        var emitted: [AppSettings] = []
        let controller = JournalFilterViewController(settings: settings, catalog: catalog) { saved in
            emitted.append(saved)
            return true
        }

        controller.applyTopNForTesting(2)

        let saved = try XCTUnwrap(emitted.last)
        XCTAssertEqual(saved.journalScope.topN, 2)
        XCTAssertEqual(saved.journalScope.selectedJournals, ["Nature", "Science"])
        XCTAssertEqual(controller.selectedCountForTesting, 2)
    }

    @MainActor
    func testJournalFilterManualTogglePreservesAtLeastOneJournal() throws {
        var settings = AppSettings.default
        settings.journalScope = JournalScope(topN: 1, selectedJournals: ["Nature"])
        let controller = JournalFilterViewController(
            settings: settings,
            catalog: makeJournalCatalog(["Nature", "Science"])
        ) { _ in true }

        controller.toggleJournalForTesting("Nature", selected: false)
        XCTAssertEqual(controller.selectedJournalNamesForTesting, ["Nature"])

        controller.toggleJournalForTesting("Science", selected: true)
        controller.toggleJournalForTesting("Nature", selected: false)

        XCTAssertEqual(controller.selectedJournalNamesForTesting, ["Science"])
    }

    @MainActor
    func testJournalFilterFiltersByJournalAliasAndLevel() {
        var settings = AppSettings.default
        settings.journalScope = JournalScope(topN: 1, selectedJournals: ["Nature Energy"])
        let catalog = JournalCatalog(entries: [
            JournalCatalogEntry(
                rank: 1,
                journal: "Nature Energy",
                aliases: ["Nat Energy"],
                impactFactor: 56.7,
                impactFactorYear: 2025,
                fiveYearImpactFactor: nil,
                level: "Energy materials",
                sourceURL: "https://example.org/nature-energy"
            ),
            JournalCatalogEntry(
                rank: 2,
                journal: "Advanced Materials",
                aliases: ["Adv Mater"],
                impactFactor: 29.4,
                impactFactorYear: 2025,
                fiveYearImpactFactor: nil,
                level: "Materials science",
                sourceURL: "https://example.org/advanced-materials"
            ),
        ])
        let controller = JournalFilterViewController(settings: settings, catalog: catalog) { _ in true }

        controller.filterForTesting("adv mater")
        XCTAssertEqual(controller.visibleJournalNamesForTesting, ["Advanced Materials"])

        controller.filterForTesting("energy materials")
        XCTAssertEqual(controller.visibleJournalNamesForTesting, ["Nature Energy"])
    }

    @MainActor
    func testJournalFilterDoesNotDisplayRankOrImpactFactorYearColumns() throws {
        var settings = AppSettings.default
        settings.journalScope = JournalScope(topN: 1, selectedJournals: ["Nature Energy"])
        let catalog = JournalCatalog(entries: [
            JournalCatalogEntry(
                rank: 1,
                journal: "Nature Energy",
                aliases: [],
                impactFactor: 60.1,
                impactFactorYear: 2024,
                fiveYearImpactFactor: nil,
                level: "Energy materials",
                sourceURL: "https://example.org/nature-energy"
            ),
        ])
        let controller = JournalFilterViewController(settings: settings, catalog: catalog) { _ in true }

        let tableView = try XCTUnwrap(findTableView(in: controller.view))
        let identifiers = tableView.tableColumns.map { $0.identifier.rawValue }
        let titles = tableView.tableColumns.map(\.title)

        XCTAssertFalse(identifiers.contains("rank"))
        XCTAssertFalse(titles.contains("Rank"))
        XCTAssertFalse(identifiers.contains("impactYear"))
        XCTAssertFalse(titles.contains("Year"))
    }

    @MainActor
    func testJournalFilterDefaultsToImpactFactorDescendingOrder() {
        var settings = AppSettings.default
        settings.journalScope = JournalScope(topN: 1, selectedJournals: ["Nature Energy"])
        let catalog = JournalCatalog(entries: [
            JournalCatalogEntry(
                rank: 1,
                journal: "Low IF Journal",
                aliases: [],
                impactFactor: 7.1,
                impactFactorYear: 2025,
                fiveYearImpactFactor: nil,
                level: "Materials",
                sourceURL: "https://example.org/low"
            ),
            JournalCatalogEntry(
                rank: 2,
                journal: "No IF Journal",
                aliases: [],
                impactFactor: nil,
                impactFactorYear: nil,
                fiveYearImpactFactor: nil,
                level: "Materials",
                sourceURL: "https://example.org/no-if"
            ),
            JournalCatalogEntry(
                rank: 3,
                journal: "High IF Journal",
                aliases: [],
                impactFactor: 60.1,
                impactFactorYear: 2024,
                fiveYearImpactFactor: nil,
                level: "Energy",
                sourceURL: "https://example.org/high"
            ),
            JournalCatalogEntry(
                rank: 4,
                journal: "Middle IF Journal",
                aliases: [],
                impactFactor: 29.4,
                impactFactorYear: 2025,
                fiveYearImpactFactor: nil,
                level: "Materials",
                sourceURL: "https://example.org/middle"
            ),
        ])
        let controller = JournalFilterViewController(settings: settings, catalog: catalog) { _ in true }

        XCTAssertEqual(
            controller.visibleJournalNamesForTesting,
            ["High IF Journal", "Middle IF Journal", "Low IF Journal", "No IF Journal"]
        )
    }

    func testRefreshSchedulePolicyOnlyReschedulesWhenIntervalChanges() {
        XCTAssertTrue(RefreshSchedulePolicy.shouldReschedule(lastScheduledInterval: nil, settingsIntervalSeconds: 3600))
        XCTAssertFalse(RefreshSchedulePolicy.shouldReschedule(lastScheduledInterval: 3600, settingsIntervalSeconds: 3600))
        XCTAssertTrue(RefreshSchedulePolicy.shouldReschedule(lastScheduledInterval: 3600, settingsIntervalSeconds: 7200))
    }

    @MainActor
    func testDebouncedSettingsChangeCoalescesQuerySaves() {
        final class TestToken: SearchSettingsDebounceToken {
            var cancelCount = 0
            func cancel() {
                cancelCount += 1
            }
        }

        var scheduled: [(delay: TimeInterval, action: @MainActor () -> Void, token: TestToken)] = []
        var emitted: [AppSettings] = []
        let debouncer = SearchSettingsChangeDebouncer(
            delay: 0.6,
            scheduler: { delay, action in
                let token = TestToken()
                scheduled.append((delay, action, token))
                return token
            },
            onChange: { settings in
                emitted.append(settings)
                return true
            }
        )
        var first = AppSettings.default
        first.searchDirection.crossrefQuery = "first"
        var second = AppSettings.default
        second.searchDirection.crossrefQuery = "second"

        debouncer.schedule(first)
        debouncer.schedule(second)
        scheduled[0].action()
        scheduled[1].action()

        XCTAssertEqual(scheduled.map(\.delay), [0.6, 0.6])
        XCTAssertEqual(scheduled[0].token.cancelCount, 1)
        XCTAssertEqual(emitted.map(\.searchDirection.crossrefQuery), ["second"])
    }

    @MainActor
    func testDebouncedSettingsChangeFlushEmitsLatestPendingSettingsOnce() {
        final class TestToken: SearchSettingsDebounceToken {
            var cancelCount = 0
            func cancel() {
                cancelCount += 1
            }
        }

        var scheduled: [(action: @MainActor () -> Void, token: TestToken)] = []
        var emitted: [AppSettings] = []
        let debouncer = SearchSettingsChangeDebouncer(
            scheduler: { _, action in
                let token = TestToken()
                scheduled.append((action, token))
                return token
            },
            onChange: { settings in
                emitted.append(settings)
                return true
            }
        )
        var first = AppSettings.default
        first.searchDirection.crossrefQuery = "first"
        var second = AppSettings.default
        second.searchDirection.crossrefQuery = "second"

        debouncer.schedule(first)
        debouncer.schedule(second)
        debouncer.flushPending()
        scheduled[1].action()

        XCTAssertEqual(scheduled[1].token.cancelCount, 1)
        XCTAssertEqual(emitted.map(\.searchDirection.crossrefQuery), ["second"])
    }

    @MainActor
    func testDebouncedSettingsChangeTimerReadsLatestSettingsAtFireTime() {
        final class TestToken: SearchSettingsDebounceToken {
            func cancel() {}
        }

        var scheduled: [@MainActor () -> Void] = []
        var emitted: [AppSettings] = []
        let debouncer = SearchSettingsChangeDebouncer(
            scheduler: { _, action in
                scheduled.append(action)
                return TestToken()
            },
            onChange: { settings in
                emitted.append(settings)
                return true
            }
        )
        let editingState = SettingsEditingState(settings: .default)
        editingState.settings.searchDirection.crossrefQuery = "pending crossref"

        debouncer.scheduleLatest { [editingState] in editingState.settings }
        editingState.settings.includeTerms = ["solid electrolyte", "LLZO"]

        scheduled[0]()

        let saved = emitted.last
        XCTAssertEqual(saved?.searchDirection.crossrefQuery, "pending crossref")
        XCTAssertEqual(saved?.includeTerms, ["solid electrolyte", "LLZO"])
    }

    @MainActor
    func testDebouncedSettingsChangeFailedFlushKeepsPendingSettingsForRetry() {
        final class TestToken: SearchSettingsDebounceToken {
            var cancelCount = 0
            func cancel() {
                cancelCount += 1
            }
        }

        var attempts = 0
        var emitted: [AppSettings] = []
        let debouncer = SearchSettingsChangeDebouncer(
            scheduler: { _, _ in TestToken() },
            onChange: { settings in
                attempts += 1
                emitted.append(settings)
                return attempts > 1
            }
        )
        var settings = AppSettings.default
        settings.searchDirection.crossrefQuery = "pending"

        debouncer.schedule(settings)

        XCTAssertFalse(debouncer.flushPending())
        XCTAssertTrue(debouncer.flushPending())
        XCTAssertEqual(emitted.map(\.searchDirection.crossrefQuery), ["pending", "pending"])
    }

    @MainActor
    func testSettingsWindowFlushPendingChangesEmitsSearchTabQueryEdit() throws {
        var emitted: [AppSettings] = []
        let controller = SettingsWindowController(settings: .default, journalCatalog: nil) { settings in
            emitted.append(settings)
            return true
        }
        let window = try XCTUnwrap(controller.window)
        let tabViewController = try XCTUnwrap(window.contentViewController as? NSTabViewController)
        let searchController = try XCTUnwrap(tabViewController.tabViewItems.first?.viewController as? SearchSettingsViewController)

        searchController.updateQueries(crossrefQuery: "pending crossref", openalexQuery: "pending openalex", debounced: true)
        XCTAssertTrue(emitted.isEmpty)

        controller.flushPendingChanges()

        XCTAssertEqual(emitted.map(\.searchDirection.crossrefQuery), ["pending crossref"])
    }

    @MainActor
    func testSettingsWindowFlushPendingChangesEmitsSearchTermsEdit() throws {
        var emitted: [AppSettings] = []
        let controller = SettingsWindowController(settings: .default, journalCatalog: nil) { settings in
            emitted.append(settings)
            return true
        }
        let window = try XCTUnwrap(controller.window)
        let tabViewController = try XCTUnwrap(window.contentViewController as? NSTabViewController)
        let termsController = try XCTUnwrap(tabViewController.tabViewItems[1].viewController as? SearchTermsViewController)

        termsController.updateTerms(
            includeTerms: ["solid electrolyte", "solid electrolyte", "LLZO"],
            excludeTerms: ["solid-state laser", "", "solid-state laser"],
            debounced: true
        )
        XCTAssertTrue(emitted.isEmpty)

        controller.flushPendingChanges()

        XCTAssertEqual(emitted.map(\.includeTerms), [["solid electrolyte", "LLZO"]])
        XCTAssertEqual(emitted.map(\.excludeTerms), [["solid-state laser"]])
    }

    @MainActor
    func testSettingsWindowFlushPendingChangesMergesSearchSettingsAndTermsEdits() throws {
        var emitted: [AppSettings] = []
        let controller = SettingsWindowController(settings: .default, journalCatalog: nil) { settings in
            emitted.append(settings)
            return true
        }
        let window = try XCTUnwrap(controller.window)
        let tabViewController = try XCTUnwrap(window.contentViewController as? NSTabViewController)
        let searchController = try XCTUnwrap(tabViewController.tabViewItems[0].viewController as? SearchSettingsViewController)
        let termsController = try XCTUnwrap(tabViewController.tabViewItems[1].viewController as? SearchTermsViewController)

        searchController.updateQueries(
            crossrefQuery: "pending crossref",
            openalexQuery: "pending openalex",
            debounced: true
        )
        termsController.updateTerms(
            includeTerms: ["solid electrolyte", "LLZO"],
            excludeTerms: ["solid-state laser"],
            debounced: true
        )

        controller.flushPendingChanges()

        let saved = try XCTUnwrap(emitted.last)
        XCTAssertEqual(saved.searchDirection.crossrefQuery, "pending crossref")
        XCTAssertEqual(saved.searchDirection.openalexQuery, "pending openalex")
        XCTAssertEqual(saved.includeTerms, ["solid electrolyte", "LLZO"])
        XCTAssertEqual(saved.excludeTerms, ["solid-state laser"])
    }

    @MainActor
    func testSettingsWindowFlushesSharedPendingEditsOnce() throws {
        var emitted: [AppSettings] = []
        let controller = SettingsWindowController(settings: .default, journalCatalog: nil) { settings in
            emitted.append(settings)
            return true
        }
        let window = try XCTUnwrap(controller.window)
        let tabViewController = try XCTUnwrap(window.contentViewController as? NSTabViewController)
        let searchController = try XCTUnwrap(tabViewController.tabViewItems[0].viewController as? SearchSettingsViewController)
        let termsController = try XCTUnwrap(tabViewController.tabViewItems[1].viewController as? SearchTermsViewController)

        searchController.updateQueries(
            crossrefQuery: "pending crossref",
            openalexQuery: "pending openalex",
            debounced: true
        )
        termsController.updateTerms(
            includeTerms: ["solid electrolyte", "LLZO"],
            excludeTerms: ["solid-state laser"],
            debounced: true
        )

        XCTAssertTrue(controller.flushPendingChanges())

        XCTAssertEqual(emitted.count, 1)
        let saved = try XCTUnwrap(emitted.last)
        XCTAssertEqual(saved.searchDirection.crossrefQuery, "pending crossref")
        XCTAssertEqual(saved.searchDirection.openalexQuery, "pending openalex")
        XCTAssertEqual(saved.includeTerms, ["solid electrolyte", "LLZO"])
        XCTAssertEqual(saved.excludeTerms, ["solid-state laser"])
    }

    @MainActor
    func testSearchSettingsDebounceTimerSavesLatestSharedTermsEdit() throws {
        final class TestToken: SearchSettingsDebounceToken {
            func cancel() {}
        }

        let editingState = SettingsEditingState(settings: .default)
        var scheduled: [@MainActor () -> Void] = []
        var emitted: [AppSettings] = []
        let searchController = SearchSettingsViewController(
            editingState: editingState,
            journalCatalog: nil,
            debounceScheduler: { _, action in
                scheduled.append(action)
                return TestToken()
            },
            onChange: { settings in
                emitted.append(settings)
                return true
            }
        )
        let termsController = SearchTermsViewController(editingState: editingState) { settings in
            emitted.append(settings)
            return true
        }

        searchController.updateQueries(
            crossrefQuery: "pending crossref",
            openalexQuery: "pending openalex",
            debounced: true
        )
        termsController.updateTerms(
            includeTerms: ["solid electrolyte", "LLZO"],
            excludeTerms: ["solid-state laser"],
            debounced: false
        )

        scheduled[0]()

        let saved = try XCTUnwrap(emitted.last)
        XCTAssertEqual(saved.searchDirection.crossrefQuery, "pending crossref")
        XCTAssertEqual(saved.searchDirection.openalexQuery, "pending openalex")
        XCTAssertEqual(saved.includeTerms, ["solid electrolyte", "LLZO"])
        XCTAssertEqual(saved.excludeTerms, ["solid-state laser"])
    }

    @MainActor
    func testSearchTermsReloadsAfterSearchSettingsPresetBeforeTermsEdit() throws {
        var emitted: [AppSettings] = []
        let controller = SettingsWindowController(settings: .default, journalCatalog: nil) { settings in
            emitted.append(settings)
            return true
        }
        let window = try XCTUnwrap(controller.window)
        let tabViewController = try XCTUnwrap(window.contentViewController as? NSTabViewController)
        let searchController = try XCTUnwrap(tabViewController.tabViewItems[0].viewController as? SearchSettingsViewController)
        let termsController = try XCTUnwrap(tabViewController.tabViewItems[1].viewController as? SearchTermsViewController)

        searchController.loadView()
        termsController.loadView()
        searchController.applyPresetForTesting(.solidElectrolyte)

        termsController.appendIncludeTermForTesting("argyrodite", debounced: false)

        let saved = try XCTUnwrap(emitted.last)
        XCTAssertEqual(
            saved.includeTerms,
            SearchPreset.solidElectrolyte.includeTerms + ["argyrodite"]
        )
        XCTAssertEqual(saved.excludeTerms, SearchPreset.solidElectrolyte.excludeTerms)
    }

    @MainActor
    func testSearchSettingsReloadsQueriesAfterTermsEditBeforeSingleQueryEdit() throws {
        var emitted: [AppSettings] = []
        let controller = SettingsWindowController(settings: .default, journalCatalog: nil) { settings in
            emitted.append(settings)
            return true
        }
        let window = try XCTUnwrap(controller.window)
        let tabViewController = try XCTUnwrap(window.contentViewController as? NSTabViewController)
        let searchController = try XCTUnwrap(tabViewController.tabViewItems[0].viewController as? SearchSettingsViewController)
        let termsController = try XCTUnwrap(tabViewController.tabViewItems[1].viewController as? SearchTermsViewController)

        searchController.loadView()
        termsController.loadView()
        termsController.updateTerms(
            includeTerms: ["solid electrolyte", "LLZO"],
            excludeTerms: [],
            debounced: false
        )

        searchController.editCrossrefQueryForTesting("custom crossref", debounced: false)

        let saved = try XCTUnwrap(emitted.last)
        XCTAssertEqual(saved.searchDirection.crossrefQuery, "custom crossref")
        XCTAssertEqual(saved.searchDirection.openalexQuery, "solid electrolyte LLZO")
    }

    @MainActor
    func testSearchSettingsTopNReloadsJournalFilterSelection() throws {
        var settings = AppSettings.default
        settings.journalScope = JournalScope(topN: 1, selectedJournals: ["Nature"])
        let catalog = makeJournalCatalog(["Nature", "Science", "Cell"])
        let controller = SettingsWindowController(settings: settings, journalCatalog: catalog) { _ in true }
        let window = try XCTUnwrap(controller.window)
        let tabViewController = try XCTUnwrap(window.contentViewController as? NSTabViewController)
        let searchController = try XCTUnwrap(tabViewController.tabViewItems[0].viewController as? SearchSettingsViewController)
        let journalController = try XCTUnwrap(tabViewController.tabViewItems[2].viewController as? JournalFilterViewController)

        searchController.loadView()
        journalController.loadView()
        searchController.applyTopNForTesting(2)

        XCTAssertEqual(journalController.selectedJournalNamesForTesting, ["Nature", "Science"])
        XCTAssertEqual(journalController.selectedCountForTesting, 2)
    }

    @MainActor
    func testJournalFilterTopNReloadsSearchSettingsScope() throws {
        var settings = AppSettings.default
        settings.journalScope = JournalScope(topN: 1, selectedJournals: ["Nature"])
        let catalog = makeJournalCatalog(["Nature", "Science", "Cell"])
        let controller = SettingsWindowController(settings: settings, journalCatalog: catalog) { _ in true }
        let window = try XCTUnwrap(controller.window)
        let tabViewController = try XCTUnwrap(window.contentViewController as? NSTabViewController)
        let searchController = try XCTUnwrap(tabViewController.tabViewItems[0].viewController as? SearchSettingsViewController)
        let journalController = try XCTUnwrap(tabViewController.tabViewItems[2].viewController as? JournalFilterViewController)

        searchController.loadView()
        journalController.loadView()
        journalController.applyTopNForTesting(3)

        XCTAssertEqual(searchController.topNValueForTesting, 3)
    }

    @MainActor
    func testSearchTermsFailedFlushKeepsWindowOpenForRetry() throws {
        var attempts = 0
        let controller = SettingsWindowController(settings: .default, journalCatalog: nil) { _ in
            attempts += 1
            return attempts > 1
        }
        let window = try XCTUnwrap(controller.window)
        let tabViewController = try XCTUnwrap(window.contentViewController as? NSTabViewController)
        let termsController = try XCTUnwrap(tabViewController.tabViewItems[1].viewController as? SearchTermsViewController)

        termsController.updateTerms(includeTerms: ["LLZO"], excludeTerms: [], debounced: true)

        XCTAssertFalse(controller.windowShouldClose(window))
        XCTAssertTrue(controller.windowShouldClose(window))
    }

    @MainActor
    func testSettingsWindowShouldNotCloseWhenPendingFlushFails() throws {
        let controller = SettingsWindowController(settings: .default, journalCatalog: nil) { _ in false }
        let window = try XCTUnwrap(controller.window)
        let tabViewController = try XCTUnwrap(window.contentViewController as? NSTabViewController)
        let searchController = try XCTUnwrap(tabViewController.tabViewItems.first?.viewController as? SearchSettingsViewController)

        searchController.updateQueries(crossrefQuery: "pending", openalexQuery: "pending", debounced: true)

        XCTAssertFalse(controller.windowShouldClose(window))
    }

    @MainActor
    func testSearchSettingsShowsCustomPresetForUnsupportedPreset() throws {
        var settings = AppSettings.default
        settings.searchDirection.preset = "custom_direction"
        settings.searchDirection.label = "My direction"
        let controller = SearchSettingsViewController(settings: settings, journalCatalog: nil) { _ in true }

        controller.loadView()

        XCTAssertEqual(controller.selectedPresetTitleForTesting, "Custom: My direction")
    }

    func testWindowSettingsFallbackSeedsSelectedJournalsFromCatalog() {
        var loaded = AppSettings.default
        loaded.journalScope = JournalScope(topN: 2, selectedJournals: [])
        let catalog = makeJournalCatalog(["Nature", "Science", "Cell"])

        let settings = SearchSettingsPolicy.windowSettings(loaded: loaded, catalog: catalog)

        XCTAssertEqual(settings.journalScope.selectedJournals, ["Nature", "Science"])
    }

    func testSettingsEditorLoadPolicyPropagatesLoadErrors() {
        enum TestError: Error {
            case corruptConfig
        }

        XCTAssertThrowsError(try SettingsEditorLoadPolicy.settingsForEditor(
            load: { throw TestError.corruptConfig },
            catalog: makeJournalCatalog(["Nature"])
        ))
    }

    func testSettingsEditorLoadPolicyRejectsEmptySelectedJournalsWithoutCatalog() {
        var loaded = AppSettings.default
        loaded.journalScope = JournalScope(topN: 2, selectedJournals: [])

        XCTAssertThrowsError(try SettingsEditorLoadPolicy.settingsForEditor(
            load: { loaded },
            catalog: nil
        ))
        XCTAssertThrowsError(try SettingsEditorLoadPolicy.settingsForEditor(
            load: { loaded },
            catalog: JournalCatalog(entries: [])
        ))
    }

    func testJournalCatalogLoadsRankedTopFiftyMetadata() throws {
        let directory = try makeTemporaryDirectory()
        let metricsURL = directory.appendingPathComponent("journal_metrics.json")
        let entries = (1...50).reversed().map { rank in
            """
            {
              "rank": \(rank),
              "journal": "Journal \(rank)",
              "aliases": ["J\(rank)"],
              "impact_factor": \(Double(rank)),
              "impact_factor_year": 2025,
              "five_year_impact_factor": null,
              "level": "Test journal",
              "source_url": "https://example.org/\(rank)"
            }
            """
        }.joined(separator: ",")
        try #"{"journals":[\#(entries)]}"#.write(to: metricsURL, atomically: true, encoding: .utf8)

        let catalog = try JournalCatalog.load(from: metricsURL)

        XCTAssertEqual(catalog.entries.count, 50)
        XCTAssertEqual(catalog.entries.map(\.rank), Array(1...50))
        XCTAssertEqual(catalog.entries.first?.rank, 1)
        XCTAssertEqual(catalog.entries.last?.journal, "Journal 50")
        XCTAssertEqual(catalog.entriesByImpactFactor.prefix(3).map(\.journal), ["Journal 50", "Journal 49", "Journal 48"])
        XCTAssertEqual(catalog.topJournals(3).map(\.journal), ["Journal 50", "Journal 49", "Journal 48"])
        XCTAssertEqual(catalog.topJournals(999).count, 50)
        XCTAssertEqual(catalog.topJournals(0).count, 1)
    }

    func testSettingsStoreFallsBackToSourceQueriesWhenSearchDirectionQueriesAreMissing() throws {
        let directory = try makeTemporaryDirectory()
        let configURL = directory.appendingPathComponent("config.json")
        try """
        {
          "search_direction": {
            "preset": "custom",
            "label": "Custom",
            "crossref_query": "",
            "query_manually_edited": false
          },
          "sources": {
            "crossref": {"enabled": true, "query": "source crossref query"},
            "openalex": {"enabled": true, "query": "source openalex query"}
          }
        }
        """.write(to: configURL, atomically: true, encoding: .utf8)

        let settings = try SettingsStore(configURL: configURL).load()

        XCTAssertEqual(settings.searchDirection.crossrefQuery, "source crossref query")
        XCTAssertEqual(settings.searchDirection.openalexQuery, "source openalex query")
    }

    func testSettingsStoreWritesRuntimeFieldsAtomically() throws {
        let directory = try makeTemporaryDirectory()
        let configURL = directory.appendingPathComponent("config.json")
        try #"{"sources":{"crossref":{"enabled":true},"openalex":{"enabled":false}}}"#
            .write(to: configURL, atomically: true, encoding: .utf8)
        let store = SettingsStore(configURL: configURL)
        var settings = AppSettings.default
        settings.journalScope = JournalScope(topN: 2, selectedJournals: ["Nature", "Science"])
        settings.intervalSeconds = 7200
        settings.includeTerms = ["solid electrolyte", "", "solid electrolyte", "LLZO"]
        settings.excludeTerms = ["solid-state laser", "", "solid-state laser"]
        settings.searchDirection.preset = "solid_electrolyte"
        settings.searchDirection.label = "Solid electrolyte"
        settings.searchDirection.crossrefQuery = "solid electrolyte"
        settings.searchDirection.openalexQuery = "solid electrolyte LLZO"
        settings.searchDirection.queryManuallyEdited = true

        try store.save(settings)

        let data = try Data(contentsOf: configURL)
        let payload = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(payload?["interval_seconds"] as? Int, 7200)
        XCTAssertEqual(payload?["include_terms"] as? [String], ["solid electrolyte", "LLZO"])
        XCTAssertEqual(payload?["exclude_terms"] as? [String], ["solid-state laser"])
        XCTAssertEqual(payload?["journals"] as? [String], ["Nature", "Science"])
        let journalScope = payload?["journal_scope"] as? [String: Any]
        XCTAssertEqual(journalScope?["top_n"] as? Int, 2)
        XCTAssertEqual(journalScope?["selected_journals"] as? [String], ["Nature", "Science"])
        let searchDirection = payload?["search_direction"] as? [String: Any]
        XCTAssertEqual(searchDirection?["preset"] as? String, "solid_electrolyte")
        XCTAssertEqual(searchDirection?["label"] as? String, "Solid electrolyte")
        XCTAssertEqual(searchDirection?["crossref_query"] as? String, "solid electrolyte")
        XCTAssertEqual(searchDirection?["openalex_query"] as? String, "solid electrolyte LLZO")
        XCTAssertEqual(searchDirection?["query_manually_edited"] as? Bool, true)
        let sources = payload?["sources"] as? [String: Any]
        let crossref = sources?["crossref"] as? [String: Any]
        XCTAssertEqual(crossref?["journal_titles"] as? [String], ["Nature", "Science"])
        XCTAssertEqual(crossref?["query"] as? String, "solid electrolyte")
        let openalex = sources?["openalex"] as? [String: Any]
        XCTAssertEqual(openalex?["query"] as? String, "solid electrolyte LLZO")
    }

    func testSettingsStoreTopNFallsBackToSelectedJournalCount() throws {
        let directory = try makeTemporaryDirectory()
        let configURL = directory.appendingPathComponent("config.json")
        try """
        {
          "journal_scope": {
            "selected_journals": ["Nature Energy", "", "Advanced Materials"]
          }
        }
        """.write(to: configURL, atomically: true, encoding: .utf8)

        let settings = try SettingsStore(configURL: configURL).load()

        XCTAssertEqual(settings.journalScope.selectedJournals, ["Nature Energy", "Advanced Materials"])
        XCTAssertEqual(settings.journalScope.topN, 2)
    }

    func testSettingsStoreRejectsInvalidTopNTypes() throws {
        let directory = try makeTemporaryDirectory()
        let booleanConfigURL = directory.appendingPathComponent("boolean-config.json")
        try """
        {
          "journal_scope": {
            "top_n": true,
            "selected_journals": ["Nature", "Science"]
          }
        }
        """.write(to: booleanConfigURL, atomically: true, encoding: .utf8)
        let fractionalConfigURL = directory.appendingPathComponent("fractional-config.json")
        try """
        {
          "journal_scope": {
            "top_n": 4.5,
            "selected_journals": ["Nature", "Science", "Cell"]
          }
        }
        """.write(to: fractionalConfigURL, atomically: true, encoding: .utf8)

        XCTAssertEqual(try SettingsStore(configURL: booleanConfigURL).load().journalScope.topN, 2)
        XCTAssertEqual(try SettingsStore(configURL: fractionalConfigURL).load().journalScope.topN, 3)
    }

    func testSettingsStoreRejectsInvalidIntervalWithoutWriting() throws {
        let directory = try makeTemporaryDirectory()
        let configURL = directory.appendingPathComponent("config.json")
        let originalJSON = #"{"interval_seconds":7200,"sources":{"crossref":{"enabled":true}}}"#
        try originalJSON.write(to: configURL, atomically: true, encoding: .utf8)
        var settings = AppSettings.default
        settings.journalScope = JournalScope(topN: 1, selectedJournals: ["Nature"])
        settings.intervalSeconds = 0

        XCTAssertThrowsError(try SettingsStore(configURL: configURL).save(settings)) { error in
            XCTAssertEqual(error as? SettingsStoreError, .invalidInterval)
        }

        let payload = try JSONSerialization.jsonObject(with: Data(contentsOf: configURL)) as? [String: Any]
        XCTAssertEqual(payload?["interval_seconds"] as? Int, 7200)
        XCTAssertNil(payload?["journals"])
    }

    func testSettingsStorePreservesUnrelatedRootAndNestedSourceKeys() throws {
        let directory = try makeTemporaryDirectory()
        let configURL = directory.appendingPathComponent("config.json")
        try """
        {
          "unrelated_root": "preserve me",
          "sources": {
            "rss": [{"url": "https://example.org/feed.xml"}],
            "crossref": {"enabled": true, "mailto": "alerts@example.org"},
            "openalex": {"enabled": true, "api_key": "secret", "query": "old query"}
          }
        }
        """.write(to: configURL, atomically: true, encoding: .utf8)
        var settings = AppSettings.default
        settings.journalScope = JournalScope(topN: 2, selectedJournals: ["Nature", "Science"])
        settings.searchDirection.crossrefQuery = "solid electrolyte"
        settings.searchDirection.openalexQuery = "solid electrolyte LLZO"

        try SettingsStore(configURL: configURL).save(settings)

        let payload = try JSONSerialization.jsonObject(with: Data(contentsOf: configURL)) as? [String: Any]
        XCTAssertEqual(payload?["unrelated_root"] as? String, "preserve me")
        let sources = payload?["sources"] as? [String: Any]
        let rss = sources?["rss"] as? [[String: Any]]
        XCTAssertEqual(rss?.first?["url"] as? String, "https://example.org/feed.xml")
        let crossref = sources?["crossref"] as? [String: Any]
        XCTAssertEqual(crossref?["mailto"] as? String, "alerts@example.org")
        XCTAssertEqual(crossref?["query"] as? String, "solid electrolyte")
        let openalex = sources?["openalex"] as? [String: Any]
        XCTAssertEqual(openalex?["api_key"] as? String, "secret")
        XCTAssertEqual(openalex?["query"] as? String, "solid electrolyte LLZO")
    }

    func testSettingsStoreRejectsEmptySelectedJournals() throws {
        let directory = try makeTemporaryDirectory()
        let configURL = directory.appendingPathComponent("config.json")
        try #"{"interval_seconds":7200}"#.write(to: configURL, atomically: true, encoding: .utf8)
        var settings = AppSettings.default
        settings.journalScope = JournalScope(topN: 1, selectedJournals: ["", "   "])

        XCTAssertThrowsError(try SettingsStore(configURL: configURL).save(settings)) { error in
            XCTAssertEqual(error as? SettingsStoreError, .noSelectedJournals)
        }

        let payload = try JSONSerialization.jsonObject(with: Data(contentsOf: configURL)) as? [String: Any]
        XCTAssertNil(payload?["journals"])
    }

    func testSettingsStoreSavesWhenConfigFileIsMissing() throws {
        let directory = try makeTemporaryDirectory()
        let configURL = directory.appendingPathComponent("nested/config.json")
        var settings = AppSettings.default
        settings.journalScope = JournalScope(topN: 1, selectedJournals: ["Nature"])
        settings.searchDirection.crossrefQuery = "solid electrolyte"
        settings.searchDirection.openalexQuery = "solid electrolyte"

        try SettingsStore(configURL: configURL).save(settings)

        let payload = try JSONSerialization.jsonObject(with: Data(contentsOf: configURL)) as? [String: Any]
        XCTAssertEqual(payload?["journals"] as? [String], ["Nature"])
        XCTAssertEqual(payload?["interval_seconds"] as? Int, AppSettings.default.intervalSeconds)
    }

    private func makeDashboardCommandConfigURL(queryManuallyEdited: Bool = false) throws -> URL {
        let directory = try makeTemporaryDirectory()
        let configURL = directory.appendingPathComponent("config.json")
        let crossrefQuery = queryManuallyEdited ? "manual crossref query" : "solid electrolyte"
        let openalexQuery = queryManuallyEdited ? "manual openalex query" : "solid electrolyte"
        try """
        {
          "settings_schema_version": 1,
          "journal_scope": {
            "top_n": 1,
            "selected_journals": ["Nature Energy"]
          },
          "interval_seconds": 3600,
          "include_terms": ["solid electrolyte"],
          "exclude_terms": [],
          "search_direction": {
            "preset": "solid_state_battery_general",
            "label": "Solid-state battery general",
            "crossref_query": "\(crossrefQuery)",
            "openalex_query": "\(openalexQuery)",
            "query_manually_edited": \(queryManuallyEdited)
          },
          "sources": {
            "crossref": {"journal_titles": [], "query": ""},
            "openalex": {"query": ""}
          }
        }
        """.write(to: configURL, atomically: true, encoding: .utf8)
        return configURL
    }

    private func makeTemporaryDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    private func makeTestPNGData() throws -> Data {
        try XCTUnwrap(Data(base64Encoded: """
        iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAHUlEQVR4nGNkYGD4z0ABYKJE86gBowaMGjCYDAAATUABH+w/WFYAAAAASUVORK5CYII=
        """))
    }

    private func makeJournalCatalog(_ journals: [String]) -> JournalCatalog {
        JournalCatalog(entries: journals.enumerated().map { index, journal in
            JournalCatalogEntry(
                rank: index + 1,
                journal: journal,
                aliases: [],
                impactFactor: nil,
                impactFactorYear: nil,
                fiveYearImpactFactor: nil,
                level: "Test",
                sourceURL: "https://example.org"
            )
        })
    }

    @MainActor
    private func findTableView(in root: NSView) -> NSTableView? {
        if let tableView = root as? NSTableView {
            return tableView
        }
        for subview in root.subviews {
            if let tableView = findTableView(in: subview) {
                return tableView
            }
        }
        return nil
    }
}

private enum TestNotificationError: LocalizedError {
    case rejected

    var errorDescription: String? {
        "rejected"
    }
}

private final class NotificationTestRecorder: @unchecked Sendable {
    var capturedRequest: UNNotificationRequest?
    var loggedMessage: String?
}

private final class LockedCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var value = 0

    func increment() -> Int {
        lock.lock()
        defer { lock.unlock() }
        value += 1
        return value
    }

    var current: Int {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}

private func containsHan(_ value: String) -> Bool {
    value.unicodeScalars.contains { scalar in
        (0x4E00...0x9FFF).contains(Int(scalar.value))
    }
}

private final class TestRefreshTimer: RefreshSchedulerTimer, @unchecked Sendable {
    let interval: TimeInterval
    let handler: @MainActor () -> Void
    private(set) var invalidateCount = 0

    init(interval: TimeInterval, handler: @escaping @MainActor () -> Void) {
        self.interval = interval
        self.handler = handler
    }

    func invalidate() {
        invalidateCount += 1
    }
}
