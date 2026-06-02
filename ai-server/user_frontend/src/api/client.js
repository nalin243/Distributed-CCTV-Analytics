const BASE = import.meta.env.VITE_API_BASE ?? 'http://192.168.1.16:5000';

async function req(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export const searchFootage = (payload) =>
  req('/api/search', { method: 'POST', body: JSON.stringify(payload) });

export const getMetadata = () => req('/api/metadata');

export const runClustering = () => req('/api/cluster/run');
export const getClusterStats = () => req('/api/cluster/stats');
export const nameCluster = (cluster_id, name) =>
  req('/api/cluster/name', { method: 'POST', body: JSON.stringify({ cluster_id, name }) });
export const mergeClusters = (source_id, target_id) =>
  req('/api/cluster/merge', { method: 'POST', body: JSON.stringify({ source_id, target_id }) });
export const deleteCluster = (cluster_id) =>
  req('/api/cluster/delete', { method: 'POST', body: JSON.stringify({ cluster_id }) });

export const deleteCrop = (image_path) =>
  req('/api/crop/delete', { method: 'POST', body: JSON.stringify({ image_path }) });
export const deleteSnapshot = (image_path) =>
  req('/api/snapshot/delete', { method: 'POST', body: JSON.stringify({ image_path }) });
export const updateSnapshotCluster = (image_path, new_cluster_id, new_person_name) =>
  fetch("/api/snapshot/update_cluster", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image_path, new_cluster_id, new_person_name }),
  }).then(r => r.json());

// ── Media URLs ────────────────────────────────────────────────────────────────
export const imageUrl = (path) => `${BASE}/image?path=${encodeURIComponent(path)}`;
export const videoUrl = (image_path) => `${BASE}/video?image_path=${encodeURIComponent(image_path)}`;