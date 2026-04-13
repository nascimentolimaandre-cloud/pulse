import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ModeSelector } from '../mode-selector';

describe('ModeSelector', () => {
  it('renders 4 radio cards', () => {
    render(<ModeSelector value="auto" onChange={vi.fn()} />);
    expect(screen.getAllByRole('radio')).toHaveLength(4);
  });

  it('marks the selected mode as checked', () => {
    render(<ModeSelector value="smart" onChange={vi.fn()} />);
    const smartRadio = screen.getByLabelText(/Modo Smart/i);
    expect(smartRadio).toBeChecked();

    const autoRadio = screen.getByLabelText(/Modo Automatico/i);
    expect(autoRadio).not.toBeChecked();
  });

  it('calls onChange when a different mode is clicked', () => {
    const onChange = vi.fn();
    render(<ModeSelector value="auto" onChange={onChange} />);

    const blocklist = screen.getByLabelText(/Modo Blocklist/i);
    fireEvent.click(blocklist);
    expect(onChange).toHaveBeenCalledWith('blocklist');
  });

  it('does not call onChange when current mode is clicked again', () => {
    const onChange = vi.fn();
    render(<ModeSelector value="allowlist" onChange={onChange} />);

    // Clicking the already-selected radio should not trigger onChange
    // (HTML radio does not fire change when re-selecting same)
    const allowlist = screen.getByLabelText(/Modo Allowlist/i);
    fireEvent.click(allowlist);
    // Radio onChange only fires on actual change
    expect(onChange).not.toHaveBeenCalled();
  });

  it('shows PII warning banner when auto mode is selected', () => {
    render(<ModeSelector value="auto" onChange={vi.fn()} />);
    const banner = screen.getByTestId('pii-mode-warning');
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toContain('discovered');
  });

  it('shows PII warning banner when smart mode is selected', () => {
    render(<ModeSelector value="smart" onChange={vi.fn()} />);
    const banner = screen.getByTestId('pii-mode-warning');
    expect(banner).toBeInTheDocument();
  });

  it('does not show PII warning banner for allowlist mode', () => {
    render(<ModeSelector value="allowlist" onChange={vi.fn()} />);
    expect(screen.queryByTestId('pii-mode-warning')).not.toBeInTheDocument();
  });

  it('does not show PII warning banner for blocklist mode', () => {
    render(<ModeSelector value="blocklist" onChange={vi.fn()} />);
    expect(screen.queryByTestId('pii-mode-warning')).not.toBeInTheDocument();
  });

  it('renders all modes disabled when disabled prop is true', () => {
    render(<ModeSelector value="auto" onChange={vi.fn()} disabled />);
    const fieldset = screen.getByRole('group');
    expect(fieldset).toBeDisabled();
  });
});
