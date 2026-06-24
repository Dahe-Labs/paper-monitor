import AppKit
import Foundation
@preconcurrency import UserNotifications

public final class NotificationController: NSObject, UNUserNotificationCenterDelegate {
    public static let paperCategoryIdentifier = "paper"
    public static let openDashboardActionIdentifier = "openDashboard"
    public static let foregroundPresentationOptions: UNNotificationPresentationOptions = [.banner, .list, .sound]
    public typealias NotificationRequestAdder = (UNNotificationRequest, @escaping @Sendable (Error?) -> Void) -> Void
    public typealias NotificationErrorLogger = @Sendable (String) -> Void

    private let notificationCenter: UNUserNotificationCenter?
    private let workspace: NSWorkspace
    private let addRequest: NotificationRequestAdder
    private let notificationErrorLogger: NotificationErrorLogger

    public init(
        notificationCenter: UNUserNotificationCenter = .current(),
        workspace: NSWorkspace = .shared,
        notificationErrorLogger: @escaping NotificationErrorLogger = { message in
            NSLog("%@", message)
        }
    ) {
        self.notificationCenter = notificationCenter
        self.workspace = workspace
        self.addRequest = { request, completion in
            notificationCenter.add(request, withCompletionHandler: completion)
        }
        self.notificationErrorLogger = notificationErrorLogger
        super.init()
        notificationCenter.delegate = self
        configureCategories()
    }

    init(
        workspace: NSWorkspace = .shared,
        addRequest: @escaping NotificationRequestAdder,
        notificationErrorLogger: @escaping NotificationErrorLogger
    ) {
        self.notificationCenter = nil
        self.workspace = workspace
        self.addRequest = addRequest
        self.notificationErrorLogger = notificationErrorLogger
        super.init()
    }

    public func requestAuthorization(completion: (@Sendable (UNAuthorizationStatus) -> Void)? = nil) {
        guard let notificationCenter else {
            completion?(.notDetermined)
            return
        }
        notificationCenter.requestAuthorization(options: [.alert, .sound, .badge]) { [notificationCenter] _, _ in
            notificationCenter.getNotificationSettings { settings in
                completion?(settings.authorizationStatus)
            }
        }
    }

    public func configureCategories() {
        guard let notificationCenter else {
            return
        }
        let openDashboard = UNNotificationAction(
            identifier: Self.openDashboardActionIdentifier,
            title: "Open Dashboard",
            options: [.foreground]
        )
        let category = UNNotificationCategory(
            identifier: Self.paperCategoryIdentifier,
            actions: [openDashboard],
            intentIdentifiers: [],
            options: []
        )
        notificationCenter.setNotificationCategories([category])
    }

    public func post(article: ArticleNotification, dashboardURL: URL) {
        let content = UNMutableNotificationContent()
        content.title = article.title
        content.subtitle = article.journal
        content.body = article.doi.isEmpty ? article.url : article.doi
        content.sound = .default
        content.categoryIdentifier = Self.paperCategoryIdentifier
        content.userInfo = [
            "article_url": Self.articleTarget(for: article).absoluteString,
            "dashboard_url": dashboardURL.absoluteString,
        ]

        let request = UNNotificationRequest(
            identifier: UUID().uuidString,
            content: content,
            trigger: nil
        )
        addRequest(request) { [notificationErrorLogger] error in
            if let error {
                notificationErrorLogger("Paper Monitor notification failed: \(error.localizedDescription)")
            }
        }
    }

    public static func testArticle() -> ArticleNotification {
        ArticleNotification(
            title: AppIdentity.testNotificationTitle,
            journal: "Notification Test",
            url: AppIdentity.testNotificationURL,
            doi: "",
            published: "",
            source: "local",
            matchedTerms: ["test"],
            journalMatch: "Notification Test"
        )
    }

    public static func articleTarget(for article: ArticleNotification) -> URL {
        if let url = URL(string: article.url), ["http", "https"].contains(url.scheme?.lowercased()) {
            return url
        }
        if !article.doi.isEmpty, let doiURL = URL(string: "https://doi.org/\(article.doi)") {
            return doiURL
        }
        return URL(string: "https://example.org")!
    }

    public func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler(Self.foregroundPresentationOptions)
    }

    public func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let userInfo = response.notification.request.content.userInfo
        if response.actionIdentifier == Self.openDashboardActionIdentifier,
           let dashboardString = userInfo["dashboard_url"] as? String,
           let dashboard = URL(string: dashboardString) {
            workspace.open(dashboard)
        } else if let articleString = userInfo["article_url"] as? String,
                  let articleURL = URL(string: articleString) {
            workspace.open(articleURL)
        }
        completionHandler()
    }
}
