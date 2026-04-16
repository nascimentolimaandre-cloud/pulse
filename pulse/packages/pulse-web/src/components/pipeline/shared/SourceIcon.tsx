import {
  GitPullRequest,
  Bug,
  Rocket,
  GitCommit,
  Box,
  Layers,
  Cable,
} from 'lucide-react';

interface SourceIconProps {
  id: string;
  size?: number;
  className?: string;
}

const ICON_MAP: Record<string, { icon: typeof GitPullRequest; defaultColor: string }> = {
  github: { icon: GitPullRequest, defaultColor: 'text-content-primary' },
  jira: { icon: Bug, defaultColor: 'text-[#0052CC]' },
  jenkins: { icon: Rocket, defaultColor: 'text-[#D24939]' },
  gitlab: { icon: GitCommit, defaultColor: 'text-[#FC6D26]' },
  azure: { icon: Box, defaultColor: 'text-[#0078D4]' },
  bitbucket: { icon: Layers, defaultColor: 'text-[#2684FF]' },
};

export function SourceIcon({ id, size = 18, className }: SourceIconProps) {
  const entry = ICON_MAP[id];
  if (!entry) return <Cable size={size} className={className ?? 'text-content-tertiary'} />;
  const Icon = entry.icon;
  return <Icon size={size} className={className ?? entry.defaultColor} />;
}
