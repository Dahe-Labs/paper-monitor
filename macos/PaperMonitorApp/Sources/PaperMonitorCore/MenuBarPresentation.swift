import AppKit
import Foundation

public struct MenuBarPresentation: Equatable, Sendable {
    public let length: CGFloat
    public let title: String
    public let toolTip: String
    public let iconName: String
    public let isTemplate: Bool
    public let iconPointSize: CGFloat

    public static let `default` = MenuBarPresentation(
        length: NSStatusItem.squareLength,
        title: "",
        toolTip: AppIdentity.displayName,
        iconName: "MenuBarIcon",
        isTemplate: true,
        iconPointSize: 20
    )
}
