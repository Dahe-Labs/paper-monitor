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
    public private(set) var currentStartTime: String = ""

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
            currentStartTime = ""
            return
        }
        currentInterval = interval
        currentStartTime = ""
        timer = timerFactory(interval, true, handler)
    }

    public func schedule(interval: TimeInterval, startTime: String, handler: @escaping @MainActor () -> Void) {
        timer?.invalidate()
        guard interval > 0 else {
            timer = nil
            currentInterval = nil
            currentStartTime = ""
            return
        }
        currentInterval = interval
        currentStartTime = startTime
        guard !startTime.isEmpty else {
            timer = timerFactory(interval, true, handler)
            return
        }
        scheduleAnchored(interval: interval, startTime: startTime, after: Date(), handler: handler)
    }

    public func invalidate() {
        timer?.invalidate()
        timer = nil
        currentInterval = nil
        currentStartTime = ""
    }

    private func scheduleAnchored(
        interval: TimeInterval,
        startTime: String,
        after now: Date,
        handler: @escaping @MainActor () -> Void
    ) {
        let next = Self.nextScheduledRefresh(after: now, startTime: startTime, interval: interval)
        let delay = max(1, next.timeIntervalSince(now))
        timer = timerFactory(delay, false) { [weak self] in
            handler()
            self?.scheduleAnchored(interval: interval, startTime: startTime, after: Date(), handler: handler)
        }
    }

    static func nextScheduledRefresh(after now: Date, startTime: String, interval: TimeInterval) -> Date {
        let calendar = Calendar.current
        let parts = startTime.split(separator: ":", omittingEmptySubsequences: false)
        let hour = parts.count == 2 ? Int(parts[0]) ?? calendar.component(.hour, from: now) : calendar.component(.hour, from: now)
        let minute = parts.count == 2 ? Int(parts[1]) ?? calendar.component(.minute, from: now) : calendar.component(.minute, from: now)
        var components = calendar.dateComponents([.year, .month, .day], from: now)
        components.hour = min(23, max(0, hour))
        components.minute = min(59, max(0, minute))
        components.second = 0

        guard var anchor = calendar.date(from: components) else {
            return now.addingTimeInterval(max(60, interval))
        }
        if anchor >= now {
            return anchor
        }
        let safeInterval = max(60, interval)
        let elapsed = now.timeIntervalSince(anchor)
        let intervalsElapsed = floor(elapsed / safeInterval) + 1
        anchor.addTimeInterval(intervalsElapsed * safeInterval)
        return anchor
    }
}
