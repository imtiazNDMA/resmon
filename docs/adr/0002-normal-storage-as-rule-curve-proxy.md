# Use the bulletin "Normal Storage" column as the rule-curve proxy

## Context

Release-risk must distinguish a flood/emergency release from routine operational drawdown, which the spec frames "net of the seasonal rule curve" (§8.3, FR-ML-3). BBMB operational rule curves for the pilot reservoirs (Gobind Sagar, Pong, Thein) are generally not published, so obtaining the real target schedules would block the release-label definition indefinitely.

The historical bulletins already carry a fully-populated (144/144) per-date, per-reservoir **"Storage as % of live capacity — Normal Storage"** column — a seasonal climatological reference tracing the expected fill shape across the year.

## Decision

Use the bulletin **Normal Storage** curve as the rule-curve proxy for v1. A release episode is defined as: storage at/near FRL **and** receding faster than / further below the seasonal normal recession. Routine drawdown that tracks the normal curve is treated as expected outflow, not a release.

## Consequences

- No new data acquisition; the proxy ships with the ground truth.
- **Known limitation:** a climatological average outcome is not an operational target. It can *understate* deliberate pre-monsoon flood-cushion drawdown, so episodes defined against it may differ from operator intent. This is acceptable for v1 weak labels but is flagged.
- "Obtain official BBMB rule curves" is a v2 upgrade that would replace this proxy.
