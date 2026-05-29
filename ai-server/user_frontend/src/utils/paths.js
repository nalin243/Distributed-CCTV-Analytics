export function parsePathDate(p) {
  try {
    const seg = p.split('/')[5].split('-');
    return `${seg[1]}/${seg[2]}/${seg[3]}`;
  } catch { return 'Unknown'; }
}

export function parsePathTime(p) {
  try {
    const seg = p.split('/')[6].split('-');
    const ss  = (seg[3] || '00').substring(0, 2);
    return `${seg[1]}:${seg[2]}:${ss}`;
  } catch { return '00:00:00'; }
}

export function parsePathHour(p) {
  try { return parseInt(parsePathTime(p).split(':')[0]); }
  catch { return null; }
}

export function getPathSortKey(p) {
  try {
    const dp = p.split('/')[5].split('-');
    const tp = p.split('/')[6].split('-');
    const ss = (tp[3] || '00').substring(0, 2);
    return `${dp[3]}-${dp[2]}-${dp[1]} ${tp[1]}:${tp[2]}:${ss}`;
  } catch { return ''; }
}

export function latestPath(paths) {
  if (!paths?.length) return null;
  return [...paths].sort((a, b) => getPathSortKey(b).localeCompare(getPathSortKey(a)))[0];
}

export function groupPathsByDate(paths) {
  const groups = {};
  paths.forEach(p => {
    const d = parsePathDate(p);
    if (!groups[d]) groups[d] = [];
    groups[d].push(p);
  });
  return Object.entries(groups).sort((a, b) => {
    const ka = a[1][0] ? getPathSortKey(a[1][0]).split(' ')[0] : '';
    const kb = b[1][0] ? getPathSortKey(b[1][0]).split(' ')[0] : '';
    return kb.localeCompare(ka);
  });
}