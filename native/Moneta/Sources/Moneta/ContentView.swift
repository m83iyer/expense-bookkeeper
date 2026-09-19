import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        NavigationSplitView {
            Sidebar()
        } detail: {
            VStack(spacing: 0) {
                if model.page.usesAnalyticalSlicers {
                    SlicerBar()
                    Divider()
                }
                if let message = model.errorMessage, model.analytics != nil {
                    Label("Live refresh paused: \(message)", systemImage: "exclamationmark.triangle.fill")
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(MonetaTheme.coral)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 9)
                        .background(MonetaTheme.coral.opacity(0.08))
                }
                Group {
                    if model.isLoading && model.analytics == nil {
                        LoadingView()
                    } else if let message = model.errorMessage, model.analytics == nil {
                        ErrorView(message: message)
                    } else {
                        workspace
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .background(MonetaTheme.canvas)
        }
        .navigationTitle(model.page.rawValue)
        .task(id: model.scopeRevision) {
            guard model.scopeRevision > 0 else { return }
            await model.refresh(includeSecondary: true)
        }
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                StatusPill(text: model.overallHealth, isHealthy: model.overallHealth == "Connected")
                Button {
                    Task { await model.refresh(includeSecondary: true) }
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
                .keyboardShortcut("r", modifiers: .command)
            }
        }
    }

    @ViewBuilder private var workspace: some View {
        switch model.page {
        case .overview: OverviewView()
        case .insights: InsightsHubView()
        case .trends: TrendsView()
        case .drivers: DriversView()
        case .transactions: TransactionsView()
        case .commitments: CommitmentsView()
        case .health: HealthView()
        }
    }
}

private struct Sidebar: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        List(selection: $model.page) {
            Section {
                ForEach(WorkspacePage.allCases) { page in
                    Label(page.rawValue, systemImage: page.icon).tag(page)
                }
            }
        }
        .navigationTitle("Moneta")
        .safeAreaInset(edge: .bottom) {
            VStack(alignment: .leading, spacing: 5) {
                Text("PRIVATE LEDGER").font(.caption2.monospaced()).foregroundStyle(.secondary)
                Text(model.analytics?.meta.lastUpdated ?? "Waiting for live data")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
        }
    }
}

private struct SlicerBar: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        HStack(spacing: 12) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 12) {
                    Image(systemName: "line.3.horizontal.decrease.circle.fill")
                        .foregroundStyle(MonetaTheme.forest)
                        .font(.title3)

            Menu {
                Section("Selection") {
                    Button("Select all", systemImage: "checkmark.square.fill") { model.selectAllYears() }
                    Button("Clear all", systemImage: "xmark.square") { model.clearAllCalendarMonths() }
                }
                Section("Years") {
                    ForEach(model.availableYears, id: \.self) { year in
                        Button { model.toggleYear(year) } label: {
                            Label(year, systemImage: model.yearIsSelected(year) ? "checkmark.square.fill" : "square")
                        }
                    }
                }
            } label: { SlicerLabel(title: "Year", value: model.selectedYearLabel) }

            Menu {
                Section("Selection") {
                    Button("Select all", systemImage: "checkmark.square.fill") { model.selectAllMonthsForSelectedYear() }
                    Button("Clear all", systemImage: "xmark.square") { model.clearAllCalendarMonths() }
                }
                Section("Months in \(model.selectedYear)") {
                    ForEach(model.availableMonthsForSelectedYear, id: \.key) { month in
                        Button { model.toggleCalendarMonth(month.key) } label: {
                            Label(month.label, systemImage: model.selectedMonths.contains(month.key) ? "checkmark.square.fill" : "square")
                        }
                    }
                }
            } label: { SlicerLabel(title: "Month", value: model.selectedMonthLabel) }

            Button { model.moveMonth(-1) } label: { Image(systemName: "chevron.left").frame(minWidth: 44, minHeight: 44) }
                .disabled(!model.canMoveToPreviousMonth)
                .help("Move the analysis window one month back")
                .accessibilityLabel("Previous month")
            Button { model.moveMonth(1) } label: { Image(systemName: "chevron.right").frame(minWidth: 44, minHeight: 44) }
                .disabled(!model.canMoveToNextMonth)
                .help("Move the analysis window one month forward")
                .accessibilityLabel("Next month")

            Menu {
                Section("Rolling period") {
                    ForEach([1, 3, 6, 12, 24], id: \.self) { range in
                        Button(range == 1 ? "Selected month" : "Last \(range) months") { model.selectRange(range) }
                    }
                }
            } label: {
                SlicerLabel(title: "Period", value: model.selectedPeriodLabel)
            }

            Menu {
                Section("Selection") {
                    Button("Select all", systemImage: "checkmark.square.fill") { model.selectAllCategories() }
                    Button("Clear all", systemImage: "xmark.square") { model.clearAllCategories() }
                }
                Section("Categories") {
                    ForEach(model.analytics?.meta.categories ?? [], id: \.self) { value in
                        Button { model.toggleCategory(value) } label: {
                            Label(value, systemImage: categoryValues.contains(value) ? "checkmark.square.fill" : "square")
                        }
                    }
                }
            } label: { SlicerLabel(title: "Category", value: model.categoryLabel) }

                    Menu {
                        Section("Selection") {
                            Button("Select all", systemImage: "checkmark.square.fill") { model.selectAllSubcategories() }
                            Button("Clear all", systemImage: "xmark.square") { model.clearAllSubcategories() }
                        }
                        Section("Subcategories") {
                            ForEach(model.analytics?.meta.subcategories ?? [], id: \.self) { value in
                                Button { model.toggleSubcategory(value) } label: {
                                    Label(value, systemImage: subcategoryValues.contains(value) ? "checkmark.square.fill" : "square")
                                }
                            }
                        }
                    } label: { SlicerLabel(title: "Subcategory", value: model.subcategoryLabel) }

                    Menu {
                        Section("Selection") {
                            Button("Select all", systemImage: "checkmark.square.fill") { model.selectAllMerchants() }
                            Button("Clear all", systemImage: "xmark.square") { model.clearAllMerchants() }
                        }
                        Section("Merchants") {
                            ForEach(model.analytics?.meta.merchants ?? [], id: \.self) { value in
                                Button { model.toggleMerchant(value) } label: {
                                    Label(value, systemImage: merchantValues.contains(value) ? "checkmark.square.fill" : "square")
                                }
                            }
                        }
                    } label: { SlicerLabel(title: "Merchant", value: model.merchantLabel) }

                    Menu {
                        ForEach(ComparisonMode.allCases) { value in
                            Button { model.selectComparison(value) } label: {
                                Label(value.rawValue, systemImage: model.comparison == value ? "checkmark" : "circle")
                            }
                        }
                    } label: { SlicerLabel(title: "Compare", value: model.comparison.rawValue) }
                }
            }

            if model.isRefreshingScope {
                ProgressView()
                    .controlSize(.small)
                    .accessibilityLabel("Updating all dashboard data")
            }
            Button { model.navigateBack() } label: {
                Image(systemName: "arrow.uturn.backward").frame(minWidth: 44, minHeight: 44)
            }
            .disabled(!model.canNavigateBack)
            .help("Return to the previous analytical scope")
            .accessibilityLabel("Back through analysis history")
            Button { model.navigateForward() } label: {
                Image(systemName: "arrow.uturn.forward").frame(minWidth: 44, minHeight: 44)
            }
            .disabled(!model.canNavigateForward)
            .help("Move forward through analytical scope history")
            .accessibilityLabel("Forward through analysis history")
            if model.page != .drivers && (!model.category.isEmpty || !model.subcategory.isEmpty || !model.merchant.isEmpty) {
                Button("Up one level", systemImage: "arrow.up.left") { model.drillUp() }
                    .buttonStyle(.bordered)
                    .frame(minHeight: 44)
                    .help("Move up one level in the spending hierarchy")
                    .accessibilityLabel("Move up one level in the spending hierarchy")
            }
            Button("Reset", systemImage: "arrow.counterclockwise") { model.resetScope() }
                .buttonStyle(.bordered)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
        .background(.bar)
    }

    private var categoryValues: Set<String> { Set(model.category.split(separator: "|").map(String.init)) }
    private var subcategoryValues: Set<String> { Set(model.subcategory.split(separator: "|").map(String.init)) }
    private var merchantValues: Set<String> { Set(model.merchant.split(separator: "|").map(String.init)) }
}

private struct SlicerLabel: View {
    let title: String
    let value: String
    var body: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 1) {
                Text(title.uppercased()).font(.caption2.monospaced()).foregroundStyle(.secondary)
                Text(value).font(.callout.weight(.medium)).lineLimit(1)
            }
            Image(systemName: "chevron.down").font(.caption2).foregroundStyle(.secondary)
        }
        .frame(minWidth: 112, alignment: .leading)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .frame(minHeight: 44)
        .background(Color.primary.opacity(0.045), in: RoundedRectangle(cornerRadius: 9))
    }
}

private struct LoadingView: View {
    var body: some View {
        VStack(spacing: 14) {
            ProgressView().controlSize(.large)
            Text("Loading your live ledger").font(.headline)
            Text("Moneta is connecting to the private finance service on this Mac.").foregroundStyle(.secondary)
        }
    }
}

private struct ErrorView: View {
    @EnvironmentObject private var model: AppModel
    let message: String
    var body: some View {
        ContentUnavailableView {
            Label("Finance service unavailable", systemImage: "exclamationmark.triangle")
        } description: {
            Text(message)
        } actions: {
            Button("Try again") { Task { await model.refresh(includeSecondary: true) } }
        }
    }
}
