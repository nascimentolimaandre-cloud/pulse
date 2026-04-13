import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ProjectRowActions, getActionsForStatus } from '../project-row-actions';
import type { JiraProjectStatus } from '@pulse/shared';

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('getActionsForStatus', () => {
  it('returns activate + block for discovered', () => {
    const actions = getActionsForStatus('discovered');
    expect(actions.map((a) => a.action)).toEqual(['activate', 'block']);
  });

  it('returns pause + block for active', () => {
    const actions = getActionsForStatus('active');
    expect(actions.map((a) => a.action)).toEqual(['pause', 'block']);
  });

  it('returns resume + block for paused', () => {
    const actions = getActionsForStatus('paused');
    expect(actions.map((a) => a.action)).toEqual(['resume', 'block']);
  });

  it('returns resume for blocked', () => {
    const actions = getActionsForStatus('blocked');
    expect(actions.map((a) => a.action)).toEqual(['resume']);
  });

  it('returns empty for archived', () => {
    const actions = getActionsForStatus('archived');
    expect(actions).toHaveLength(0);
  });
});

describe('ProjectRowActions', () => {
  it('renders action button for non-archived status', () => {
    render(<ProjectRowActions projectKey="PROJ" status="discovered" />, { wrapper });
    expect(screen.getByRole('button', { name: /Acoes para projeto PROJ/i })).toBeInTheDocument();
  });

  it('renders nothing for archived status', () => {
    const { container } = render(<ProjectRowActions projectKey="PROJ" status="archived" />, {
      wrapper,
    });
    expect(container.innerHTML).toBe('');
  });

  it('shows menu items on click', () => {
    render(<ProjectRowActions projectKey="PROJ" status="active" />, { wrapper });
    const trigger = screen.getByRole('button', { name: /Acoes para projeto PROJ/i });
    fireEvent.click(trigger);

    expect(screen.getByRole('menuitem', { name: /Pausar/i })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /Bloquear/i })).toBeInTheDocument();
  });

  it.each<[JiraProjectStatus, string[]]>([
    ['discovered', ['Ativar', 'Bloquear']],
    ['active', ['Pausar', 'Bloquear']],
    ['paused', ['Retomar', 'Bloquear']],
    ['blocked', ['Desbloquear']],
  ])('shows correct menu items for status %s', (status, expectedLabels) => {
    render(<ProjectRowActions projectKey="TEST" status={status} />, { wrapper });
    fireEvent.click(screen.getByRole('button', { name: /Acoes para projeto TEST/i }));

    for (const label of expectedLabels) {
      expect(screen.getByRole('menuitem', { name: new RegExp(label, 'i') })).toBeInTheDocument();
    }
  });
});
