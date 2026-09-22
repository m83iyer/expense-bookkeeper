import Foundation
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    @Published var page: WorkspacePage = .overview
    @Published var analytics: AnalyticsResponse?
    @Published var commitments: CommitmentsResponse?
    @Published var insightsHub: InsightsHubResponse?
    @Published var insightCadence = "weekly"
    @Published var health: [String: HealthItem] = [:]
    @Published var selectedMonth = ""
    @Published var selectedMonths: Set<String> = []
    @Published var rangeMonths = 1
    @Published var category = ""
    @Published var subcategory = ""
    @Published var merchant = ""
    @Published var comparison: ComparisonMode = .previous
    @Published var isLoading = true
    @Published var errorMessage: String?
    @Published var lastRefresh: Date?
    @Published private(set) var scopeRevision = 0
    @Published private(set) var isRefreshingScope = false
    @Published private(set) var canNavigateBack = false
    @Published private(set) var canNavigateForward = false

    private let api = APIClient()
    private var loadGeneration = 0
    private var backwardScopes: [ScopeSnapshot] = []
    private var forwardScopes: [ScopeSnapshot] = []

    private struct ScopeSnapshot {
        let page: WorkspacePage
        let selectedMonth: String
        let selectedMonths: Set<String>
        let rangeMonths: Int
        let category: String
        let subcategory: String
        let merchant: String
        let comparison: ComparisonMode
    }

    var scopeTitle: String {
        let period = analytics?.meta.periodLabel ?? selectedMonth
        let categoryScope = category.split(separator: "|").map(String.init).joined(separator: ", ")
        let subcategoryScope = subcategory.split(separator: "|").map(String.init).joined(separator: ", ")
        let merchantScope = merchant.split(separator: "|").map(String.init).joined(separator: ", ")
        let parts = [period, categoryScope, subcategoryScope, merchantScope].filter { !$0.isEmpty }
        return parts.isEmpty ? "All spending" : parts.joined(separator: "  ›  ")
    }

    var availableYears: [String] {
        Array(Set((analytics?.meta.months ?? []).compactMap { $0.split(separator: "-").last.map(String.init) }))
            .sorted(by: >)
    }

    var selectedYear: String {
        selectedMonth.split(separator: "-").last.map(String.init) ?? availableYears.first ?? ""
    }

    var availableMonthsForSelectedYear: [(key: String, label: String)] {
        (analytics?.meta.months ?? []).compactMap { key in
            let pieces = key.split(separator: "-")
            guard pieces.count == 2, String(pieces[1]) == selectedYear else { return nil }
            return (key, Self.monthLabel(String(pieces[0])))
        }
    }

    var selectedMonthLabel: String {
        guard let short = selectedMonth.split(separator: "-").first else { return "Latest" }
        return Self.monthLabel(String(short))
    }

    var selectedYearLabel: String {
        let years = Set(selectedMonths.compactMap { $0.split(separator: "-").last.map(String.init) })
        return years.count > 1 ? "\(years.count) years" : years.first ?? selectedYear
    }

    var selectedPeriodLabel: String {
        if selectedMonths.count > 1 { return "\(selectedMonths.count) months" }
        if selectedMonths.count == 1 { return "Selected month" }
        return rangeMonths == 1 ? "Selected month" : "Last \(rangeMonths) months"
    }

    var categoryLabel: String {
        let values = category.split(separator: "|")
        return values.count > 1 ? "\(values.count) selected" : values.first.map(String.init) ?? "All"
    }

    var subcategoryLabel: String {
        let values = subcategory.split(separator: "|")
        return values.count > 1 ? "\(values.count) selected" : values.first.map(String.init) ?? "All"
    }

    var merchantLabel: String {
        let values = merchant.split(separator: "|")
        return values.count > 1 ? "\(values.count) selected" : values.first.map(String.init) ?? "All"
    }

    private static func monthLabel(_ short: String) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MMM"
        guard let date = formatter.date(from: short) else { return short }
        formatter.dateFormat = "MMMM"
        return formatter.string(from: date)
    }

    var canMoveToPreviousMonth: Bool {
        guard let months = analytics?.meta.months, let index = months.firstIndex(of: selectedMonth) else { return false }
        return index < months.count - 1
    }

    var canMoveToNextMonth: Bool {
        guard let months = analytics?.meta.months, let index = months.firstIndex(of: selectedMonth) else { return false }
        return index > 0
    }

    var overallHealth: String {
        if health.isEmpty { return "Checking" }
        let acceptable = Set(["healthy", "ok", "watch", "clean", "complete"])
        return health.values.allSatisfy { acceptable.contains($0.status.lowercased()) } ? "Connected" : "Review needed"
    }

    func start() async {
        await refresh(includeSecondary: true)
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(30))
            guard !Task.isCancelled else { return }
            await refresh(includeSecondary: true, passive: true)
        }
    }

    func refresh(includeSecondary: Bool = false, passive: Bool = false) async {
        loadGeneration += 1
        let generation = loadGeneration
        if !passive {
            isLoading = analytics == nil
            isRefreshingScope = true
        }
        errorMessage = nil
        do {
            let newAnalytics = try await api.analytics(
                month: selectedMonth,
                range: rangeMonths,
                category: category,
                subcategory: subcategory,
                merchant: merchant,
                comparison: comparison,
                months: selectedMonths
            )
            guard generation == loadGeneration else { return }
            analytics = newAnalytics
            if includeSecondary {
                async let commitmentsRequest = try? api.commitments()
                async let healthRequest = try? api.health()
                async let insightsRequest = try? scopedInsights()
                let (newCommitments, newHealth, newInsights) = await (commitmentsRequest, healthRequest, insightsRequest)
                guard generation == loadGeneration else { return }
                if let newCommitments { commitments = newCommitments }
                if let newHealth { health = newHealth }
                if let newInsights { insightsHub = newInsights }
            }
            if let meta = analytics?.meta {
                selectedMonth = meta.selectedMonth
                category = meta.category
                subcategory = meta.subcategory
                merchant = meta.merchant
                comparison = meta.comparison == "year" ? .year : .previous
            }
            lastRefresh = Date()
        } catch {
            guard generation == loadGeneration else { return }
            errorMessage = error.localizedDescription
        }
        if !passive {
            isLoading = false
            isRefreshingScope = false
        }
    }

    private func scopedInsights() async throws -> InsightsHubResponse {
        try await api.insights(
            cadence: insightCadence,
            month: selectedMonth,
            range: rangeMonths,
            category: category,
            subcategory: subcategory,
            merchant: merchant,
            comparison: comparison,
            months: selectedMonths
        )
    }

    func selectMonth(_ month: String) {
        selectedMonth = month
        scopeRevision += 1
    }

    func selectYear(_ year: String) {
        let currentShortMonth = selectedMonth.split(separator: "-").first.map(String.init)
        let candidates = analytics?.meta.months ?? []
        let matching = candidates.first { key in
            let pieces = key.split(separator: "-")
            return pieces.count == 2 && String(pieces[1]) == year && String(pieces[0]) == currentShortMonth
        } ?? candidates.first { $0.hasSuffix("-\(year)") }
        guard let matching else { return }
        selectedMonth = matching
        selectedMonths = [matching]
        rangeMonths = 1
        scopeRevision += 1
    }

    func selectCalendarMonth(_ month: String) {
        selectedMonth = month
        selectedMonths = [month]
        rangeMonths = 1
        scopeRevision += 1
    }

    func toggleCalendarMonth(_ month: String) {
        if selectedMonths.contains(month) { selectedMonths.remove(month) }
        else { selectedMonths.insert(month) }
        selectedMonth = selectedMonths.sorted { monthKey($0) < monthKey($1) }.last ?? month
        rangeMonths = 1
        scopeRevision += 1
    }

    func selectAllMonthsForSelectedYear() {
        selectedMonths.formUnion(availableMonthsForSelectedYear.map(\.key))
        selectedMonth = selectedMonths.sorted { monthKey($0) < monthKey($1) }.last ?? selectedMonth
        rangeMonths = 1
        scopeRevision += 1
    }

    func clearAllCalendarMonths() {
        selectedMonths = []
        rangeMonths = 1
        scopeRevision += 1
    }

    func selectAllYears() {
        selectedMonths = Set(analytics?.meta.months ?? [])
        selectedMonth = selectedMonths.sorted { monthKey($0) < monthKey($1) }.last ?? selectedMonth
        rangeMonths = 1
        scopeRevision += 1
    }

    func toggleYear(_ year: String) {
        let yearMonths = Set((analytics?.meta.months ?? []).filter { $0.hasSuffix("-\(year)") })
        if yearMonths.isSubset(of: selectedMonths) { selectedMonths.subtract(yearMonths) }
        else { selectedMonths.formUnion(yearMonths) }
        selectedMonth = selectedMonths.sorted { monthKey($0) < monthKey($1) }.last ?? selectedMonth
        rangeMonths = 1
        scopeRevision += 1
    }

    func yearIsSelected(_ year: String) -> Bool {
        let yearMonths = Set((analytics?.meta.months ?? []).filter { $0.hasSuffix("-\(year)") })
        return !yearMonths.isEmpty && yearMonths.isSubset(of: selectedMonths)
    }

    func toggleCategory(_ value: String) {
        var values = Set(category.split(separator: "|").map(String.init))
        if values.contains(value) { values.remove(value) } else { values.insert(value) }
        category = values.sorted().joined(separator: "|")
        subcategory = ""
        merchant = ""
        scopeRevision += 1
    }

    func selectAllCategories() {
        category = (analytics?.meta.categories ?? []).sorted().joined(separator: "|")
        subcategory = ""
        merchant = ""
        scopeRevision += 1
    }

    func clearAllCategories() {
        category = ""
        subcategory = ""
        merchant = ""
        scopeRevision += 1
    }

    func toggleSubcategory(_ value: String) {
        var values = Set(subcategory.split(separator: "|").map(String.init))
        if values.contains(value) { values.remove(value) } else { values.insert(value) }
        subcategory = values.sorted().joined(separator: "|")
        merchant = ""
        scopeRevision += 1
    }

    func selectAllSubcategories() {
        subcategory = (analytics?.meta.subcategories ?? []).sorted().joined(separator: "|")
        merchant = ""
        scopeRevision += 1
    }

    func clearAllSubcategories() {
        subcategory = ""
        merchant = ""
        scopeRevision += 1
    }

    func toggleMerchant(_ value: String) {
        var values = Set(merchant.split(separator: "|").map(String.init))
        if values.contains(value) { values.remove(value) } else { values.insert(value) }
        merchant = values.sorted().joined(separator: "|")
        scopeRevision += 1
    }

    func selectAllMerchants() {
        merchant = (analytics?.meta.merchants ?? []).sorted().joined(separator: "|")
        scopeRevision += 1
    }

    func clearAllMerchants() {
        merchant = ""
        scopeRevision += 1
    }

    func selectComparison(_ value: ComparisonMode) {
        comparison = value
        scopeRevision += 1
    }

    private func monthKey(_ value: String) -> Date {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MMM-yyyy"
        return formatter.date(from: value) ?? .distantPast
    }

    func moveMonth(_ offset: Int) {
        guard let months = analytics?.meta.months, let index = months.firstIndex(of: selectedMonth) else { return }
        let target = index - offset
        guard months.indices.contains(target) else { return }
        selectMonth(months[target])
    }

    func selectRange(_ range: Int) {
        rangeMonths = range
        selectedMonths = []
        scopeRevision += 1
    }

    func selectCategory(_ value: String) {
        rememberScope()
        category = value
        subcategory = ""
        merchant = ""
        scopeRevision += 1
    }

    func selectSubcategory(_ value: String) {
        rememberScope()
        subcategory = value
        merchant = ""
        scopeRevision += 1
    }

    func selectMerchant(_ value: String) {
        rememberScope()
        merchant = value
        scopeRevision += 1
    }

    func drill(_ item: CompositionItem) {
        rememberScope()
        guard let dimension = analytics?.meta.dimension else { return }
        if dimension == "category" {
            category = item.name
            subcategory = ""
            merchant = ""
        } else if dimension == "subcategory" {
            subcategory = item.name
            merchant = ""
        } else {
            merchant = item.name
            page = .transactions
        }
        scopeRevision += 1
    }

    func drill(_ node: DriverNode, openTransactions: Bool = false) {
        rememberScope()
        category = node.path.first ?? ""
        subcategory = node.path.count > 1 ? node.path[1] : ""
        merchant = node.path.count > 2 ? node.path[2] : ""
        if openTransactions || node.level == "merchant" { page = .transactions }
        scopeRevision += 1
    }

    func navigateHierarchy(to path: [String]) {
        rememberScope()
        category = path.indices.contains(0) ? path[0] : ""
        subcategory = path.indices.contains(1) ? path[1] : ""
        merchant = path.indices.contains(2) ? path[2] : ""
        page = .drivers
        scopeRevision += 1
    }

    func drillUp() {
        rememberScope()
        if !merchant.isEmpty {
            merchant = ""
            page = .drivers
        }
        else if !subcategory.isEmpty { subcategory = "" }
        else if !category.isEmpty { category = "" }
        if page == .transactions { page = .drivers }
        scopeRevision += 1
    }

    func resetScope() {
        rememberScope()
        selectedMonth = analytics?.meta.months.first ?? selectedMonth
        category = ""
        subcategory = ""
        merchant = ""
        rangeMonths = 1
        selectedMonths = []
        scopeRevision += 1
    }

    func navigateBack() {
        guard let target = backwardScopes.popLast() else { return }
        forwardScopes.append(scopeSnapshot())
        restore(target)
    }

    func navigateForward() {
        guard let target = forwardScopes.popLast() else { return }
        backwardScopes.append(scopeSnapshot())
        restore(target)
    }

    private func scopeSnapshot() -> ScopeSnapshot {
        ScopeSnapshot(
            page: page,
            selectedMonth: selectedMonth,
            selectedMonths: selectedMonths,
            rangeMonths: rangeMonths,
            category: category,
            subcategory: subcategory,
            merchant: merchant,
            comparison: comparison
        )
    }

    private func rememberScope() {
        backwardScopes.append(scopeSnapshot())
        if backwardScopes.count > 40 { backwardScopes.removeFirst() }
        forwardScopes.removeAll()
        updateNavigationState()
    }

    private func restore(_ snapshot: ScopeSnapshot) {
        page = snapshot.page
        selectedMonth = snapshot.selectedMonth
        selectedMonths = snapshot.selectedMonths
        rangeMonths = snapshot.rangeMonths
        category = snapshot.category
        subcategory = snapshot.subcategory
        merchant = snapshot.merchant
        comparison = snapshot.comparison
        updateNavigationState()
        scopeRevision += 1
    }

    private func updateNavigationState() {
        canNavigateBack = !backwardScopes.isEmpty
        canNavigateForward = !forwardScopes.isEmpty
    }

    func logCash(_ payload: CashEntryPayload) async throws -> CashEntryResponse {
        let response = try await api.logCash(payload)
        await refresh(includeSecondary: true)
        return response
    }

    func updateCommitment(id: String, payload: CommitmentUpdatePayload) async throws {
        commitments = try await api.updateCommitment(id: id, payload: payload)
    }

    func setInsightCadence(_ cadence: String) {
        insightCadence = cadence
        Task {
            do { insightsHub = try await scopedInsights() }
            catch { errorMessage = error.localizedDescription }
        }
    }

    func openInsight(_ insight: HubInsight) {
        category = insight.actionCategory
        subcategory = insight.actionSubcategory
        switch insight.actionPage {
        case "trends": page = .trends
        case "drivers": page = .drivers
        case "transactions": page = .transactions
        case "commitments": page = .commitments
        case "health": page = .health
        default: page = .overview
        }
        scopeRevision += 1
    }
}
