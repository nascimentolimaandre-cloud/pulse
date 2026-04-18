/**
 * Thin analytics wrapper. Central entry-point so that swapping to
 * PostHog/Mixpanel/Amplitude later is a one-file change.
 *
 * For now it just logs to console (gated to dev) — no vendor coupling.
 * TODO: wire to PostHog once infra ticket lands (see FDD-TEL-001).
 */

export type AnalyticsPayload = Record<string, unknown>;

export function trackEvent(name: string, payload: AnalyticsPayload = {}): void {
  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.debug('[analytics]', name, payload);
  }
  // TODO: forward to vendor SDK (PostHog/Mixpanel) behind a runtime flag.
}
