import AppKit
import Foundation

public struct MenuBarIconLoader {
    private let bundle: Bundle

    public init(bundle: Bundle = .main) {
        self.bundle = bundle
    }

    public func image(for presentation: MenuBarPresentation) -> NSImage? {
        guard !presentation.iconName.isEmpty else {
            return nil
        }

        let image = bundledPNG(named: presentation.iconName)
            ?? NSImage(named: presentation.iconName)
            ?? fallbackIcon(accessibilityDescription: presentation.toolTip, pointSize: presentation.iconPointSize)
        image.isTemplate = presentation.isTemplate
        image.size = NSSize(width: presentation.iconPointSize, height: presentation.iconPointSize)
        return image
    }

    private func bundledPNG(named name: String) -> NSImage? {
        guard let url = bundle.url(forResource: name, withExtension: "png") else {
            return nil
        }
        return NSImage(contentsOf: url)
    }

    private func fallbackIcon(accessibilityDescription: String, pointSize: CGFloat) -> NSImage {
        if let symbol = NSImage(
            systemSymbolName: "bolt.horizontal.circle",
            accessibilityDescription: accessibilityDescription
        ) {
            return symbol
        }

        let image = NSImage(size: NSSize(width: pointSize, height: pointSize))
        image.lockFocus()
        NSColor.black.setStroke()
        let rect = NSRect(x: 2, y: 2, width: pointSize - 4, height: pointSize - 4)
        let circle = NSBezierPath(ovalIn: rect)
        circle.lineWidth = 2
        circle.stroke()

        let bolt = NSBezierPath()
        bolt.move(to: NSPoint(x: pointSize * 0.56, y: pointSize * 0.78))
        bolt.line(to: NSPoint(x: pointSize * 0.38, y: pointSize * 0.48))
        bolt.line(to: NSPoint(x: pointSize * 0.54, y: pointSize * 0.48))
        bolt.line(to: NSPoint(x: pointSize * 0.44, y: pointSize * 0.22))
        bolt.lineWidth = 2
        bolt.stroke()
        image.unlockFocus()
        return image
    }
}
