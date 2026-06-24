import Foundation

protocol RefreshSchedulerTimer: AnyObject, Sendable {
    func invalidate()
}

extension Timer: RefreshSchedulerTimer {}

@MainActor
public final class RefreshScheduler {
    private typealias TimerFactory = (TimeInterval, @escaping @MainActor () -> Void) -> RefreshSchedulerTimer

    private let timerFactory: TimerFactory
    private var timer: RefreshSchedulerTimer?
    public private(set) var currentInterval: TimeInterval?

    public init() {
        self.timerFactory = { interval, handler in
            Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { _ in
                Task { @MainActor in
                    handler()
                }
            }
        }
    }

    init(_ timerFactory: @escaping (TimeInterval, @escaping @MainActor () -> Void) -> RefreshSchedulerTimer) {
        self.timerFactory = timerFactory
    }

    deinit {
        timer?.invalidate()
    }

    public var isScheduled: Bool {
        timer != nil
    }

    public func schedule(interval: TimeInterval, handler: @escaping @MainActor () -> Void) {
        timer?.invalidate()
        guard interval > 0 else {
            timer = nil
            currentInterval = nil
            return
        }
        currentInterval = interval
        timer = timerFactory(interval, handler)
    }

    public func invalidate() {
        timer?.invalidate()
        timer = nil
        currentInterval = nil
    }
}
