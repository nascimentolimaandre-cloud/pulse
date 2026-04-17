// Mock data shared by dashboard concepts (Executive / Investigator / Diagnostic)
// Real-scale: 27 squads grouped by 8 tribos (Webmotors)

export const GLOBAL_METRICS = {
  dora: {
    deploymentFrequency: { label: 'Deploy Frequency',  value: 4.2,  unit: '/dia', classification: 'elite',  trendPct:  12.3, sparkline: [2.8,3.1,3.4,3.0,3.6,3.9,3.7,4.0,4.2,4.1,4.3,4.2] },
    leadTimeForChanges:  { label: 'Lead Time',         value: 18,   unit: 'h',    classification: 'elite',  trendPct:  -8.1, sparkline: [26,24,25,23,22,21,20,19,19,18,18,18] },
    changeFailureRate:   { label: 'Change Failure',    value: 6.8,  unit: '%',    classification: 'high',   trendPct:  -2.4, sparkline: [9.2,8.8,8.1,7.9,7.5,7.2,7.0,6.9,6.8,6.7,6.8,6.8] },
    timeToRestore:       { label: 'Time to Restore',   value: 1.2,  unit: 'h',    classification: 'elite',  trendPct: -15.0, sparkline: [2.1,1.9,1.8,1.6,1.5,1.4,1.3,1.3,1.2,1.2,1.2,1.2] },
  },
  flow: {
    cycleTimeP50:        { label: 'Cycle Time P50',    value: 2.8,  unit: 'd',    trendPct: -5.4,  sparkline: [3.4,3.3,3.1,3.0,2.9,2.9,2.8,2.8,2.8,2.8,2.8,2.8] },
    cycleTimeP85:        { label: 'Cycle Time P85',    value: 8.1,  unit: 'd',    trendPct:  3.2,  sparkline: [7.2,7.4,7.6,7.7,7.8,7.9,8.0,8.0,8.1,8.0,8.1,8.1] },
    wip:                 { label: 'WIP',               value: 143,  unit: 'items',trendPct:  8.0,  sparkline: [124,128,130,132,134,136,138,140,141,142,143,143] },
    throughput:          { label: 'Throughput',        value: 87,   unit: 'PRs/sem', trendPct: 6.2, sparkline: [78,80,81,82,83,84,85,86,86,87,87,87] },
  },
};

// 27 squads distributed across 8 tribos — realistic Webmotors-like distribution
const RAW_TEAMS = [
  // Tribe PF (Produtos Financeiros) — 4 squads
  { id: 'pf-okm',   name: 'OEM Integração',       tribe: 'PF',   cls: 'elite'  },
  { id: 'pf-fin',   name: 'Financiamento',        tribe: 'PF',   cls: 'elite'  },
  { id: 'pf-seg',   name: 'Seguros',              tribe: 'PF',   cls: 'high'   },
  { id: 'pf-pag',   name: 'Pagamentos',           tribe: 'PF',   cls: 'high'   },

  // Tribe TEC (Tecnologia transversal) — 4
  { id: 'tec-sdi',  name: 'Segurança da Informação', tribe: 'TEC', cls: 'medium' },
  { id: 'tec-obs',  name: 'Observabilidade',      tribe: 'TEC',  cls: 'high'   },
  { id: 'tec-plt',  name: 'Plataforma Cloud',     tribe: 'TEC',  cls: 'elite'  },
  { id: 'tec-dev',  name: 'Developer Experience', tribe: 'TEC',  cls: 'high'   },

  // Tribe PI (Publicidade / Integrações) — 3
  { id: 'pi-secom', name: 'SECOM',                tribe: 'PI',   cls: 'low'    },
  { id: 'pi-ads',   name: 'Ads Platform',         tribe: 'PI',   cls: 'medium' },
  { id: 'pi-part',  name: 'Parceiros',            tribe: 'PI',   cls: 'medium' },

  // Tribe SALES — 4
  { id: 'sls-lead', name: 'Lead Management',      tribe: 'SALES',cls: 'high'   },
  { id: 'sls-crm',  name: 'CRM',                  tribe: 'SALES',cls: 'medium' },
  { id: 'sls-prc',  name: 'Precificação',         tribe: 'SALES',cls: 'elite'  },
  { id: 'sls-dlr',  name: 'Dealer Portal',        tribe: 'SALES',cls: 'high'   },

  // Tribe BG (Buy/Grow) — 3
  { id: 'bg-buy',   name: 'Buy Flow',             tribe: 'BG',   cls: 'high'   },
  { id: 'bg-grw',   name: 'Growth',               tribe: 'BG',   cls: 'medium' },
  { id: 'bg-chk',   name: 'Checkout',             tribe: 'BG',   cls: 'high'   },

  // Tribe DESC (Descoberta) — 3
  { id: 'dsc-srh',  name: 'Search',               tribe: 'DESC', cls: 'elite'  },
  { id: 'dsc-rec',  name: 'Recomendação',         tribe: 'DESC', cls: 'high'   },
  { id: 'dsc-cat',  name: 'Catálogo',             tribe: 'DESC', cls: 'medium' },

  // Tribe ENO (Enablers / Ops) — 3
  { id: 'eno-ops',  name: 'SRE',                  tribe: 'ENO',  cls: 'elite'  },
  { id: 'eno-dat',  name: 'Data Platform',        tribe: 'ENO',  cls: 'high'   },
  { id: 'eno-iam',  name: 'Identity',             tribe: 'ENO',  cls: 'medium' },

  // Tribe CPA (Core & Apps) — 3
  { id: 'cpa-mob',  name: 'Mobile Apps',          tribe: 'CPA',  cls: 'high'   },
  { id: 'cpa-web',  name: 'Web Core',             tribe: 'CPA',  cls: 'high'   },
  { id: 'cpa-bff',  name: 'BFF',                  tribe: 'CPA',  cls: 'low'    },
];

// Deterministic seeded PRNG for reproducible mock
function mulberry32(seed) {
  return function () {
    let t = seed += 0x6D2B79F5;
    t = Math.imul(t ^ t >>> 15, t | 1);
    t ^= t + Math.imul(t ^ t >>> 7, t | 61);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

// Generate metrics per classification band
function generateTeamMetrics(cls, rng) {
  const bands = {
    elite:  { df: [3.0, 6.0],  lt: [8,  22],  cfr: [1, 5],   ct50: [1.5, 3.0], ct85: [4, 7],  wip: [8, 16], thr: [18, 30] },
    high:   { df: [1.2, 3.0],  lt: [22, 50],  cfr: [5, 10],  ct50: [2.5, 5.0], ct85: [7, 12], wip: [12, 22],thr: [12, 22] },
    medium: { df: [0.4, 1.2],  lt: [50, 120], cfr: [10, 15], ct50: [4.0, 7.0], ct85: [10,18], wip: [18, 30],thr: [8, 15]  },
    low:    { df: [0.05, 0.4], lt: [120,360], cfr: [15, 40], ct50: [6.0, 12 ], ct85: [16,30], wip: [25, 45],thr: [3, 10]  },
  };
  const b = bands[cls];
  const pick = ([lo, hi]) => +(lo + rng() * (hi - lo)).toFixed(cls === 'elite' || cls === 'high' ? 1 : 1);
  return {
    deployFreq:   pick(b.df),
    leadTime:     Math.round(pick(b.lt)),
    cfr:          +pick(b.cfr).toFixed(1),
    cycleTimeP50: pick(b.ct50),
    cycleTimeP85: pick(b.ct85),
    wip:          Math.round(pick(b.wip)),
    throughput:   Math.round(pick(b.thr)),
  };
}

// Generate 12-week evolution sparkline with mild trend
function generateEvolution(baseline, rng, trend = 0) {
  const pts = [];
  let v = baseline * (1 - trend * 0.15);
  for (let i = 0; i < 12; i++) {
    v = v + (baseline - v) * 0.25 + (rng() - 0.5) * baseline * 0.12;
    pts.push(+Math.max(0, v).toFixed(2));
  }
  // End exactly at baseline
  pts[pts.length - 1] = baseline;
  return pts;
}

export const TEAMS = (() => {
  const rng = mulberry32(1492);
  return RAW_TEAMS.map((t) => {
    const m = generateTeamMetrics(t.cls, rng);
    return {
      ...t,
      ...m,
      evolution: {
        deployFreq:   generateEvolution(m.deployFreq,   rng, -0.05),
        leadTime:     generateEvolution(m.leadTime,     rng,  0.08),
        cfr:          generateEvolution(m.cfr,          rng,  0.02),
        cycleTimeP50: generateEvolution(m.cycleTimeP50, rng,  0.0),
        wip:          generateEvolution(m.wip,          rng,  0.10),
        throughput:   generateEvolution(m.throughput,   rng, -0.05),
      },
    };
  });
})();

export const TRIBES = [...new Set(TEAMS.map((t) => t.tribe))];

export const PERIOD_OPTIONS = [
  { id: '30d',    label: '30 dias' },
  { id: '60d',    label: '60 dias' },
  { id: '90d',    label: '90 dias' },
  { id: '120d',   label: '120 dias' },
  { id: 'custom', label: 'Personalizado…' },
];

// DORA thresholds (2023 DORA report)
export const DORA_THRESHOLDS = {
  deployFreq:   { elite: 1,   high: 0.14, medium: 0.03 }, // per day
  leadTime:     { elite: 24,  high: 168,  medium: 720 },  // hours (<= is better)
  cfr:          { elite: 5,   high: 10,   medium: 15 },   // % (<= is better)
};

export function classifyDora(metric, value) {
  const t = DORA_THRESHOLDS[metric];
  if (!t) return 'neutral';
  if (metric === 'deployFreq') {
    if (value >= t.elite) return 'elite';
    if (value >= t.high) return 'high';
    if (value >= t.medium) return 'medium';
    return 'low';
  }
  if (value <= t.elite) return 'elite';
  if (value <= t.high) return 'high';
  if (value <= t.medium) return 'medium';
  return 'low';
}

export function fmtNumber(n, unit = '') {
  if (n == null) return '—';
  if (Math.abs(n) >= 1000) return (n / 1000).toFixed(1) + 'k' + (unit ? ' ' + unit : '');
  if (Number.isInteger(n)) return n.toString() + (unit ? ' ' + unit : '');
  return n.toFixed(1) + (unit ? ' ' + unit : '');
}

export function fmtTrend(pct) {
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(1)}%`;
}
