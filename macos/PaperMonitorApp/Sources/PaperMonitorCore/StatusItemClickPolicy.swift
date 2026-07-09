import AppKit

enum StatusItemClickAction: Equatable {
    case openDashboard
    case showMenu
}

enum StatusItemClickPolicy {
    static func action(for eventType: NSEvent.EventType?, clickCount _: Int) -> StatusItemClickAction {
        switch eventType {
        case .rightMouseDown, .rightMouseUp:
            return .showMenu
        default:
            return .openDashboard
        }
    }
}
