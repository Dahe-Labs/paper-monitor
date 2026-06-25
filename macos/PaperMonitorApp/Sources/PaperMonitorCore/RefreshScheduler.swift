import Foundation

protocol RefreshSchedulerTimer: AnyObject, Sendable {
    func invalidate()
}

extension Timer: RefreshSchedulerTimer {}

@MainActor
public final class RefreshScheduler {
    private typealias TimerFactory = (TimeInterval, Bool, @escaping @MainActor () -> Void) -> RefreshSchedulerTimer

    private let timerFactory: TimerFactory
    private var timer: RefreshSchedulerTimer?
    public private(set) var currentInterval: TimeInterval?
    public private(set) var currentInitialDelay: TimeInterval?

    public init() {
        self.timerFactory = { interval, repeats, handler in
            Timer.scheduledTimer(withTimeInterval: interval, repeats: repeats) { _ in
                Task { @MainActor in
                    handler()
                }
            }
        }
    }

    init(_ timerFactory: @escaping (TimeInterval, @escaping @MainActor () -> Void) -> RefreshSchedulerTimer) {
        self.timerFactory = { interval, _, handler in
            timerFactory(interval, handler)
        }
    }

    init(_ timerFactory: @escaping (TimeInterval, Bool, @escaping @MainActor () -> Void) -> RefreshSchedulerTimer) {
        self.timerFactory = timerFactory
    }

    deinit {
        timer?.invalidate()
    }

    public var isScheduled: Bool {
        timer != nil
    }

    public func schedule(interval: TimeInterval, handler: @escaping @MainActor () -> Void) {
        schedule(initialDelay: interval, interval: interval, handler: handler)
    }

    public func schedule(
        interval: TimeInterval,
        startTime: String?,
        now: Date = Date(),
        calendar: Calendar = .current,
        handler: @escaping @MainActor () -> Void
    ) {
        let initialDelay = RefreshSchedulePolicy.initialDelay(
            interval: interval,
            startTime: startTime,
            now: now,
            calendar: calendar
        )
        schedule(initialDelay: initialDelay, interval: interval, handler: handler)
    }

    private func schedule(initialDelay: TimeInterval, interval: TimeInterval, handler: @escaping @MainActor () -> Void) {
        timer?.invalidate()
        guard interval > 0 else {
            timer = nil
            currentInterval = nil
            currentInitialDelay = nil
            return
        }
        currentInterval = interval
        currentInitialDelay = max(0, initialDelay)
        if currentInitialDelay == interval {
            timer = timerFactory(interval, true, handler)
            return
        }
        if currentInitialDelay == 0 {
            handler()
            timer = timerFactory(interval, true, handler)
            return
        }
        timer = timerFactory(currentInitialDelay ?? interval, false) { [weak self] in
            handler()
            self?.timer = self?.timerFactory(interval, true, handler)
        }
    }

    public func invalidate() {
        timer?.invalidate()
        timer = nil
        currentInterval = nil
        currentInitialDelay = nil
    }
}
