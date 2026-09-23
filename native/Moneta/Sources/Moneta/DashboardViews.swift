import Charts
import Foundation
import SwiftUI

struct InsightsHubView: View {
    @EnvironmentObject private var model: AppModel
    @State private var expandedThemes: Set<String> = ["momentum"]

    private let themes = [
        InsightTheme(id: "momentum", title: "Spending momentum", subtitle: "Direction, pace and annual context", icon: "chart.line.uptrend.xyaxis", color: MonetaTheme.amber),
        InsightTheme(id: "drivers", title: "Drivers and concentration", subtitle: "Categories, merchants and large expenses", icon: "scope", color: MonetaTheme.coral),
        InsightTheme(id: "commitments", title: "Commitments and subscriptions", subtitle: "Known recurring cash pressure", icon: "calendar.badge.clock", color: MonetaTheme.forest),
        InsightTheme(id: "watchlist", title: "Watchlist and data quality", subtitle: "Classification confidence and concentration", icon: "checkmark.shield", color: MonetaTheme.teal),
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top) {
                    ScopeHeader(title: "Insights hub", subtitle: "Four expandable themes connecting momentum, drivers, commitments and data quality")
                    Spacer()
                    Picker("Refresh rhythm", selection: Binding(get: { model.insightCadence }, set: { model.setInsightCadence($0) })) {
                        Text("Weekly").tag("weekly")
                        Text("Fortnightly").tag("fortnightly")
                        Text("Monthly").tag("monthly")
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 320)
                }
                if let hub = model.insightsHub {
                    HStack {
                        Label("Refreshed \(hub.generatedAt)", systemImage: "clock.arrow.circlepath")
                        Spacer()
                        Button(expandedThemes.count == themes.count ? "Collapse all" : "Expand all") {
                            withAnimation(.easeOut(duration: 0.18)) {
                                expandedThemes = expandedThemes.count == themes.count ? [] : Set(themes.map(\.id))
                            }
                        }.buttonStyle(.bordered)
                    }
                    .font(.caption).foregroundStyle(.secondary)

                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 390), spacing: 16, alignment: .top)], alignment: .leading, spacing: 16) {
                        ForEach(themes) { theme in
                            InsightThemeSection(
                                theme: theme,
                                insights: hub.items.filter { $0.theme == theme.id },
                                isExpanded: Binding(
                                    get: { expandedThemes.contains(theme.id) },
                                    set: { value in
                                        withAnimation(.easeOut(duration: 0.18)) {
                                            if value { expandedThemes.insert(theme.id) } else { expandedThemes.remove(theme.id) }
                                        }
                                    }
                                ),
                                action: model.openInsight
                            )
                        }
                    }
                } else {
                    ProgressView("Connecting the dots across your ledger…")
                }
            }.padding(20)
        }
    }
}

private struct InsightTheme: Identifiable {
    let id: String
    let title: String
    let subtitle: String
    let icon: String
    let color: Color
}

private struct InsightThemeSection: View {
    let theme: InsightTheme
    let insights: [HubInsight]
    @Binding var isExpanded: Bool
    let action: (HubInsight) -> Void
    @State private var headerHovered = false

    private var lead: HubInsight? { insights.first }

    var body: some View {
        VStack(spacing: 0) {
            Button {
                withAnimation(.easeOut(duration: 0.18)) { isExpanded.toggle() }
            } label: {
                HStack(alignment: .center, spacing: 14) {
                    Image(systemName: theme.icon).font(.title2.weight(.semibold)).foregroundStyle(theme.color)
                        .frame(width: 42, height: 42).background(theme.color.opacity(0.11), in: RoundedRectangle(cornerRadius: 11))
                    VStack(alignment: .leading, spacing: 4) {
                        Text(theme.title).font(.title3.bold()).foregroundStyle(.primary)
                        Text(isExpanded ? theme.subtitle : (lead?.title ?? theme.subtitle)).font(.callout).foregroundStyle(.secondary).lineLimit(1)
                    }
                    Spacer(minLength: 16)
                    if let lead {
                        VStack(alignment: .trailing, spacing: 2) {
                            Text(lead.metric).font(.title.bold().monospacedDigit()).foregroundStyle(metricColor(lead.tone))
                            Text(lead.metricLabel.uppercased()).font(.caption2.monospaced()).foregroundStyle(.secondary)
                        }
                    }
                    Image(systemName: "chevron.right")
                        .font(.callout.bold()).foregroundStyle(theme.color)
                        .rotationEffect(.degrees(isExpanded ? 90 : 0))
                        .frame(width: 28, height: 44)
                }
                .padding(18)
                .frame(maxWidth: .infinity, minHeight: 88, alignment: .leading)
                .contentShape(Rectangle())
                .background(headerHovered ? theme.color.opacity(0.075) : Color.clear)
            }
            .buttonStyle(FullSurfaceToggleStyle())
            .onHover { headerHovered = $0 }
            .accessibilityLabel("\(theme.title), \(lead?.metric ?? ""), \(isExpanded ? "expanded" : "collapsed")")
            .accessibilityHint(isExpanded ? "Activate anywhere in this header to collapse the theme" : "Activate anywhere in this header to expand the theme")

            if isExpanded {
                VStack(spacing: 0) {
                    Divider()
                ForEach(insights) { insight in
                    Button { action(insight) } label: {
                        HStack(alignment: .center, spacing: 14) {
                            VStack(alignment: .leading, spacing: 5) {
                                Text(insight.title).font(.headline).fontWeight(.bold).foregroundStyle(.primary)
                                Text(insight.body).font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.leading).lineLimit(3)
                            }
                            Spacer(minLength: 16)
                            VStack(alignment: .trailing, spacing: 3) {
                                Text(insight.metric).font(.title3.bold().monospacedDigit()).foregroundStyle(metricColor(insight.tone))
                                Text(insight.metricLabel.uppercased()).font(.caption2.monospaced()).foregroundStyle(.secondary).multilineTextAlignment(.trailing).lineLimit(2)
                            }.frame(minWidth: 116, alignment: .trailing)
                            Image(systemName: "arrow.up.right").font(.caption.bold()).foregroundStyle(theme.color)
                        }
                        .padding(.vertical, 13)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    Divider()
                }
                }
                .padding(.horizontal, 18)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .background(MonetaTheme.panel, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(isExpanded ? theme.color.opacity(0.55) : MonetaTheme.line, lineWidth: isExpanded ? 1.5 : 1))
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .shadow(color: isExpanded ? theme.color.opacity(0.08) : .clear, radius: 12, y: 4)
    }

    private func metricColor(_ tone: String) -> Color {
        switch tone { case "attention": MonetaTheme.coral; case "positive": MonetaTheme.teal; default: theme.color }
    }
}

private struct FullSurfaceToggleStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(configuration.isPressed ? 0.76 : 1)
            .scaleEffect(configuration.isPressed ? 0.995 : 1)
            .animation(.easeOut(duration: 0.1), value: configuration.isPressed)
    }
}

struct OverviewView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        ScrollView {
            if let data = model.analytics {
                VStack(alignment: .leading, spacing: 18) {
                    ScopeHeader(title: "Your money brief", subtitle: "A concise read of \(model.scopeTitle)")
                    HStack(alignment: .top, spacing: 16) {
                        HomePeriodBrief(data: data).frame(maxWidth: .infinity)
                        HomeExploreRail(select: { model.page = $0 }).frame(width: 300)
                    }
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 360), spacing: 16, alignment: .top)], alignment: .leading, spacing: 16) {
                        HomeChangeBrief(data: data) { model.page = .drivers }
                        HomeCategoryBrief(items: data.composition) { model.page = .drivers }
                        HomeCommitmentBrief(data: model.commitments) { model.page = .commitments }
                        HomeWatchlistBrief(items: model.insightsHub?.items ?? []) { model.page = .insights }
                    }
                }
                .padding(20)
            }
        }
    }
}

private struct HomePeriodBrief: View {
    let data: AnalyticsResponse
    private var change: Double? { data.kpis.period.changePct }
    private var changeColor: Color { (change ?? 0) > 0 ? MonetaTheme.coral : MonetaTheme.teal }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(data.meta.periodLabel.uppercased()).font(.caption.monospaced().weight(.semibold)).foregroundStyle(MonetaTheme.onBrand.opacity(0.72))
            Text("You spent")
                .font(.title2.weight(.medium)).foregroundStyle(MonetaTheme.onBrand.opacity(0.88))
            Text(data.kpis.period.value.aed)
                .font(.system(size: 46, weight: .bold, design: .rounded)).monospacedDigit().foregroundStyle(MonetaTheme.onBrand)
            if let change {
                HStack(spacing: 8) {
                    Image(systemName: change > 0 ? "arrow.up.right" : change < 0 ? "arrow.down.right" : "minus")
                    Text("\(abs(change).formatted(.number.precision(.fractionLength(1))))% \(change > 0 ? "higher" : change < 0 ? "lower" : "unchanged") than \(data.meta.previousPeriodLabel)")
                }
                .font(.headline).foregroundStyle(changeColor)
            }
            Divider().overlay(MonetaTheme.onBrand.opacity(0.22))
            HStack(spacing: 28) {
                briefMetric("Monthly pace", data.kpis.monthlyAverage.value.aed)
                briefMetric("Transactions", data.kpis.transactions.formatted())
                briefMetric("Per spending day", data.kpis.dailyAverage.aed)
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity, minHeight: 260, alignment: .leading)
        .background(MonetaTheme.brandFill, in: RoundedRectangle(cornerRadius: 20))
    }

    private func briefMetric(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label.uppercased()).font(.caption2.monospaced()).foregroundStyle(MonetaTheme.onBrand.opacity(0.70))
            Text(value).font(.title3.bold().monospacedDigit()).foregroundStyle(MonetaTheme.onBrand)
        }
    }
}

private struct HomeExploreRail: View {
    let select: (WorkspacePage) -> Void
    private let routes: [(WorkspacePage, String, String)] = [
        (.trends, "Trend studio", "See the shape over time"),
        (.drivers, "Spike drivers", "Understand what changed"),
        (.transactions, "Transactions", "Inspect the evidence"),
        (.insights, "Insights hub", "Connect the signals"),
        (.commitments, "Commitments", "Review recurring cash"),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("EXPLORE").font(.caption.monospaced().weight(.semibold)).foregroundStyle(.secondary).padding(.horizontal, 16).padding(.bottom, 8)
            ForEach(routes, id: \.0) { page, title, subtitle in
                Button { select(page) } label: {
                    HStack(spacing: 12) {
                        Image(systemName: page.icon).foregroundStyle(MonetaTheme.forest).frame(width: 24)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(title).font(.headline).foregroundStyle(.primary)
                            Text(subtitle).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Image(systemName: "chevron.right").font(.caption.bold()).foregroundStyle(.tertiary)
                    }
                    .padding(.horizontal, 16).frame(maxWidth: .infinity, minHeight: 48, alignment: .leading).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                Divider().padding(.leading, 52)
            }
        }
        .padding(.vertical, 14)
        .background(MonetaTheme.panel, in: RoundedRectangle(cornerRadius: 18))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(MonetaTheme.line))
    }
}

private struct HomeChangeBrief: View {
    let data: AnalyticsResponse
    let action: () -> Void
    private var driver: SpikeItem? { data.spikes.filter { $0.delta > 0 }.max { $0.delta < $1.delta } }
    private var largest: TransactionItem? { data.transactions.max { $0.amountAed < $1.amountAed } }

    var body: some View {
        HomeBriefPanel(title: "What changed", icon: "arrow.up.right", color: MonetaTheme.coral, action: action) {
            if let driver {
                HomeSignal(label: "BIGGEST INCREASE", value: "+\(driver.delta.aed)", detail: driver.name, color: MonetaTheme.coral)
            }
            if let largest {
                Divider()
                HomeSignal(label: "LARGEST EXPENSE", value: largest.amountAed.aed, detail: "\(largest.merchantClean) · \(largest.date)", color: MonetaTheme.amber)
            }
        }
    }
}

private struct HomeCategoryBrief: View {
    let items: [CompositionItem]
    let action: () -> Void
    var body: some View {
        HomeBriefPanel(title: "Where it went", icon: "square.stack.3d.up", color: MonetaTheme.forest, action: action) {
            ForEach(Array(items.prefix(3).enumerated()), id: \.element.id) { index, item in
                HStack(spacing: 10) {
                    Text("\(index + 1)").font(.caption.monospaced()).foregroundStyle(.tertiary).frame(width: 18)
                    Text(item.name).font(.headline).lineLimit(1)
                    Spacer()
                    Text(item.amount.aed).font(.headline.monospacedDigit())
                    Text("\(item.share, specifier: "%.1f")%").font(.caption.monospaced()).foregroundStyle(MonetaTheme.forest).frame(width: 48, alignment: .trailing)
                }.frame(minHeight: 38)
                if index < 2 { Divider() }
            }
        }
    }
}

private struct HomeCommitmentBrief: View {
    let data: CommitmentsResponse?
    let action: () -> Void
    var body: some View {
        HomeBriefPanel(title: "What is committed", icon: "calendar.badge.clock", color: MonetaTheme.forest, action: action) {
            HomeSignal(label: "MONTHLY EQUIVALENT", value: data?.monthlyEquivalent.aed ?? "—", detail: "Planned recurring cash", color: MonetaTheme.forest)
            if let next = data?.upcoming.first {
                Divider()
                HomeSignal(label: "NEXT PAYMENT", value: next.amount.aed, detail: "\(next.name) · \(next.dueDate)", color: MonetaTheme.amber)
            }
        }
    }
}

private struct HomeWatchlistBrief: View {
    let items: [HubInsight]
    let action: () -> Void
    private var watchlist: [HubInsight] { Array(items.filter { $0.theme == "watchlist" }.prefix(2)) }
    var body: some View {
        HomeBriefPanel(title: "Needs attention", icon: "eye", color: MonetaTheme.teal, action: action) {
            ForEach(Array(watchlist.enumerated()), id: \.element.id) { index, item in
                HomeSignal(label: item.metricLabel.uppercased(), value: item.metric, detail: item.title, color: item.tone == "attention" ? MonetaTheme.coral : MonetaTheme.teal)
                if index < watchlist.count - 1 { Divider() }
            }
        }
    }
}

private struct HomeSignal: View {
    let label: String
    let value: String
    let detail: String
    let color: Color
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text(label).font(.caption2.monospaced()).foregroundStyle(.secondary)
                Text(detail).font(.callout.weight(.semibold)).lineLimit(2)
            }
            Spacer()
            Text(value).font(.title2.bold().monospacedDigit()).foregroundStyle(color).multilineTextAlignment(.trailing)
        }.padding(.vertical, 5)
    }
}

private struct HomeBriefPanel<Content: View>: View {
    let title: String
    let icon: String
    let color: Color
    let action: () -> Void
    @ViewBuilder let content: Content

    init(title: String, icon: String, color: Color, action: @escaping () -> Void, @ViewBuilder content: () -> Content) {
        self.title = title; self.icon = icon; self.color = color; self.action = action; self.content = content()
    }

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Label(title, systemImage: icon).font(.title3.bold()).foregroundStyle(.primary)
                    Spacer()
                    Text("Open").font(.caption.weight(.semibold)).foregroundStyle(color)
                    Image(systemName: "arrow.up.right").font(.caption.bold()).foregroundStyle(color)
                }.frame(maxWidth: .infinity, minHeight: 44).contentShape(Rectangle())
                content
            }
            .padding(18)
            .frame(maxWidth: .infinity, minHeight: 180, alignment: .topLeading)
            .background(MonetaTheme.panel, in: RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(MonetaTheme.line))
            .contentShape(RoundedRectangle(cornerRadius: 16))
        }
        .buttonStyle(FullSurfaceToggleStyle())
    }
}

private struct ScopeHeader: View {
    let title: String
    let subtitle: String
    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.largeTitle.bold())
                Text(subtitle).font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
            Text("LIVE • PRIVATE").font(.caption2.monospaced().weight(.semibold)).foregroundStyle(MonetaTheme.teal)
        }
    }
}

private struct KPIGrid: View {
    let kpis: KPIs
    let meta: AnalyticsMeta
    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 190), spacing: 12)], spacing: 12) {
            KPITile(title: meta.rangeMonths == 1 ? "Selected month" : "Selected period", metric: kpis.period, comparison: "vs prior \(meta.rangeMonths)m", baselineLabel: meta.previousPeriodLabel)
            KPITile(title: "Monthly average", metric: kpis.monthlyAverage, comparison: "per month", baselineLabel: meta.previousPeriodLabel)
            KPITile(title: "Same period last year", metric: kpis.year, comparison: "YoY", baselineLabel: "year-ago window")
            CountTile(title: "Transactions", value: kpis.transactions.formatted(), supporting: "\(kpis.dailyAverage.aed) per spending day")
        }
    }
}

private struct KPITile: View {
    let title: String
    let metric: ComparisonMetric
    let comparison: String
    let baselineLabel: String
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack { Text(title); Spacer(); Text(comparison).font(.caption2.monospaced()) }
                .font(.caption).foregroundStyle(.secondary)
            Text(metric.value.aed).font(.title.bold().monospacedDigit()).minimumScaleFactor(0.7)
            if let change = metric.changePct {
                Label(change.signedPercent, systemImage: change > 0 ? "arrow.up.right" : change < 0 ? "arrow.down.right" : "minus")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(change > 0 ? MonetaTheme.coral : change < 0 ? MonetaTheme.teal : .secondary)
            } else {
                Text("No comparison baseline").font(.callout).foregroundStyle(.secondary)
            }
            Text("\(baselineLabel): \(metric.previous.aed)").font(.caption).foregroundStyle(.secondary).lineLimit(1)
        }
        .padding(16)
        .frame(maxWidth: .infinity, minHeight: 132, alignment: .leading)
        .background(MonetaTheme.panel, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(MonetaTheme.line))
    }
}

private struct CountTile: View {
    let title: String
    let value: String
    let supporting: String
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.title.bold().monospacedDigit())
            Text(supporting).font(.callout).foregroundStyle(.secondary)
        }
        .padding(16)
        .frame(maxWidth: .infinity, minHeight: 132, alignment: .leading)
        .background(MonetaTheme.panel, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(MonetaTheme.line))
    }
}

private struct TrendPanel: View {
    @EnvironmentObject private var model: AppModel
    let points: [TrendPoint]
    @State private var focusedMonth: String?

    var body: some View {
        Panel("Monthly spend trajectory", subtitle: "Hover for detail, click a month to cross-filter every visual") {
            InteractiveTrendChart(points: points, mode: .actual, focusedMonth: $focusedMonth, onSelect: model.selectMonth)
                .frame(minHeight: 300)
        }
    }
}

private struct CompositionPanel: View {
    @EnvironmentObject private var model: AppModel
    let items: [CompositionItem]
    let dimension: String

    var body: some View {
        Panel(dimension == "category" ? "Category mix" : dimension == "subcategory" ? "Subcategory mix" : "Merchant mix", subtitle: "Select a row to drill down") {
            VStack(spacing: 2) {
                ForEach(Array(items.prefix(10).enumerated()), id: \.element.id) { index, item in
                    Button { model.drill(item) } label: {
                        HStack(spacing: 10) {
                            Text(String(format: "%02d", index + 1)).font(.caption2.monospaced()).foregroundStyle(.tertiary)
                            VStack(alignment: .leading, spacing: 6) {
                                HStack { Text(item.name).font(.callout.weight(.semibold)).lineLimit(1); Spacer(); Text(item.amount.aed).font(.callout.monospacedDigit()) }
                                ProgressView(value: item.share, total: 100).tint(MonetaTheme.forest)
                            }
                            Text("\(item.share, specifier: "%.1f")%").font(.caption2.monospaced()).foregroundStyle(.secondary).frame(width: 42, alignment: .trailing)
                        }
                        .padding(.vertical, 6)
                    }
                    .buttonStyle(.plain)
                    Divider()
                }
            }
        }
    }
}

private struct InsightStrip: View {
    let items: [InsightItem]
    var body: some View {
        HStack(spacing: 12) {
            ForEach(items) { item in
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: item.tone == "warn" ? "arrow.up.right.circle.fill" : item.tone == "good" ? "arrow.down.right.circle.fill" : "scope")
                        .foregroundStyle(item.tone == "warn" ? MonetaTheme.coral : item.tone == "good" ? MonetaTheme.teal : MonetaTheme.amber)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(item.title).font(.callout.weight(.semibold)).lineLimit(2)
                        Text(item.body).font(.caption).foregroundStyle(.secondary).lineLimit(3)
                    }
                }
                .padding(14)
                .frame(maxWidth: .infinity, minHeight: 92, alignment: .topLeading)
                .background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 12))
            }
        }
    }
}

private struct DriverPanel: View {
    @EnvironmentObject private var model: AppModel
    let items: [SpikeItem]
    let meta: AnalyticsMeta
    @State private var focusedName: String?
    var body: some View {
        Panel("What caused the movement?", subtitle: "\(meta.periodLabel) versus \(meta.previousPeriodLabel) · hover for detail, click to drill") {
            if items.isEmpty || !meta.baselineComplete {
                ContentUnavailableView("Comparison unavailable", systemImage: "calendar.badge.exclamationmark", description: Text("A complete preceding \(meta.rangeMonths)-month period is not available in the ledger."))
                    .frame(minHeight: 300)
            } else {
                Chart(Array(items.prefix(9))) { item in
                    BarMark(x: .value("Change", item.delta), y: .value("Category", item.name))
                        .foregroundStyle(item.delta >= 0 ? MonetaTheme.coral : MonetaTheme.teal)
                        .opacity(focusedName == nil || focusedName == item.name ? 1 : 0.35)
                        .annotation(position: item.delta >= 0 ? .trailing : .leading) {
                            if focusedName == item.name {
                                VStack(alignment: item.delta >= 0 ? .leading : .trailing, spacing: 2) {
                                    Text(item.delta.aed).font(.caption.weight(.bold).monospacedDigit())
                                    Text("\(item.previous.aed) → \(item.current.aed)").font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                                    Text(item.pct?.signedPercent ?? "New in period").font(.caption2).foregroundStyle(.secondary)
                                }.padding(7).background(MonetaTheme.panel, in: RoundedRectangle(cornerRadius: 8)).shadow(color: .black.opacity(0.1), radius: 7, y: 3)
                            } else { Text(item.delta.aed).font(.caption2.monospacedDigit()) }
                        }
                }
                .chartXAxis { AxisMarks(position: .bottom) { AxisGridLine(); AxisValueLabel() } }
                .chartOverlay { proxy in
                    GeometryReader { geometry in
                        Rectangle().fill(.clear).contentShape(Rectangle())
                            .onContinuousHover { phase in
                                switch phase {
                                case .active(let location): focusedName = nearestDriver(at: location, proxy: proxy, geometry: geometry)
                                case .ended: focusedName = nil
                                }
                            }
                            .gesture(SpatialTapGesture().onEnded { event in
                                guard let name = nearestDriver(at: event.location, proxy: proxy, geometry: geometry) else { return }
                                if meta.dimension == "category" { model.selectCategory(name) }
                                else if meta.dimension == "subcategory" { model.selectSubcategory(name) }
                                else { model.page = .transactions }
                            })
                    }
                }
                .animation(.easeOut(duration: 0.16), value: focusedName)
                .frame(minHeight: 300)
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func nearestDriver(at location: CGPoint, proxy: ChartProxy, geometry: GeometryProxy) -> String? {
        guard let frame = proxy.plotFrame else { return nil }
        let plot = geometry[frame]
        guard plot.contains(location) else { return nil }
        let localY = location.y - plot.minY
        return items.prefix(9).min { left, right in abs((proxy.position(forY: left.name) ?? 0) - localY) < abs((proxy.position(forY: right.name) ?? 0) - localY) }?.name
    }
}

private struct MerchantPanel: View {
    let items: [MerchantItem]
    var body: some View {
        Panel("Top merchants", subtitle: "Concentration in the selected scope") {
            VStack(spacing: 0) {
                ForEach(Array(items.prefix(8).enumerated()), id: \.element.id) { index, item in
                    HStack {
                        Text("\(index + 1)").font(.caption2.monospaced()).foregroundStyle(.tertiary).frame(width: 18)
                        Text(item.name).lineLimit(1)
                        Spacer()
                        Text(item.amount.aed).font(.callout.weight(.semibold).monospacedDigit())
                    }
                    .padding(.vertical, 10)
                    Divider()
                }
            }
        }
        .frame(width: 390)
    }
}

struct TrendsView: View {
    @EnvironmentObject private var model: AppModel
    @State private var mode: TrendMode = .actual
    @State private var focusedMonth: String?

    var body: some View {
        ScrollView {
            if let data = model.analytics {
                VStack(alignment: .leading, spacing: 16) {
                    ViewThatFits(in: .horizontal) {
                        HStack {
                            ScopeHeader(title: "Trend studio", subtitle: model.scopeTitle)
                            Spacer()
                            trendControls
                        }
                        VStack(alignment: .leading, spacing: 12) {
                            ScopeHeader(title: "Trend studio", subtitle: model.scopeTitle)
                            trendControls
                        }
                    }
                    TrendSummaryStrip(points: data.trend, focusedMonth: focusedMonth)
                    Panel(mode.rawValue, subtitle: trendSubtitle) {
                        InteractiveTrendChart(points: data.trend, mode: mode, focusedMonth: $focusedMonth, onSelect: model.selectMonth)
                            .frame(minHeight: 440)
                    }
                    Panel("Monthly evidence", subtitle: "Hover-linked exact values, select a row to inspect that month") {
                        ScrollView(.horizontal, showsIndicators: false) { VStack(spacing: 0) {
                            HStack { Text("Month").frame(maxWidth: .infinity, alignment: .leading); Text("Spend").frame(width: 130, alignment: .trailing); Text("Comparison").frame(width: 130, alignment: .trailing); Text("Variance").frame(width: 110, alignment: .trailing); Text("Count").frame(width: 80, alignment: .trailing); Text("MoM").frame(width: 90, alignment: .trailing) }
                                .font(.caption.weight(.semibold)).foregroundStyle(.secondary).padding(.horizontal, 10).padding(.bottom, 7)
                            ForEach(Array(data.trend.enumerated()), id: \.element.id) { index, point in
                                Button { model.selectMonth(point.month) } label: {
                                    HStack {
                                        Text(point.month).frame(maxWidth: .infinity, alignment: .leading)
                                        Text(point.amount.aed).frame(width: 130, alignment: .trailing)
                                        Text(point.comparisonAmount?.aed ?? "Unavailable").frame(width: 130, alignment: .trailing).foregroundStyle(.secondary)
                                        Text(point.comparisonAmount.map { (point.amount - $0).aed } ?? "Unavailable").frame(width: 110, alignment: .trailing)
                                            .foregroundStyle((point.comparisonAmount.map { point.amount - $0 } ?? 0) >= 0 ? MonetaTheme.coral : MonetaTheme.teal)
                                        Text(point.transactions.formatted()).frame(width: 80, alignment: .trailing)
                                        Text(monthlyChange(data.trend, index: index).map { $0.signedPercent } ?? "Unavailable").frame(width: 90, alignment: .trailing)
                                    }
                                    .font(.callout.monospacedDigit())
                                    .padding(.horizontal, 10).frame(minHeight: 44)
                                    .background(focusedMonth == point.month ? MonetaTheme.amber.opacity(0.12) : Color.clear, in: RoundedRectangle(cornerRadius: 8))
                                }.font(.callout)
                                .buttonStyle(.plain)
                                .onHover { hovering in if hovering { focusedMonth = point.month } }
                                Divider()
                            }
                        }.frame(minWidth: 760) }
                    }
                }.padding(20)
            }
        }
    }

    private var trendControls: some View {
        HStack {
            Button("Explain this period", systemImage: "scope") { model.page = .drivers }
                .buttonStyle(.bordered).controlSize(.large)
            Picker("Measure", selection: $mode) { ForEach(TrendMode.allCases) { Text($0.rawValue).tag($0) } }
                .pickerStyle(.segmented).frame(maxWidth: 440)
        }
    }

    private var trendSubtitle: String {
        let coverage = model.analytics?.meta.isPartial == true
            ? " · month to date through day \(model.analytics?.meta.comparisonCutoffDay ?? 0)"
            : ""
        let context = model.analytics?.meta.trendContext == true
            ? " · prior months are shown for context; headline KPIs remain the selected month"
            : ""
        switch mode {
        case .actual: return "AED spending by month\(coverage)\(context)"
        case .comparison: return "Selected period against \(model.analytics?.meta.comparisonLabel.lowercased() ?? "the comparison")\(coverage)\(context)"
        case .rollingAverage: return "Monthly spend against its trailing three-month average\(coverage)\(context)"
        case .indexed: return "Each month relative to the first visible month (100)\(coverage)\(context)"
        case .monthlyChange: return "Percentage movement from the preceding month\(coverage)\(context)"
        }
    }

    private func monthlyChange(_ points: [TrendPoint], index: Int) -> Double? {
        guard index > 0, points[index - 1].amount != 0 else { return nil }
        return (points[index].amount - points[index - 1].amount) / points[index - 1].amount * 100
    }
}

private struct ChangePoint: Identifiable { var id: String { month }; let month: String; let value: Double }

private struct RollingPoint: Identifiable { var id: String { month }; let month: String; let value: Double }

private struct TrendSummaryStrip: View {
    let points: [TrendPoint]
    let focusedMonth: String?

    private var focus: TrendPoint? { points.first { $0.month == focusedMonth } }
    private var average: Double { points.map(\.amount).reduce(0, +) / Double(max(points.count, 1)) }
    private var peak: TrendPoint? { points.max { $0.amount < $1.amount } }
    private var lowest: TrendPoint? { points.min { $0.amount < $1.amount } }

    var body: some View {
        HStack(spacing: 0) {
            summary(focusedMonth == nil ? "Window average" : "Hover focus", focusedMonth == nil ? average.aed : (focus?.amount.aed ?? "—"), focusedMonth ?? "All visible months")
            Divider().frame(height: 42)
            summary("Peak month", peak?.amount.aed ?? "—", peak?.month ?? "—")
            Divider().frame(height: 42)
            summary("Lowest month", lowest?.amount.aed ?? "—", lowest?.month ?? "—")
            Divider().frame(height: 42)
            summary("Visible activity", points.map(\.transactions).reduce(0, +).formatted(), "transactions")
        }
        .padding(.vertical, 12)
        .background(MonetaTheme.panel, in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(MonetaTheme.line))
    }

    private func summary(_ title: String, _ value: String, _ detail: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.headline.monospacedDigit())
            Text(detail).font(.caption2).foregroundStyle(.secondary)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16)
    }
}

private struct InteractiveTrendChart: View {
    let points: [TrendPoint]
    let mode: TrendMode
    @Binding var focusedMonth: String?
    let onSelect: (String) -> Void

    init(points: [TrendPoint], mode: TrendMode, focusedMonth: Binding<String?> = .constant(nil), onSelect: @escaping (String) -> Void) {
        self.points = points; self.mode = mode; self._focusedMonth = focusedMonth; self.onSelect = onSelect
    }

    private var focused: TrendPoint? { points.first { $0.month == focusedMonth } }
    private var changes: [ChangePoint] {
        points.enumerated().compactMap { index, point in
            guard index > 0, points[index - 1].amount != 0 else { return nil }
            return ChangePoint(month: point.month, value: (point.amount - points[index - 1].amount) / points[index - 1].amount * 100)
        }
    }
    private var rolling: [RollingPoint] {
        points.indices.map { index in
            let start = max(0, index - 2)
            let slice = points[start...index]
            return RollingPoint(month: points[index].month, value: slice.map(\.amount).reduce(0, +) / Double(slice.count))
        }
    }

    var body: some View {
        Chart {
            switch mode {
            case .actual:
                ForEach(points) { point in
                    AreaMark(x: .value("Month", point.month), y: .value("Spend", point.amount)).foregroundStyle(MonetaTheme.amber.opacity(0.12))
                    LineMark(x: .value("Month", point.month), y: .value("Spend", point.amount)).foregroundStyle(MonetaTheme.amber).lineStyle(.init(lineWidth: 2.5))
                    PointMark(x: .value("Month", point.month), y: .value("Spend", point.amount)).foregroundStyle(MonetaTheme.amber).symbolSize(36)
                }
            case .comparison:
                ForEach(points) { point in
                    LineMark(x: .value("Month", point.month), y: .value("Selected spend", point.amount), series: .value("Series", "Selected"))
                        .foregroundStyle(MonetaTheme.amber).lineStyle(.init(lineWidth: 2.8))
                    PointMark(x: .value("Month", point.month), y: .value("Selected spend", point.amount))
                        .foregroundStyle(MonetaTheme.amber).symbolSize(34)
                    if let comparison = point.comparisonAmount {
                        LineMark(x: .value("Month", point.month), y: .value("Comparison spend", comparison), series: .value("Series", "Comparison"))
                            .foregroundStyle(MonetaTheme.forest).lineStyle(.init(lineWidth: 2, dash: [6, 4]))
                        PointMark(x: .value("Month", point.month), y: .value("Comparison spend", comparison))
                            .foregroundStyle(MonetaTheme.forest.opacity(0.72)).symbolSize(24)
                    }
                }
            case .rollingAverage:
                ForEach(points) { point in LineMark(x: .value("Month", point.month), y: .value("Spend", point.amount), series: .value("Series", "Spend")).foregroundStyle(MonetaTheme.amber).lineStyle(.init(lineWidth: 1.5)) }
                ForEach(rolling) { point in LineMark(x: .value("Month", point.month), y: .value("3M average", point.value), series: .value("Series", "3M average")).foregroundStyle(MonetaTheme.forest).lineStyle(.init(lineWidth: 3)) }
            case .indexed:
                let base = max(points.first?.amount ?? 1, 1)
                ForEach(points) { point in LineMark(x: .value("Month", point.month), y: .value("Index", point.amount / base * 100)).foregroundStyle(MonetaTheme.forest).lineStyle(.init(lineWidth: 2.5)) }
                RuleMark(y: .value("Baseline", 100)).foregroundStyle(.secondary).lineStyle(.init(dash: [4, 4]))
            case .monthlyChange:
                ForEach(changes) { point in BarMark(x: .value("Month", point.month), y: .value("Change", point.value)).foregroundStyle(point.value >= 0 ? MonetaTheme.coral : MonetaTheme.teal) }
                RuleMark(y: .value("No change", 0)).foregroundStyle(.secondary)
            }
            if let point = focused {
                RuleMark(x: .value("Focused month", point.month)).foregroundStyle(MonetaTheme.forest.opacity(0.5)).lineStyle(.init(lineWidth: 1, dash: [3, 3]))
                PointMark(x: .value("Focused month", point.month), y: .value("Focused spend", focusValue(point))).foregroundStyle(MonetaTheme.forest).symbolSize(100)
                    .annotation(position: .top, spacing: 12) { TrendTooltip(point: point, change: change(for: point.month), mode: mode, displayValue: focusValue(point)) }
            }
        }
        .chartXAxis { AxisMarks(values: .automatic(desiredCount: min(points.count, 12))) { AxisGridLine().foregroundStyle(.clear); AxisTick(); AxisValueLabel().font(.caption) } }
        .chartYAxis { AxisMarks(position: .leading) { value in AxisGridLine(); AxisValueLabel { if let number = value.as(Double.self) { Text(mode == .actual || mode == .comparison || mode == .rollingAverage ? number.aed : number.formatted(.number.precision(.fractionLength(0)))) } } } }
        .chartOverlay { proxy in
            GeometryReader { geometry in
                Rectangle().fill(.clear).contentShape(Rectangle())
                    .onContinuousHover { phase in
                        switch phase {
                        case .active(let location): focusedMonth = nearestMonth(at: location, proxy: proxy, geometry: geometry)
                        case .ended: focusedMonth = nil
                        }
                    }
                    .gesture(SpatialTapGesture().onEnded { event in
                        if let month = nearestMonth(at: event.location, proxy: proxy, geometry: geometry) { onSelect(month) }
                    })
            }
        }
        .animation(.easeOut(duration: 0.16), value: focusedMonth)
        .accessibilityLabel("Interactive monthly spending chart. Hover for exact values and click to inspect a month.")
    }

    private func nearestMonth(at location: CGPoint, proxy: ChartProxy, geometry: GeometryProxy) -> String? {
        guard let frame = proxy.plotFrame else { return nil }
        let plot = geometry[frame]
        guard plot.contains(location) else { return nil }
        let localX = location.x - plot.minX
        return points.min { left, right in abs((proxy.position(forX: left.month) ?? 0) - localX) < abs((proxy.position(forX: right.month) ?? 0) - localX) }?.month
    }

    private func change(for month: String) -> Double? { changes.first { $0.month == month }?.value }
    private func focusValue(_ point: TrendPoint) -> Double {
        switch mode {
        case .actual: point.amount
        case .comparison: point.amount
        case .rollingAverage: rolling.first { $0.month == point.month }?.value ?? point.amount
        case .indexed: point.amount / max(points.first?.amount ?? 1, 1) * 100
        case .monthlyChange: change(for: point.month) ?? 0
        }
    }
}

private struct TrendTooltip: View {
    let point: TrendPoint
    let change: Double?
    let mode: TrendMode
    let displayValue: Double
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(point.month).font(.caption.weight(.semibold))
            Text(mode == .actual || mode == .comparison || mode == .rollingAverage ? displayValue.aed : displayValue.formatted(.number.precision(.fractionLength(1)))).font(.headline.monospacedDigit())
            if mode == .comparison, let comparison = point.comparisonAmount {
                Text("Comparison \(comparison.aed) · variance \((point.amount - comparison).aed)")
                    .font(.caption.weight(.medium).monospacedDigit()).foregroundStyle(.secondary)
            }
            HStack(spacing: 8) { Text("\(point.transactions) transactions"); Text(change?.signedPercent ?? "No MoM") }
                .font(.caption2).foregroundStyle(.secondary)
        }
        .padding(10).background(MonetaTheme.panel, in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(MonetaTheme.line)).shadow(color: .black.opacity(0.12), radius: 10, y: 4)
    }
}

private struct DriverHeadline: View {
    let summary: DriverSummary
    let comparisonLabel: String

    var body: some View {
        HStack(spacing: 0) {
            metric("Selected spend", summary.current.aed, tone: MonetaTheme.forest)
            Divider().frame(height: 46)
            metric(comparisonLabel, summary.previous.aed, tone: MonetaTheme.muted)
            Divider().frame(height: 46)
            metric("Movement", summary.delta.aed, supporting: summary.pct?.signedPercent ?? "New in period", tone: summary.delta >= 0 ? MonetaTheme.coral : MonetaTheme.teal)
            Divider().frame(height: 46)
            metric("Transactions", summary.transactions.formatted(), supporting: "\(summary.previousTransactions) in comparison", tone: MonetaTheme.amber)
        }
        .padding(.vertical, 14)
        .background(MonetaTheme.panel, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(MonetaTheme.line))
    }

    private func metric(_ label: String, _ value: String, supporting: String? = nil, tone: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label.uppercased()).font(.caption2.monospaced()).foregroundStyle(.secondary)
            Text(value).font(.title3.bold().monospacedDigit()).foregroundStyle(tone)
            if let supporting { Text(supporting).font(.caption.monospacedDigit()).foregroundStyle(.secondary) }
        }
        .frame(maxWidth: .infinity, minHeight: 62, alignment: .leading)
        .padding(.horizontal, 16)
    }
}

private struct DriverDialSlice: Identifiable {
    let id: String
    let name: String
    let current: Double
    let share: Double
    let node: DriverNode?
}

private struct DriverDial: View {
    let nodes: [DriverNode]
    let summary: DriverSummary
    let scopeName: String
    let childLevel: String
    let selectedID: String?
    let onSelect: (DriverNode) -> Void
    @State private var selectedAngle: Double?
    @State private var previewNodeID: String?

    private let residualTargetPercent = 1.0
    private let palette = MonetaTheme.chartPalette
    private var positiveNodes: [DriverNode] { nodes.filter { $0.current > 0 }.sorted { $0.current > $1.current } }
    private var shownNodes: [DriverNode] {
        let denominator = max(summary.current, 0.01)
        var included: Set<String> = []
        var namedAmount = 0.0
        for node in positiveNodes {
            let residualPercent = max(0, summary.current - namedAmount) / denominator * 100
            if !included.isEmpty && residualPercent <= residualTargetPercent { break }
            included.insert(node.id)
            namedAmount += node.current
        }
        for node in positiveNodes where requiresExplicitVisibility(node) && !included.contains(node.id) {
            included.insert(node.id)
        }
        return positiveNodes.filter { included.contains($0.id) }
    }
    private var residualAmount: Double { max(0, summary.current - shownNodes.reduce(0) { $0 + $1.current }) }
    private var residualShare: Double { summary.current > 0 ? residualAmount / summary.current * 100 : 0 }
    private var residualCount: Int { max(0, positiveNodes.count - shownNodes.count) }
    private var residualLabel: String {
        guard residualCount > 0 else { return "Unreconciled spend" }
        return "Remaining \(residualCount) \(pluralizedLevel(residualCount).lowercased())"
    }
    private var slices: [DriverDialSlice] {
        let denominator = max(summary.current, 0.01)
        var result = shownNodes.map { node in
            DriverDialSlice(id: node.id, name: node.name, current: node.current, share: node.current / denominator * 100, node: node)
        }
        if residualAmount > 0.02 {
            result.append(DriverDialSlice(id: "residual|\(scopeName)", name: residualLabel, current: residualAmount, share: residualShare, node: nil))
        }
        return result
    }
    private var levelPlural: String {
        pluralizedLevel(positiveNodes.count)
    }
    private var usesRankedBars: Bool { positiveNodes.count > 8 }
    private var maxCurrent: Double { max(positiveNodes.first?.current ?? 0, 0.01) }
    private func pluralizedLevel(_ count: Int) -> String {
        guard count != 1 else { return childLevel }
        switch childLevel {
        case "Category": return "Categories"
        case "Subcategory": return "Subcategories"
        default: return "\(childLevel)s"
        }
    }
    private func requiresExplicitVisibility(_ node: DriverNode) -> Bool {
        let label = node.name.lowercased()
        return ["unknown", "unidentified", "uncategorized", "uncategorised", "needs review", "miscellaneous", "other"].contains { label.contains($0) }
    }

    var body: some View {
        Panel(
            "Where it went",
            subtitle: usesRankedBars
                ? "Ranked \(levelPlural.lowercased()) inside \(scopeName). Every item is shown by name; select any row to drill."
                : "\(levelPlural) inside \(scopeName). \(String(format: "%.1f", 100 - residualShare))% is shown by name."
        ) {
            if usesRankedBars {
                rankedBars
            } else {
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .center, spacing: 28) { dial; legend }
                    VStack(alignment: .leading, spacing: 18) { dial; legend }
                }
            }
        }
    }

    private var rankedBars: some View {
        ScrollView(.vertical, showsIndicators: true) {
            LazyVStack(spacing: 2) {
                ForEach(Array(positiveNodes.enumerated()), id: \.element.id) { index, node in
                    Button { onSelect(node) } label: {
                        HStack(spacing: 12) {
                            Text(String(format: "%02d", index + 1))
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                                .frame(width: 24, alignment: .trailing)
                            VStack(alignment: .leading, spacing: 7) {
                                Text(node.name).font(.callout.weight(.semibold)).lineLimit(1)
                                GeometryReader { geometry in
                                    Capsule().fill(MonetaTheme.line)
                                        .overlay(alignment: .leading) {
                                            Capsule()
                                                .fill(palette[index % palette.count])
                                                .frame(width: max(3, geometry.size.width * node.current / maxCurrent))
                                        }
                                }
                                .frame(height: 6)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            VStack(alignment: .trailing, spacing: 2) {
                                Text(node.current.aed).font(.callout.weight(.semibold).monospacedDigit())
                                Text("\(node.current / max(summary.current, 0.01) * 100, specifier: "%.1f")%")
                                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                            }
                            Text(node.delta.aed)
                                .font(.caption.weight(.semibold).monospacedDigit())
                                .foregroundStyle(node.delta >= 0 ? MonetaTheme.coral : MonetaTheme.teal)
                                .frame(width: 86, alignment: .trailing)
                        }
                        .padding(.horizontal, 10)
                        .frame(minHeight: 56)
                        .background(selectedID == node.id ? MonetaTheme.amber.opacity(0.11) : Color.clear, in: RoundedRectangle(cornerRadius: 9))
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Rank \(index + 1), \(node.name), \(node.current.aed), \(node.current / max(summary.current, 0.01) * 100, specifier: "%.1f") percent, change \(node.delta.aed)")
                }
            }
        }
        .frame(maxHeight: 520)
    }

    private var dial: some View {
        ZStack {
            Chart(Array(slices.enumerated()), id: \.element.id) { index, slice in
                SectorMark(
                    angle: .value("Spend", slice.current),
                    innerRadius: .ratio(0.62),
                    angularInset: 1.8
                )
                .cornerRadius(4)
                .foregroundStyle(slice.node == nil ? Color.secondary.opacity(0.22) : palette[index % palette.count])
                .opacity(activeNodeID == nil || activeNodeID == slice.node?.id ? 1 : 0.38)
            }
            .chartAngleSelection(value: $selectedAngle)
            .onChange(of: selectedAngle) { _, value in
                previewNodeID = value.flatMap { slice(at: $0)?.node?.id }
            }
            .simultaneousGesture(TapGesture().onEnded {
                guard let value = selectedAngle, let node = slice(at: value)?.node else { return }
                onSelect(node)
            })
            VStack(spacing: 3) {
                Text(activeSlice?.name ?? scopeName).font(.caption.weight(.semibold)).foregroundStyle(.secondary).lineLimit(1)
                Text((activeSlice?.current ?? summary.current).aed).font(.title2.bold().monospacedDigit())
                Text(activeSlice.map { "\($0.share, specifier: "%.1f")% of \(scopeName)" } ?? "\(positiveNodes.count) \(levelPlural.lowercased())")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .frame(width: 140)
            .allowsHitTesting(false)
        }
        .frame(minWidth: 300, idealWidth: 340, maxWidth: 390, minHeight: 300)
        .animation(.easeOut(duration: 0.18), value: selectedID)
        .onChange(of: scopeName) { _, _ in selectedAngle = nil; previewNodeID = nil }
        .accessibilityLabel("\(childLevel) composition inside \(scopeName). Select a segment to inspect its exact amount and share.")
    }

    private var legend: some View {
        ScrollView(.vertical, showsIndicators: true) {
            LazyVStack(spacing: 2) {
                ForEach(Array(slices.enumerated()), id: \.element.id) { index, slice in
                    if let node = slice.node {
                        Button { onSelect(node) } label: {
                            legendRow(slice, color: palette[index % palette.count], selected: selectedID == node.id)
                        }
                        .buttonStyle(.plain)
                    } else {
                        legendRow(slice, color: Color.secondary.opacity(0.22), selected: false)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: 360)
    }

    private func legendRow(_ slice: DriverDialSlice, color: Color, selected: Bool) -> some View {
        HStack(spacing: 10) {
            Circle().fill(color).frame(width: 10, height: 10)
            Text(slice.name).font(.callout.weight(.semibold)).lineLimit(1)
            Spacer(minLength: 16)
            VStack(alignment: .trailing, spacing: 2) {
                Text(slice.current.aed).font(.callout.weight(.semibold).monospacedDigit())
                Text("\(slice.share, specifier: "%.1f")%").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 10)
        .frame(minHeight: 48)
        .background(selected ? MonetaTheme.amber.opacity(0.11) : Color.clear, in: RoundedRectangle(cornerRadius: 9))
        .contentShape(Rectangle())
    }

    private var selectedSlice: DriverDialSlice? { slices.first { $0.node?.id == selectedID } }
    private var previewSlice: DriverDialSlice? { slices.first { $0.node?.id == previewNodeID } }
    private var activeSlice: DriverDialSlice? { selectedSlice ?? previewSlice }
    private var activeNodeID: String? { selectedID ?? previewNodeID }
    private func slice(at angleValue: Double) -> DriverDialSlice? {
        var cumulative = 0.0
        for slice in slices {
            cumulative += slice.current
            if angleValue <= cumulative { return slice }
        }
        return slices.last
    }
}

private struct DriverChangeView: View {
    let nodes: [DriverNode]
    let meta: AnalyticsMeta
    let selectedID: String?
    let onSelect: (DriverNode) -> Void
    @State private var focusedID: String?

    private var visibleNodes: [DriverNode] {
        Array(nodes.sorted { abs($0.delta) > abs($1.delta) }.prefix(10))
    }

    var body: some View {
        Panel("What changed", subtitle: "\(meta.periodLabel) compared with \(meta.previousPeriodLabel). Hover for exact values, select to inspect.") {
            if !meta.baselineComplete {
                ContentUnavailableView("Comparison unavailable", systemImage: "calendar.badge.exclamationmark", description: Text("The ledger does not contain a complete \(meta.comparisonLabel.lowercased()) baseline."))
                    .frame(minHeight: 340)
            } else {
                Chart(visibleNodes) { node in
                    BarMark(x: .value("Change", node.delta), y: .value("Driver", node.name))
                        .foregroundStyle(node.delta >= 0 ? MonetaTheme.coral : MonetaTheme.teal)
                        .opacity(activeID == nil || activeID == node.id ? 1 : 0.28)
                        .annotation(position: node.delta >= 0 ? .trailing : .leading) {
                            Text(node.delta.aed).font(.caption.weight(.semibold).monospacedDigit())
                        }
                    RuleMark(x: .value("No change", 0)).foregroundStyle(.secondary.opacity(0.45))
                    if activeID == node.id {
                        RuleMark(y: .value("Focused driver", node.name)).foregroundStyle(MonetaTheme.forest.opacity(0.28))
                            .annotation(position: .overlay, alignment: .topTrailing) {
                                VStack(alignment: .trailing, spacing: 3) {
                                    Text(node.name).font(.caption.weight(.semibold))
                                    Text("\(node.previous.aed)  →  \(node.current.aed)").font(.caption.monospacedDigit())
                                    Text(node.pct?.signedPercent ?? "New in period").font(.caption2).foregroundStyle(.secondary)
                                }
                                .padding(9)
                                .background(MonetaTheme.panel, in: RoundedRectangle(cornerRadius: 9))
                                .overlay(RoundedRectangle(cornerRadius: 9).stroke(MonetaTheme.line))
                                .shadow(color: .black.opacity(0.1), radius: 8, y: 3)
                            }
                    }
                }
                .chartXAxis { AxisMarks(position: .bottom) { AxisGridLine(); AxisValueLabel() } }
                .chartOverlay { proxy in
                    GeometryReader { geometry in
                        Rectangle().fill(.clear).contentShape(Rectangle())
                            .onContinuousHover { phase in
                                switch phase {
                                case .active(let location): focusedID = nearest(at: location, proxy: proxy, geometry: geometry)?.id
                                case .ended: focusedID = nil
                                }
                            }
                            .gesture(SpatialTapGesture().onEnded { event in
                                if let node = nearest(at: event.location, proxy: proxy, geometry: geometry) { onSelect(node) }
                            })
                    }
                }
                .frame(minHeight: 390)
                .animation(.easeOut(duration: 0.16), value: activeID)
            }
        }
    }

    private var activeID: String? { focusedID ?? selectedID }
    private func nearest(at location: CGPoint, proxy: ChartProxy, geometry: GeometryProxy) -> DriverNode? {
        guard let frame = proxy.plotFrame else { return nil }
        let plot = geometry[frame]
        guard plot.contains(location) else { return nil }
        let localY = location.y - plot.minY
        return visibleNodes.min { left, right in
            abs((proxy.position(forY: left.name) ?? 0) - localY) < abs((proxy.position(forY: right.name) ?? 0) - localY)
        }
    }
}

private struct DriverQuickRead: View {
    let summary: DriverSummary
    let nodes: [DriverNode]
    let selected: DriverNode?
    let onDrill: (DriverNode) -> Void

    private var biggestIncrease: DriverNode? { nodes.filter { $0.delta > 0 }.max { $0.delta < $1.delta } }
    private var biggestDecrease: DriverNode? { nodes.filter { $0.delta < 0 }.min { $0.delta < $1.delta } }

    var body: some View {
        Panel("Read the signal", subtitle: "The shortest path from headline movement to evidence") {
            VStack(alignment: .leading, spacing: 12) {
                if let selected {
                    Text(selected.name).font(.title3.bold())
                    Text("\(selected.current.aed), \(relativeShare(selected), specifier: "%.1f")% of selected spend")
                        .font(.headline.monospacedDigit()).foregroundStyle(MonetaTheme.forest)
                    Text("\(selected.delta >= 0 ? "Up" : "Down") \(abs(selected.delta).aed) versus the comparison, across \(selected.transactions) transactions.")
                        .font(.callout).foregroundStyle(.secondary)
                    Button(drillLabel(selected), systemImage: "arrow.down.right.circle.fill") { onDrill(selected) }
                        .buttonStyle(.borderedProminent).tint(MonetaTheme.brandFill).controlSize(.large)
                } else {
                    if let increase = biggestIncrease {
                        signal("Largest increase", increase.name, increase.delta.aed, MonetaTheme.coral)
                    }
                    if let decrease = biggestDecrease {
                        signal("Largest reduction", decrease.name, decrease.delta.aed, MonetaTheme.teal)
                    }
                    Text("Select a segment, bar or matrix row to reveal its exact transactions.")
                        .font(.callout).foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, minHeight: 240, alignment: .topLeading)
        }
    }

    private func signal(_ label: String, _ name: String, _ value: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label.uppercased()).font(.caption2.monospaced()).foregroundStyle(.secondary)
            HStack { Text(name).font(.headline); Spacer(); Text(value).font(.headline.monospacedDigit()).foregroundStyle(color) }
        }
        .padding(.vertical, 8)
    }

    private func relativeShare(_ node: DriverNode) -> Double { summary.current > 0 ? node.current / summary.current * 100 : 0 }
    private func drillLabel(_ node: DriverNode) -> String {
        switch node.level {
        case "category": "Show subcategories"
        case "subcategory": "Show merchants"
        default: "Open transactions"
        }
    }
}

private struct DriverMatrix: View {
    let nodes: [DriverNode]
    let selectedID: String?
    let onSelect: (DriverNode) -> Void
    @State private var expanded: Set<String> = []

    var body: some View {
        Panel("Spend path", subtitle: "Expand category → subcategory → merchant, then open the supporting transactions.") {
            ScrollView(.horizontal, showsIndicators: true) {
                VStack(spacing: 0) {
                    matrixHeader
                    Divider()
                    ForEach(nodes) { node in
                        DriverMatrixRow(node: node, depth: 0, selectedID: selectedID, expanded: $expanded, onSelect: onSelect)
                    }
                }
                .frame(minWidth: 980)
            }
        }
    }

    private var matrixHeader: some View {
        HStack(spacing: 10) {
            Text("Driver").frame(maxWidth: .infinity, alignment: .leading)
            Text("Current").frame(width: 110, alignment: .trailing)
            Text("Comparison").frame(width: 110, alignment: .trailing)
            Text("Change").frame(width: 100, alignment: .trailing)
            Text("Change %").frame(width: 82, alignment: .trailing)
            Text("Share").frame(width: 70, alignment: .trailing)
            Text("Count").frame(width: 60, alignment: .trailing)
            Text("Trend").frame(width: 90, alignment: .trailing)
        }
        .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
        .padding(.horizontal, 10).frame(minHeight: 36)
    }
}

private struct DriverMatrixRow: View {
    let node: DriverNode
    let depth: Int
    let selectedID: String?
    @Binding var expanded: Set<String>
    let onSelect: (DriverNode) -> Void

    var body: some View {
        Button {
            onSelect(node)
            if !node.children.isEmpty {
                if expanded.contains(node.id) { expanded.remove(node.id) } else { expanded.insert(node.id) }
            }
        } label: {
            HStack(spacing: 10) {
                HStack(spacing: 7) {
                    Color.clear.frame(width: CGFloat(depth) * 18)
                    Image(systemName: node.children.isEmpty ? "circle.fill" : expanded.contains(node.id) ? "chevron.down" : "chevron.right")
                        .font(node.children.isEmpty ? .system(size: 5) : .caption.weight(.semibold))
                        .foregroundStyle(node.children.isEmpty ? Color.secondary.opacity(0.5) : MonetaTheme.forest)
                        .frame(width: 14)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(node.name).font(.callout.weight(depth == 0 ? .semibold : .regular)).lineLimit(1)
                        Text(node.level.capitalized).font(.caption2).foregroundStyle(.secondary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Text(node.current.aed).frame(width: 110, alignment: .trailing)
                Text(node.previous.aed).frame(width: 110, alignment: .trailing).foregroundStyle(.secondary)
                Text(node.delta.aed).frame(width: 100, alignment: .trailing).foregroundStyle(node.delta >= 0 ? MonetaTheme.coral : MonetaTheme.teal)
                Text(node.pct?.signedPercent ?? "New").frame(width: 82, alignment: .trailing)
                Text("\(node.share, specifier: "%.1f")%").frame(width: 70, alignment: .trailing)
                Text(node.transactions.formatted()).frame(width: 60, alignment: .trailing)
                DriverSparkline(points: node.trend).frame(width: 90, height: 28)
            }
            .font(.callout.monospacedDigit())
            .padding(.horizontal, 10)
            .frame(minHeight: 48)
            .background(selectedID == node.id ? MonetaTheme.amber.opacity(0.12) : Color.clear, in: RoundedRectangle(cornerRadius: 8))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        Divider()
        if expanded.contains(node.id) {
            ForEach(node.children) { child in
                DriverMatrixRow(node: child, depth: depth + 1, selectedID: selectedID, expanded: $expanded, onSelect: onSelect)
            }
        }
    }
}

private struct DriverSparkline: View {
    let points: [TrendPoint]
    var body: some View {
        Chart(points) { point in
            LineMark(x: .value("Month", point.month), y: .value("Spend", point.amount))
                .foregroundStyle(MonetaTheme.forest).lineStyle(.init(lineWidth: 1.6))
        }
        .chartXAxis(.hidden).chartYAxis(.hidden)
        .accessibilityLabel("Driver trend")
    }
}

private struct DriverEvidencePanel: View {
    @EnvironmentObject private var model: AppModel
    let node: DriverNode
    let transactions: [TransactionItem]

    private var evidence: [TransactionItem] {
        transactions.filter { transaction in
            guard node.path.first == transaction.category else { return false }
            if node.path.count > 1 && node.path[1] != transaction.subcategory { return false }
            if node.path.count > 2 && node.path[2] != transaction.merchantClean { return false }
            return true
        }
    }

    var body: some View {
        Panel("Supporting transactions", subtitle: "\(node.path.joined(separator: "  ›  ")) · \(evidence.count) matching entries") {
            VStack(spacing: 0) {
                ForEach(evidence.prefix(10)) { transaction in
                    HStack(spacing: 12) {
                        Text(transaction.date).font(.caption.monospacedDigit()).foregroundStyle(.secondary).frame(width: 92, alignment: .leading)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(transaction.merchantClean).font(.callout.weight(.semibold)).lineLimit(1)
                            Text("\(transaction.subcategory) · \(transaction.cardUsed.isEmpty ? transaction.source : transaction.cardUsed)")
                                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                        Spacer()
                        Text(transaction.amountAed.aed).font(.callout.weight(.semibold).monospacedDigit())
                    }
                    .frame(minHeight: 48)
                    Divider()
                }
                Button("Open all \(evidence.count) transactions", systemImage: "list.bullet.rectangle") { model.drill(node, openTransactions: true) }
                    .buttonStyle(.bordered).controlSize(.large).padding(.top, 12)
            }
        }
    }
}

private struct DriverHierarchyNavigator: View {
    let meta: AnalyticsMeta
    let nextLevel: String
    let selected: DriverNode?
    let onNavigate: ([String]) -> Void
    let onUp: () -> Void
    let onDrill: (DriverNode) -> Void

    private var path: [String] {
        [meta.category, meta.subcategory, meta.merchant].filter { !$0.isEmpty }
    }
    private var crumbs: [(label: String, path: [String])] {
        var result: [(String, [String])] = [("All spending", [])]
        for index in path.indices {
            result.append((path[index], Array(path.prefix(index + 1))))
        }
        return result
    }
    private var upDestination: String {
        path.count > 1 ? path[path.count - 2] : "All spending"
    }
    private var levelLabel: String {
        switch nextLevel {
        case "Category": "Viewing categories"
        case "Subcategory": "Viewing subcategories"
        case "Merchant": "Viewing merchants"
        default: "Viewing \(nextLevel.lowercased())"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Text("DRILL PATH")
                    .font(.caption2.monospaced().weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Text(levelLabel)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(MonetaTheme.forest)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(MonetaTheme.forest.opacity(0.09), in: Capsule())
            }

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 4) {
                    ForEach(Array(crumbs.enumerated()), id: \.offset) { index, crumb in
                        if index > 0 {
                            Image(systemName: "chevron.right")
                                .font(.caption2.weight(.bold))
                                .foregroundStyle(.tertiary)
                                .accessibilityHidden(true)
                        }
                        Button { onNavigate(crumb.path) } label: {
                            Text(crumb.label)
                                .font(.callout.weight(index == crumbs.count - 1 ? .semibold : .medium))
                                .lineLimit(1)
                                .padding(.horizontal, 10)
                                .frame(minHeight: 44)
                                .background(index == crumbs.count - 1 ? MonetaTheme.amber.opacity(0.13) : Color.clear, in: RoundedRectangle(cornerRadius: 9))
                        }
                        .buttonStyle(.plain)
                        .disabled(index == crumbs.count - 1)
                        .accessibilityLabel(index == crumbs.count - 1 ? "Current level, \(crumb.label)" : "Return to \(crumb.label)")
                    }
                }
            }

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 10) {
                    hierarchyButtons
                    Spacer(minLength: 12)
                    instruction
                }
                VStack(alignment: .leading, spacing: 10) {
                    instruction
                    hierarchyButtons
                }
            }
        }
        .padding(12)
        .background(MonetaTheme.panel, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(MonetaTheme.line))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Spend driver hierarchy")
    }

    @ViewBuilder private var hierarchyButtons: some View {
        if !path.isEmpty {
            Button("Up to \(upDestination)", systemImage: "arrow.up.left") { onUp() }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .frame(minHeight: 44)
                .help("Move up exactly one level to \(upDestination)")
        }
        if let selected {
            Button(drillLabel(selected), systemImage: selected.level == "merchant" ? "list.bullet.rectangle" : "arrow.down.right") { onDrill(selected) }
                .buttonStyle(.borderedProminent)
                .tint(MonetaTheme.brandFill)
                .controlSize(.large)
                .frame(minHeight: 44)
        }
    }

    private var instruction: some View {
        Text(selected == nil ? "Select any slice or row to reveal the next level." : "Selected: \(selected?.name ?? "")")
            .font(.callout)
            .foregroundStyle(.secondary)
            .lineLimit(2)
    }

    private func drillLabel(_ node: DriverNode) -> String {
        switch node.level {
        case "category": "Show subcategories in \(node.name)"
        case "subcategory": "Show merchants in \(node.name)"
        default: "Open \(node.name) transactions"
        }
    }
}

struct DriversView: View {
    @EnvironmentObject private var model: AppModel
    @State private var mode: DriverDisplayMode = .composition
    @State private var selectedNodeID: String?

    var body: some View {
        ScrollView {
            if let data = model.analytics {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .top, spacing: 16) {
                        ScopeHeader(title: "Spend drivers", subtitle: "\(model.scopeTitle) · compared with \(data.meta.previousPeriodLabel)")
                        Spacer()
                        Picker("Analysis", selection: $mode) {
                            ForEach(DriverDisplayMode.allCases) { Text($0.rawValue).tag($0) }
                        }
                        .pickerStyle(.segmented).frame(width: 320)
                    }
                    DriverHierarchyNavigator(
                        meta: data.meta,
                        nextLevel: nextLevel,
                        selected: selectedNode,
                        onNavigate: { model.navigateHierarchy(to: $0) },
                        onUp: { model.drillUp() },
                        onDrill: { model.drill($0) }
                    )
                    DriverHeadline(summary: data.driverSummary, comparisonLabel: data.meta.comparisonLabel)
                    if mode == .composition {
                        ViewThatFits(in: .horizontal) {
                            HStack(alignment: .top, spacing: 16) {
                                DriverDial(nodes: scopeNodes, summary: data.driverSummary, scopeName: scopeName, childLevel: nextLevel, selectedID: selectedNodeID, onSelect: select)
                                    .frame(maxWidth: .infinity)
                                DriverQuickRead(summary: data.driverSummary, nodes: scopeNodes, selected: selectedNode, onDrill: { model.drill($0) })
                                    .frame(width: 390)
                            }
                            VStack(alignment: .leading, spacing: 16) {
                                DriverDial(nodes: scopeNodes, summary: data.driverSummary, scopeName: scopeName, childLevel: nextLevel, selectedID: selectedNodeID, onSelect: select)
                                DriverQuickRead(summary: data.driverSummary, nodes: scopeNodes, selected: selectedNode, onDrill: { model.drill($0) })
                            }
                        }
                    } else {
                        DriverChangeView(nodes: scopeNodes, meta: data.meta, selectedID: selectedNodeID, onSelect: select)
                    }
                    DriverMatrix(nodes: data.driverRows, selectedID: selectedNodeID, onSelect: select)
                    if let selectedNode {
                        DriverEvidencePanel(node: selectedNode, transactions: data.transactions)
                    }
                }
                .padding(20)
                .onChange(of: scopeKey) { _, _ in selectedNodeID = nil }
            }
        }
    }

    private var scopeKey: String {
        guard let meta = model.analytics?.meta else { return "" }
        return [meta.periodLabel, meta.category, meta.subcategory, meta.merchant].joined(separator: "|")
    }
    private var scopeParent: DriverNode? {
        guard let data = model.analytics else { return nil }
        if !data.meta.subcategory.isEmpty {
            return find(path: [data.meta.category, data.meta.subcategory], in: data.driverRows)
        }
        if !data.meta.category.isEmpty {
            return find(path: [data.meta.category], in: data.driverRows)
        }
        return nil
    }
    private var scopeNodes: [DriverNode] {
        if let scopeParent, !scopeParent.children.isEmpty { return scopeParent.children }
        return model.analytics?.driverRows ?? []
    }
    private var scopeName: String { scopeParent?.name ?? "All spending" }
    private var nextLevel: String {
        switch scopeParent?.level {
        case "category": "Subcategory"
        case "subcategory": "Merchant"
        default: "Category"
        }
    }

    private var selectedNode: DriverNode? {
        guard let selectedNodeID, let nodes = model.analytics?.driverRows else { return nil }
        return find(selectedNodeID, in: nodes)
    }
    private func select(_ node: DriverNode) {
        if selectedNodeID == node.id {
            model.drill(node)
        } else {
            selectedNodeID = node.id
        }
    }
    private func find(_ id: String, in nodes: [DriverNode]) -> DriverNode? {
        for node in nodes {
            if node.id == id { return node }
            if let child = find(id, in: node.children) { return child }
        }
        return nil
    }
    private func find(path: [String], in nodes: [DriverNode]) -> DriverNode? {
        for node in nodes {
            if node.path == path { return node }
            if let child = find(path: path, in: node.children) { return child }
        }
        return nil
    }
}

struct TransactionsView: View {
    @EnvironmentObject private var model: AppModel
    @State private var query = ""

    private var rows: [TransactionItem] {
        let source = model.analytics?.transactions ?? []
        guard !query.isEmpty else { return source }
        return source.filter { [$0.merchantClean, $0.category, $0.subcategory, $0.detail, $0.source].contains { $0.localizedCaseInsensitiveContains(query) } }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ScopeHeader(title: "Transactions", subtitle: "\(rows.count) rows behind \(model.scopeTitle)")
            Table(rows) {
                TableColumn("Date", value: \.date).width(min: 90, ideal: 105)
                TableColumn("Merchant", value: \.merchantClean).width(min: 160, ideal: 240)
                TableColumn("Category") { Text($0.category) }.width(min: 140, ideal: 180)
                TableColumn("Subcategory") { Text($0.subcategory) }.width(min: 140, ideal: 180)
                TableColumn("Source") { Text($0.cardUsed.isEmpty ? $0.source : $0.cardUsed) }.width(min: 100, ideal: 130)
                TableColumn("Amount") { Text($0.amountAed.aed).fontWeight(.semibold).monospacedDigit().frame(maxWidth: .infinity, alignment: .trailing) }.width(110)
            }
            .searchable(text: $query, prompt: "Merchant, category, source")
        }
        .padding(20)
    }
}

struct CommitmentsView: View {
    @EnvironmentObject private var model: AppModel
    @State private var showCashEntry = false
    @State private var editingCommitment: Commitment?

    private var uniqueUpcoming: [UpcomingPayment] {
        guard let upcoming = model.commitments?.upcoming else { return [] }
        var seen = Set<String>()
        return upcoming.filter { seen.insert($0.id).inserted }
    }

    var body: some View {
        ScrollView {
            if let data = model.commitments {
                VStack(alignment: .leading, spacing: 16) {
                    HStack {
                        ScopeHeader(title: "Commitments", subtitle: "Planned cash obligations, shown at monthly level")
                        Button("Log cash expense", systemImage: "plus.circle.fill") { showCashEntry = true }.buttonStyle(.borderedProminent).tint(MonetaTheme.brandFill)
                    }
                    HStack(spacing: 12) {
                        CountTile(title: "Monthly equivalent", value: data.monthlyEquivalent.aed, supporting: "Normalized monthly view")
                        CountTile(title: "12-month commitment", value: data.annualTotal.aed, supporting: "Planned, not counted as spent")
                    }
                    Panel("Recurring commitments") {
                        ForEach(data.commitments) { item in
                            HStack {
                                VStack(alignment: .leading) { Text(item.name).fontWeight(.semibold); Text("\(item.category) › \(item.subcategory)").font(.caption).foregroundStyle(.secondary) }
                                Spacer(); Text(item.paymentAmount.aed).font(.title3.weight(.semibold).monospacedDigit()); Text("/ month").font(.caption).foregroundStyle(.secondary)
                                Button("Edit", systemImage: "pencil") { editingCommitment = item }
                                    .buttonStyle(.bordered)
                            }.padding(.vertical, 8); Divider()
                        }
                    }
                    Panel("Upcoming payments") {
                        ForEach(uniqueUpcoming.prefix(12)) { item in
                            HStack { Text(item.dueDate).font(.callout.monospaced()); Text(item.name); Spacer(); Text(item.amount.aed).fontWeight(.semibold).monospacedDigit() }.padding(.vertical, 7); Divider()
                        }
                    }
                }.padding(20)
            }
        }
        .sheet(isPresented: $showCashEntry) { CashEntryView(isPresented: $showCashEntry) }
        .sheet(item: $editingCommitment) { item in CommitmentEditView(commitment: item, isPresented: Binding(get: { editingCommitment != nil }, set: { if !$0 { editingCommitment = nil } })) }
    }
}

struct CommitmentEditView: View {
    @EnvironmentObject private var model: AppModel
    let commitment: Commitment
    @Binding var isPresented: Bool
    @State private var monthlyAmount: String
    @State private var startDate: Date
    @State private var endDate: Date
    @State private var active: Bool
    @State private var status = "Changes affect the plan only; they do not create an expense transaction."
    @State private var isSaving = false

    init(commitment: Commitment, isPresented: Binding<Bool>) {
        self.commitment = commitment
        self._isPresented = isPresented
        _monthlyAmount = State(initialValue: String(format: "%.2f", commitment.paymentAmount))
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        _startDate = State(initialValue: formatter.date(from: commitment.startDate) ?? Date())
        _endDate = State(initialValue: formatter.date(from: commitment.endDate) ?? Date())
        _active = State(initialValue: commitment.active)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Edit \(commitment.name)").font(.title2.bold())
            Text("Moneta stores commitments monthly and recalculates the 12-month plan automatically.").foregroundStyle(.secondary)
            Form {
                TextField("Monthly amount (AED)", text: $monthlyAmount)
                DatePicker("Starts", selection: $startDate, displayedComponents: .date)
                DatePicker("Ends", selection: $endDate, in: startDate..., displayedComponents: .date)
                Toggle("Include in active commitments", isOn: $active)
            }
            Text(status).font(.caption).foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("Cancel") { isPresented = false }
                Button(isSaving ? "Saving…" : "Save changes") { save() }
                    .buttonStyle(.borderedProminent).tint(MonetaTheme.brandFill)
                    .disabled(isSaving || (Double(monthlyAmount) ?? 0) <= 0)
            }
        }
        .padding(24)
        .frame(width: 520)
    }

    private func save() {
        guard let amount = Double(monthlyAmount), amount > 0 else { return }
        isSaving = true
        status = "Updating the commitment…"
        let payload = CommitmentUpdatePayload(
            monthlyAmount: amount,
            startDate: startDate.formatted(.iso8601.year().month().day()),
            endDate: endDate.formatted(.iso8601.year().month().day()),
            active: active
        )
        Task {
            do {
                try await model.updateCommitment(id: commitment.id, payload: payload)
                status = "Commitment updated."
                try? await Task.sleep(for: .milliseconds(500))
                isPresented = false
            } catch { status = error.localizedDescription }
            isSaving = false
        }
    }
}

struct CashEntryView: View {
    @EnvironmentObject private var model: AppModel
    @Binding var isPresented: Bool
    @State private var amount = ""
    @State private var merchant = ""
    @State private var date = Date()
    @State private var category = ""
    @State private var subcategory = ""
    @State private var notes = ""
    @State private var status = "Unknown merchants are safely queued for review."
    @State private var isSaving = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Log cash expense").font(.title2.bold())
            Text("This writes to the live ledger using the same classification safeguards as the existing dashboard.").foregroundStyle(.secondary)
            Form {
                TextField("Amount (AED)", text: $amount)
                DatePicker("Date", selection: $date, displayedComponents: .date)
                TextField("Merchant or description", text: $merchant)
                Picker("Category", selection: $category) { Text("Auto-detect").tag(""); ForEach(model.analytics?.meta.categories ?? [], id: \.self) { Text($0).tag($0) } }
                Picker("Subcategory", selection: $subcategory) { Text("Auto-detect").tag(""); ForEach(model.analytics?.meta.taxonomy[category] ?? [], id: \.self) { Text($0).tag($0) } }
                TextField("Optional note", text: $notes)
            }
            Text(status).font(.caption).foregroundStyle(.secondary)
            HStack { Spacer(); Button("Cancel") { isPresented = false }; Button(isSaving ? "Saving…" : "Add expense") { save() }.buttonStyle(.borderedProminent).tint(MonetaTheme.brandFill).disabled(isSaving || Double(amount) == nil || merchant.trimmingCharacters(in: .whitespaces).isEmpty) }
        }
        .padding(24)
        .frame(width: 520)
    }

    private func save() {
        isSaving = true
        status = "Writing to the live ledger…"
        let dateText = date.formatted(.iso8601.year().month().day())
        let payload = CashEntryPayload(amount: amount, merchant: merchant, date: dateText, category: category, subcategory: subcategory, notes: notes)
        Task {
            do {
                let response = try await model.logCash(payload)
                status = "\(response.amount.aed) at \(response.merchant) was added."
                try? await Task.sleep(for: .milliseconds(700))
                isPresented = false
            } catch { status = error.localizedDescription }
            isSaving = false
        }
    }
}

struct HealthView: View {
    @EnvironmentObject private var model: AppModel

    private func presentation(for status: String) -> (icon: String, color: Color, label: String) {
        switch status.lowercased() {
        case "healthy", "ok", "clean", "complete":
            return ("checkmark.circle.fill", MonetaTheme.teal, "Healthy")
        case "watch", "watching", "monitoring":
            return ("eye.circle.fill", MonetaTheme.amber, "Monitoring")
        case "needs_review", "stale", "rate_limited", "unknown", "missing":
            return ("exclamationmark.circle.fill", MonetaTheme.amber, "Action suggested")
        default:
            return ("xmark.octagon.fill", MonetaTheme.coral, "Failed")
        }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                ScopeHeader(title: "Data health", subtitle: "Live evidence from the expense tracker and Hermes reports")
                Panel("System checks") {
                    ForEach(model.health.keys.sorted(), id: \.self) { key in
                        if let item = model.health[key] {
                            let state = presentation(for: item.status)
                            HStack(spacing: 12) {
                                Image(systemName: state.icon).foregroundStyle(state.color)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(item.title ?? key.replacingOccurrences(of: "_", with: " ").capitalized).fontWeight(.semibold)
                                    if let message = item.message { Text(message).font(.caption).foregroundStyle(.secondary) }
                                    Text(item.ageMinutes.map { "Updated \(Int($0)) minutes ago · \(item.generatedAt ?? "timestamp unavailable")" } ?? "Timestamp unavailable")
                                        .font(.caption2).foregroundStyle(.tertiary)
                                }
                                Spacer()
                                Text(state.label.uppercased()).font(.caption2.weight(.bold)).foregroundStyle(state.color)
                            }.padding(.vertical, 8); Divider()
                        }
                    }
                }
                if let message = model.errorMessage { Label(message, systemImage: "exclamationmark.triangle").foregroundStyle(MonetaTheme.coral) }
            }.padding(20)
        }
    }
}
