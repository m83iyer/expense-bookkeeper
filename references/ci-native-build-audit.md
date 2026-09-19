# Native Moneta release-gate audit

Candidate change: add one manual macOS build to the existing exact-SHA cloud
release gate and bind its application artifact into the final proof.

## Eighteen-practice review

1. **Dependency cache:** not applicable; the native Swift package has no remote package dependencies.
2. **Shallow checkout:** applied to the native job; it uses the default shallow checkout.
3. **Sharding:** not applicable; one small native compile would cost more if split.
4. **Affected-component scoping:** not used in the authoritative manual release gate.
5. **Path filters:** not applicable because the gate is `workflow_dispatch` only.
6. **Concurrency:** the existing ref-scoped group serializes/cancels superseded manual candidates.
7. **Required-check hygiene:** the native compile and exact-SHA proof are release-blocking.
8. **Runner selection:** macOS is required for SwiftUI/AppKit; Linux remains in use for every other job.
9. **Queue measurement:** no runner change was made; queue delay will be measured from this first native run.
10. **Timeouts:** applied: 20 minutes for native build and 10 minutes for proof; existing validation is 25 minutes.
11. **Fixed sleeps:** none.
12. **Service containers:** none.
13. **Permissions:** top-level `contents: read`; each job is read-only.
14. **Secrets:** none referenced or exposed.
15. **`pull_request_target`:** absent.
16. **Cache trust:** no Actions cache is written or restored.
17. **Pinned actions:** every external action is pinned to a 40-character commit SHA.
18. **OIDC:** no `id-token` permission is granted.

## Minute and proof impact

The September baseline audit recorded one five-minute Cloud release gate run.
This change adds one required macOS compile job and no matrix fan-out, cache,
browser, service container, or automatic trigger. Its first measured duration
will become the reservation basis for later runs. The artifact is built once,
retained for 30 days, downloaded by the proof job, and reused for installation;
there is no second deployment build.
