import Foundation

enum APIError: LocalizedError {
    case invalidResponse
    case backendUnavailable

    var errorDescription: String? {
        switch self {
        case .invalidResponse: "Moneta received an unexpected response from the local finance service."
        case .backendUnavailable: "The local finance service is unavailable. The ledger itself has not been changed."
        }
    }
}

struct APIClient {
    let baseURL = URL(string: "http://127.0.0.1:8765")!

    func analytics(
        month: String,
        range: Int,
        category: String,
        subcategory: String,
        merchant: String,
        comparison: ComparisonMode,
        months: Set<String> = []
    ) async throws -> AnalyticsResponse {
        var components = URLComponents(url: baseURL.appending(path: "api/analytics"), resolvingAgainstBaseURL: false)!
        components.queryItems = [
            URLQueryItem(name: "month", value: month),
            URLQueryItem(name: "range", value: String(range)),
            URLQueryItem(name: "category", value: category),
            URLQueryItem(name: "subcategory", value: subcategory),
            URLQueryItem(name: "merchant", value: merchant),
            URLQueryItem(name: "comparison", value: comparison == .year ? "year" : "previous"),
            URLQueryItem(name: "months", value: months.sorted().joined(separator: "|")),
        ]
        return try await fetch(components.url!)
    }

    func commitments() async throws -> CommitmentsResponse {
        try await fetch(baseURL.appending(path: "api/commitments"))
    }

    func health() async throws -> [String: HealthItem] {
        try await fetch(baseURL.appending(path: "api/health"))
    }

    func insights(
        cadence: String,
        month: String,
        range: Int,
        category: String,
        subcategory: String,
        merchant: String,
        comparison: ComparisonMode,
        months: Set<String>
    ) async throws -> InsightsHubResponse {
        var components = URLComponents(url: baseURL.appending(path: "api/insights"), resolvingAgainstBaseURL: false)!
        components.queryItems = [
            URLQueryItem(name: "cadence", value: cadence),
            URLQueryItem(name: "month", value: month),
            URLQueryItem(name: "range", value: String(range)),
            URLQueryItem(name: "category", value: category),
            URLQueryItem(name: "subcategory", value: subcategory),
            URLQueryItem(name: "merchant", value: merchant),
            URLQueryItem(name: "comparison", value: comparison == .year ? "year" : "previous"),
            URLQueryItem(name: "months", value: months.sorted().joined(separator: "|")),
        ]
        return try await fetch(components.url!)
    }

    func updateCommitment(id: String, payload: CommitmentUpdatePayload) async throws -> CommitmentsResponse {
        let url = baseURL.appending(path: "api/commitments/\(id)")
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(payload)
        request.timeoutInterval = 15
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            let message = (try? JSONSerialization.jsonObject(with: data) as? [String: String])?["message"]
            throw NSError(domain: "Moneta.Commitment", code: 1, userInfo: [NSLocalizedDescriptionKey: message ?? "The commitment could not be updated."])
        }
        return try JSONDecoder.moneta.decode(CommitmentsResponse.self, from: data)
    }

    func logCash(_ payload: CashEntryPayload) async throws -> CashEntryResponse {
        let url = baseURL.appending(path: "api/cash")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(payload)
        request.timeoutInterval = 95
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 201 else {
            let message = (try? JSONSerialization.jsonObject(with: data) as? [String: String])?["message"]
            throw NSError(domain: "Moneta.Cash", code: 1, userInfo: [NSLocalizedDescriptionKey: message ?? "Cash entry could not be logged."])
        }
        return try JSONDecoder.moneta.decode(CashEntryResponse.self, from: data)
    }

    private func fetch<T: Decodable>(_ url: URL) async throws -> T {
        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        request.timeoutInterval = 12
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                throw APIError.invalidResponse
            }
            return try JSONDecoder.moneta.decode(T.self, from: data)
        } catch let error as APIError {
            throw error
        } catch {
            throw APIError.backendUnavailable
        }
    }
}
