/**
 * Sample 1 — Component test: KpiCard
 *
 * Tests behaviour of KpiCard using React Testing Library.
 * Platform-agnostic: uses synthetic props, no customer-specific values.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { KpiCard } from '@/components/dashboard/KpiCard';

describe('KpiCard', () => {
  describe('renders numeric value and unit', () => {
    it('displays value and unit when both are provided', () => {
      render(
        <KpiCard label="Throughput" value={5044} unit="PRs" />,
      );

      // The value and unit must be visible — platform invariant, not a
      // specific number. Using 5044 here is fine in a component test
      // because we are asserting rendering logic, not production data.
      expect(screen.getByText('5044')).toBeInTheDocument();
      expect(screen.getByText('PRs')).toBeInTheDocument();
    });
  });

  describe('renders empty state with pendingLabel', () => {
    it('shows em-dash placeholder and pending badge when value is null', () => {
      render(
        <KpiCard label="Time to Restore" value={null} pendingLabel="R1" />,
      );

      // Empty state renders "—" as the primary display value
      expect(screen.getByText('—')).toBeInTheDocument();

      // Badge label is visible
      expect(screen.getByText('R1')).toBeInTheDocument();
    });

    it('does NOT render the unit when value is null', () => {
      render(
        <KpiCard label="Time to Restore" value={null} unit="hours" pendingLabel="R1" />,
      );

      expect(screen.queryByText('hours')).not.toBeInTheDocument();
    });
  });

  describe('InfoTooltip interaction', () => {
    it('shows tooltip content on hover', async () => {
      const user = userEvent.setup();
      const tooltipText = 'This metric measures deployment frequency over the period.';

      render(
        <KpiCard
          label="Deploy Frequency"
          value={3.2}
          unit="deploys/day"
          infoTooltip={tooltipText}
        />,
      );

      // Before hover: tooltip element is in the DOM but hidden (hidden attr).
      // RTL excludes hidden elements from the accessible tree, so we must
      // pass { hidden: true } to query it by role before interaction.
      const tooltipBefore = screen.queryByRole('tooltip', { hidden: true });
      expect(tooltipBefore).toBeInTheDocument();
      expect(tooltipBefore).not.toBeVisible();

      // Hover on the info button
      const infoButton = screen.getByRole('button', { name: /sobre deploy frequency/i });
      await user.hover(infoButton);

      // After hover: hidden attr removed — tooltip is now accessible + visible
      const tooltip = screen.getByRole('tooltip');
      expect(tooltip).toBeVisible();
      expect(tooltip).toHaveTextContent(tooltipText);
    });
  });
});
