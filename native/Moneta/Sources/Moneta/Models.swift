import Foundation

struct AnalyticsResponse: Decodable {
    let meta: AnalyticsMeta
    let kpis: KPIs
    let trend: [TrendPoint]
    let composition: [CompositionItem]
    let spikes: [SpikeItem]
    let merchants: [MerchantItem]
    let driverSummary: DriverSummary
    let driverRows: [DriverNode]
    let insights: [InsightItem]
    let transactions: [TransactionItem]
}

struct AnalyticsMeta: Decodable {
    let selectedMonth: String
    let selectedMonths: [String]?
    let rangeMonths: Int
    let periodMonths: [String]
    let previousPeriodMonths: [String]
    let periodLabel: String
    let previousPeriodLabel: String
    let baselineComplete: Bool
    let isPartial: Bool?
    let asOfDate: String?
    let comparisonCutoffDay: Int?
    let trendContext: Bool?
    let scopeLabel: String
    let category: String
    let subcategory: String
    let merchant: String
    let comparison: String
    let comparisonLabel: String
    let dimension: String
    let lastUpdated: String
    let months: [String]
    let categories: [String]
    let subcategories: [String]
    let merchants: [String]
    let taxonomy: [String: [String]]
}

struct KPIs: Decodable {
    let period: ComparisonMetric
    let monthlyAverage: ComparisonMetric
    let year: ComparisonMetric
    let transactions: Int
    let dailyAverage: Double
}

struct ComparisonMetric: Decodable {
    let value: Double
    let previous: Double
    let changePct: Double?
}

struct TrendPoint: Decodable, Identifiable {
    var id: String { month }
    let month: String
    let amount: Double
    let transactions: Int
    let comparisonMonth: String?
    let comparisonAmount: Double?
}

struct CompositionItem: Decodable, Identifiable {
    var id: String { name }
    let name: String
    let amount: Double
    let share: Double
}

struct SpikeItem: Decodable, Identifiable {
    var id: String { name }
    let name: String
    let current: Double
    let previous: Double
    let delta: Double
    let pct: Double?
}

struct MerchantItem: Decodable, Identifiable {
    var id: String { name }
    let name: String
    let amount: Double
    let previous: Double
    let delta: Double
    let share: Double
    let transactions: Int
}

struct DriverSummary: Decodable {
    let current: Double
    let previous: Double
    let delta: Double
    let pct: Double?
    let transactions: Int
    let previousTransactions: Int
    let biggestIncrease: SpikeItem?
    let biggestDecrease: SpikeItem?
}

struct DriverNode: Decodable, Identifiable {
    let id: String
    let level: String
    let name: String
    let path: [String]
    let current: Double
    let previous: Double
    let delta: Double
    let pct: Double?
    let share: Double
    let transactions: Int
    let previousTransactions: Int
    let averageTicket: Double
    let previousAverageTicket: Double
    let trend: [TrendPoint]
    let children: [DriverNode]
}

struct InsightItem: Decodable, Identifiable {
    var id: String { title + body }
    let tone: String
    let title: String
    let body: String
}

struct InsightsHubResponse: Decodable {
    let cadence: String
    let generatedAt: String
    let nextRefresh: String
    let items: [HubInsight]
}

struct HubInsight: Decodable, Identifiable {
    var id: String { title + body }
    let theme: String
    let tone: String
    let title: String
    let body: String
    let metric: String
    let metricLabel: String
    let actionPage: String
    let actionCategory: String
    let actionSubcategory: String
}

struct TransactionItem: Decodable, Identifiable {
    var id: String { txnId }
    let txnId: String
    let date: String
    let monthYear: String
    let amountAed: Double
    let category: String
    let subcategory: String
    let detail: String
    let merchantClean: String
    let cardUsed: String
    let source: String
    let person: String
    let notes: String
}

struct CommitmentsResponse: Decodable {
    let annualTotal: Double
    let monthlyEquivalent: Double
    let updatedAt: String
    let commitments: [Commitment]
    let upcoming: [UpcomingPayment]
}

struct Commitment: Decodable, Identifiable {
    let id: String
    let name: String
    let merchant: String
    let category: String
    let subcategory: String
    let cadence: String
    let annualAmount: Double
    let paymentAmount: Double
    let startDate: String
    let endDate: String
    let paymentDates: [String]
    let active: Bool
    let source: String
}

struct CommitmentUpdatePayload: Encodable {
    let monthlyAmount: Double
    let startDate: String
    let endDate: String
    let active: Bool
}

struct UpcomingPayment: Decodable, Identifiable {
    let commitmentId: String
    var id: String { "\(commitmentId)|\(dueDate)|\(amount)" }
    let name: String
    let merchant: String
    let category: String
    let subcategory: String
    let cadence: String
    let amount: Double
    let dueDate: String

    enum CodingKeys: String, CodingKey {
        case commitmentId = "id"
        case name, merchant, category, subcategory, cadence, amount, dueDate
    }
}

struct HealthItem: Decodable {
    let title: String?
    let status: String
    let generatedAt: String?
    let ageMinutes: Double?
    let message: String?
}

struct CashEntryPayload: Encodable {
    let amount: String
    let merchant: String
    let date: String
    let category: String
    let subcategory: String
    let notes: String
}

struct CashEntryResponse: Decodable {
    let status: String
    let amount: Double
    let merchant: String
}

enum WorkspacePage: String, CaseIterable, Identifiable {
    case overview = "Overview"
    case insights = "Insights hub"
    case trends = "Trend studio"
    case drivers = "Spend drivers"
    case transactions = "Transactions"
    case commitments = "Commitments"
    case health = "Data health"
    var id: String { rawValue }
    var usesAnalyticalSlicers: Bool {
        switch self {
        case .overview, .trends, .drivers, .transactions: true
        case .insights, .commitments, .health: false
        }
    }
    var icon: String {
        switch self {
        case .overview: "square.grid.2x2"
        case .insights: "lightbulb.max"
        case .trends: "chart.xyaxis.line"
        case .drivers: "water.waves"
        case .transactions: "list.bullet.rectangle"
        case .commitments: "calendar.badge.clock"
        case .health: "checkmark.shield"
        }
    }
}

enum DriverDisplayMode: String, CaseIterable, Identifiable {
    case composition = "Where it went"
    case change = "What changed"
    var id: String { rawValue }
}

enum ComparisonMode: String, CaseIterable, Identifiable {
    case previous = "Previous period"
    case year = "Last year"
    var id: String { rawValue }
}

enum TrendMode: String, CaseIterable, Identifiable {
    case actual = "Spend"
    case comparison = "Vs comparison"
    case rollingAverage = "3M average"
    case indexed = "Indexed"
    case monthlyChange = "MoM change"
    var id: String { rawValue }
}

extension JSONDecoder {
    static var moneta: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}

extension Double {
    var aed: String {
        formatted(.currency(code: "AED").precision(.fractionLength(0)))
    }
    var signedPercent: String {
        let prefix = self > 0 ? "+" : ""
        return "\(prefix)\(formatted(.number.precision(.fractionLength(1))))%"
    }
}
