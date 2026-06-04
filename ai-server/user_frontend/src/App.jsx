import { useState, useEffect, useCallback } from "react";
import * as api from "./api/client";
import {
  parsePathDate, parsePathTime, parsePathHour,
  getPathSortKey, latestPath, groupPathsByDate,
} from "./utils/paths";

// ─── Design tokens ────────────────────────────────────────────────────────────
const T = {
  bg:      "#f1f5f9",
  surface: "#ffffff",
  s2:      "#f8fafc",
  border:  "#e2e8f0",
  border2: "#cbd5e1",
  accent:  "#2563eb",
  accent2: "#1d4ed8",
  green:   "#16a34a",
  amber:   "#d97706",
  red:     "#dc2626",
  purple:  "#7c3aed",
  text:    "#0f172a",
  muted:   "#64748b",
  muted2:  "#475569",
};

// ─── Responsive hook ──────────────────────────────────────────────────────────
function useBreakpoint() {
  const [w, setW] = useState(typeof window !== "undefined" ? window.innerWidth : 1024);
  useEffect(() => {
    const handler = () => setW(window.innerWidth);
    window.addEventListener("resize", handler);
    return () => window.removeEventListener("resize", handler);
  }, []);
  return {
    isMobile:  w < 640,
    isTablet:  w >= 640 && w < 1024,
    isDesktop: w >= 1024,
    w,
  };
}

// ─── Shared components ────────────────────────────────────────────────────────
function Pill({ children, color = T.accent }) {
  return (
    <span style={{
      fontFamily: "'IBM Plex Mono', monospace",
      fontSize: 11, fontWeight: 500,
      background: color === T.accent ? "#eff6ff" : color + "18",
      color,
      border: `1px solid ${color === T.accent ? "#bfdbfe" : color + "44"}`,
      borderRadius: 4, padding: "2px 7px", whiteSpace: "nowrap",
    }}>
      {children}
    </span>
  );
}

function Btn({ children, onClick, variant = "primary", style, disabled }) {
  const base = {
    border: "none", borderRadius: 7, fontSize: 13, fontWeight: 600,
    cursor: disabled ? "not-allowed" : "pointer", padding: "8px 16px",
    opacity: disabled ? 0.4 : 1, transition: "all .15s",
    fontFamily: "'IBM Plex Sans', sans-serif", whiteSpace: "nowrap",
    display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
  };
  const variants = {
    primary: { background: T.accent,  color: "#fff" },
    ghost:   { background: "transparent", border: `1px solid ${T.border2}`, color: T.muted2 },
    danger:  { background: T.red,     color: "#fff" },
    amber:   { background: T.amber,   color: "#000" },
  };
  return (
    <button onClick={onClick} disabled={disabled}
      style={{ ...base, ...variants[variant], ...style }}>
      {children}
    </button>
  );
}

function StatCard({ val, label, color = T.accent }) {
  return (
    <div style={{
      background: T.surface, border: `1px solid ${T.border}`,
      borderRadius: 10, padding: "16px 12px", textAlign: "center",
      display: "flex", flexDirection: "column", justifyContent: "center",
    }}>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 22, fontWeight: 700, color }}>{val}</div>
      <div style={{ fontSize: 10, color: T.muted, marginTop: 4, textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</div>
    </div>
  );
}

function SectionLabel({ children }) {
  return (
    <div style={{
      fontSize: 10, fontWeight: 600, color: T.muted,
      textTransform: "uppercase", letterSpacing: "0.12em",
      fontFamily: "'IBM Plex Mono', monospace", marginBottom: 14,
    }}>{children}</div>
  );
}

function Loader({ text = "Loading…" }) {
  return (
    <div style={{ textAlign: "center", padding: "60px 0", width: "100%" }}>
      <div style={{
        width: 32, height: 32, borderRadius: "50%",
        border: `2px solid ${T.border2}`, borderTopColor: T.accent,
        animation: "spin .7s linear infinite", margin: "0 auto 12px",
      }} />
      <div style={{ fontSize: 13, color: T.muted }}>{text}</div>
    </div>
  );
}

function Panel({ children, style }) {
  return (
    <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 10, ...style }}>
      {children}
    </div>
  );
}

// ─── Lightbox ─────────────────────────────────────────────────────────────────
function Lightbox({ meta, onClose, onDelete, onMove }) {
  const [mode, setMode] = useState("video");
  const { isMobile }    = useBreakpoint();

  useEffect(() => { setMode("video"); }, [meta]);
  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  if (!meta) return null;

  return (
    <div onClick={(e) => e.target === e.currentTarget && onClose()}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.92)",
        zIndex: 1000, display: "flex",
        alignItems: isMobile ? "flex-end" : "center",
        justifyContent: "center",
        padding: isMobile ? 0 : 24,
      }}>
      <div style={{
        background: T.surface, border: `1px solid ${T.border}`,
        borderRadius: isMobile ? "12px 12px 0 0" : 12,
        overflow: "hidden", width: "100%", maxWidth: isMobile ? "100%" : 1000,
        boxShadow: "0 24px 80px rgba(0,0,0,0.4)",
        display: "flex", flexDirection: "column",
        maxHeight: isMobile ? "90vh" : "95vh"
      }}>
        {mode === "video" ? (
          <video src={api.videoUrl(meta.image_path)} controls autoPlay
            style={{ width: "100%", height: "auto", maxHeight: isMobile ? "calc(90vh - 120px)" : "calc(95vh - 100px)", background: "#000", display: "block", objectFit: "contain" }} />
        ) : (
          <img src={api.imageUrl(meta.image_path)} alt="snapshot"
            style={{ width: "100%", height: "auto", maxHeight: isMobile ? "calc(90vh - 120px)" : "calc(95vh - 100px)", objectFit: "contain", background: "#000", display: "block" }} />
        )}
        <div style={{ padding: isMobile ? "12px 14px" : "14px 18px", borderTop: `1px solid ${T.border}`, flexShrink: 0 }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", fontSize: 12, color: T.muted2, marginBottom: 10 }}>
            <Pill>{meta.camera || "—"}</Pill>
            <span style={{ fontFamily: "monospace" }}>📅 {meta.date}</span>
            <span style={{ fontFamily: "monospace" }}>⏰ {meta.time}</span>
            {meta.similarity > 0 && (
              <span style={{ fontFamily: "monospace", fontWeight: 700, color: T.accent2 }}>
                {Math.round(meta.similarity * 100)}% match
              </span>
            )}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(80px, 1fr))", gap: 8 }}>
            <Btn variant="ghost" onClick={() => setMode("video")}  style={{ fontSize: 12 }}>🎥 Video</Btn>
            <Btn variant="ghost" onClick={() => setMode("image")}  style={{ fontSize: 12 }}>🖼️ Image</Btn>
            {onMove && (
              <Btn variant="ghost" onClick={onMove} style={{ fontSize: 12, color: T.purple, borderColor: "rgba(124,58,237,0.3)" }}>↗ Move</Btn>
            )}
            <Btn variant="ghost" onClick={onDelete} style={{ fontSize: 12, color: T.red, borderColor: "rgba(239,68,68,0.3)" }}>🗑 Delete</Btn>
            <Btn variant="ghost" onClick={onClose}  style={{ fontSize: 12 }}>✕ Close</Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Modal ────────────────────────────────────────────────────────────────────
function Modal({ title, subtitle, children, onClose }) {
  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div onClick={e => e.target === e.currentTarget && onClose()}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
        zIndex: 1100, display: "flex", alignItems: "center",
        justifyContent: "center", padding: 16,
      }}>
      <div style={{
        background: T.surface, border: `1px solid ${T.border2}`,
        borderRadius: 12, padding: 24, width: "100%", maxWidth: 360,
        boxShadow: "0 10px 40px rgba(0,0,0,0.2)"
      }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: T.text, marginBottom: subtitle ? 4 : 14 }}>{title}</div>
        {subtitle && <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: T.muted, marginBottom: 14 }}>{subtitle}</div>}
        {children}
      </div>
    </div>
  );
}

// ─── SearchTab ────────────────────────────────────────────────────────────────
function SearchTab({ cameras, dates }) {
  const { isMobile, w } = useBreakpoint();
  const [query, setQuery]         = useState("");
  const [camera, setCamera]       = useState("");
  const [date, setDate]           = useState("");
  const [hour, setHour]           = useState("");
  const [n, setN]                 = useState(9);
  const [loading, setLoading]     = useState(false);
  const [results, setResults]     = useState(null);
  const [lightbox, setLightbox]   = useState(null);

  const doSearch = useCallback(async () => {
    if (!query.trim()) return;
    setLoading(true); setResults(null);
    try {
      const data = await api.searchFootage({ query, camera: camera || null, date: date || null, hour: hour || null, n });
      setResults(data.results || []);
    } catch { setResults([]); }
    setLoading(false);
  }, [query, camera, date, hour, n]);

  useEffect(() => {
    const h = (e) => { if (e.key === "Enter" && e.target.id === "query-input") doSearch(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [doSearch]);

  const handleDeleteSnapshot = async () => {
    if (!lightbox || !window.confirm("Permanently delete this snapshot?")) return;
    try {
      await api.deleteSnapshot(lightbox.image_path);
      setLightbox(null);
      setResults(r => r.filter(x => x.image_path !== lightbox.image_path));
    } catch (e) { alert(e.message); }
  };

  const badgeBg = (p) => p >= 70 ? "#dcfce7" : p >= 45 ? "#fef3c7" : "#f1f5f9";
  const badgeCol = (p) => p >= 70 ? T.green : p >= 45 ? T.amber : T.muted2;
  const badgeBdr = (p) => p >= 70 ? "#bbf7d0" : p >= 45 ? "#fde68a" : T.border2;

  const selectStyle = {
    width: "100%", padding: "8px 10px", borderRadius: 7, fontSize: 13,
    background: T.s2, border: `1px solid ${T.border2}`, color: T.text,
    fontFamily: "'IBM Plex Sans', sans-serif", appearance: "none",
    backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E\")",
    backgroundRepeat: "no-repeat", backgroundPosition: "right 10px center", paddingRight: 32,
  };

  return (
    <div style={{ width: "100%" }}>
      <Panel style={{ padding: isMobile ? 14 : 20, marginBottom: 16 }}>
        <SectionLabel>Search Parameters</SectionLabel>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
          <input id="query-input" value={query} onChange={e => setQuery(e.target.value)}
            placeholder={isMobile ? "Search footage…" : "e.g. man in red shirt in the evening, white delivery van…"}
            style={{
              flex: "1 1 200px", padding: "10px 12px", fontSize: isMobile ? 15 : 17, borderRadius: 7,
              background: T.s2, border: `1px solid ${T.border2}`, color: T.text,
              fontFamily: "'IBM Plex Sans', sans-serif", outline: "none", minWidth: 0,
            }}
            onFocus={e => { e.target.style.borderColor = T.accent; e.target.style.boxShadow = "0 0 0 3px rgba(37,99,235,0.15)"; }}
            onBlur={e =>  { e.target.style.borderColor = T.border2; e.target.style.boxShadow = "none"; }}
          />
          <Btn onClick={doSearch} disabled={loading} style={{ flex: isMobile ? "1 1 100%" : "0 0 auto" }}>
            {loading ? "…" : "Search"}
          </Btn>
        </div>
        
        {/* Fluid Grid for Filters */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12 }}>
          <div>
            <label style={{ display: "block", fontSize: 11, fontWeight: 500, color: T.muted2, marginBottom: 4 }}>Camera</label>
            <select value={camera} onChange={e => setCamera(e.target.value)} style={selectStyle}>
              <option value="">All Cameras</option>
              {cameras.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label style={{ display: "block", fontSize: 11, fontWeight: 500, color: T.muted2, marginBottom: 4 }}>Date</label>
            <select value={date} onChange={e => setDate(e.target.value)} style={selectStyle}>
              <option value="">All Dates</option>
              {dates.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
          <div>
            <label style={{ display: "block", fontSize: 11, fontWeight: 500, color: T.muted2, marginBottom: 4 }}>Hour</label>
            <select value={hour} onChange={e => setHour(e.target.value)} style={selectStyle}>
              <option value="">Any Hour</option>
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h} value={String(h).padStart(2, "0")}>
                  {String(h).padStart(2, "0")}:00 – {String(h + 1).padStart(2, "0")}:00
                </option>
              ))}
            </select>
          </div>
          <div>
            <label style={{ display: "block", fontSize: 11, fontWeight: 500, color: T.muted2, marginBottom: 4 }}>Max Results</label>
            <div style={{ display: "flex", gap: 6 }}>
              <input type="number" value={n} min={1} max={50}
                onChange={e => setN(parseInt(e.target.value) || 9)}
                style={{ ...selectStyle, flex: 1, backgroundImage: "none", minWidth: 60 }} />
              <Btn variant="ghost" onClick={() => { setCamera(""); setDate(""); setHour(""); setN(9); }}
                style={{ fontSize: 12, padding: "8px 10px" }}>
                Clear
              </Btn>
            </div>
          </div>
        </div>
      </Panel>

      {results !== null && !loading && (
        <div style={{ fontSize: 13, color: T.muted2, marginBottom: 12 }}>
          <strong style={{ color: T.text }}>{results.length} results</strong>
          {results.length > 0 && !isMobile && ` for "${query}"`}
        </div>
      )}

      {loading && <Loader text="Searching database…" />}

      {!loading && results === null && (
        <div style={{ textAlign: "center", padding: "60px 0", fontSize: 13, color: T.muted }}>
          Enter a query above to search footage
        </div>
      )}
      {!loading && results !== null && results.length === 0 && (
        <div style={{ textAlign: "center", padding: "60px 0", fontSize: 13, color: T.muted }}>No results found.</div>
      )}

      {!loading && results !== null && results.length > 0 && (
        /* Fluid Grid for Search Results */
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 12 }}>
          {results.map((r, i) => {
            const p    = Math.round(r.similarity * 100);
            const d    = parsePathDate(r.image_path);
            const t    = parsePathTime(r.image_path);
            const meta = { ...r, date: d, time: t };
            return (
              <div key={r.image_path} onClick={() => setLightbox(meta)}
                style={{
                  background: T.surface, border: `1px solid ${T.border}`,
                  borderRadius: 10, overflow: "hidden", cursor: "pointer",
                  transition: "border-color .2s, transform .15s, box-shadow .15s",
                  display: "flex", flexDirection: "column",
                }}
                onMouseEnter={e => {
                  if (w >= 640) {
                    e.currentTarget.style.borderColor = T.accent;
                    e.currentTarget.style.transform = "translateY(-2px)";
                    e.currentTarget.style.boxShadow = "0 4px 20px rgba(37,99,235,0.12)";
                  }
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.borderColor = T.border;
                  e.currentTarget.style.transform = "none";
                  e.currentTarget.style.boxShadow = "none";
                }}
              >
                <div style={{ position: "relative", paddingTop: "56.25%", background: "#000" }}>
                  <img src={api.imageUrl(r.image_path)} alt="CCTV" loading="lazy"
                    style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", objectFit: "cover", display: "block" }}
                    onError={e => { e.target.style.display = "none"; }} />
                  <div style={{
                    position: "absolute", top: 8, left: 8,
                    background: badgeBg(p), color: badgeCol(p), border: `1px solid ${badgeBdr(p)}`,
                    fontSize: 11, fontWeight: 600, fontFamily: "'IBM Plex Mono', monospace",
                    padding: "2px 7px", borderRadius: 20,
                  }}>{p}%</div>
                  <div style={{
                    position: "absolute", top: 8, right: 8,
                    background: "rgba(0,0,0,0.55)", color: "#fff",
                    fontSize: 10, fontFamily: "'IBM Plex Mono', monospace",
                    width: 22, height: 22, borderRadius: "50%",
                    display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700,
                  }}>{i + 1}</div>
                </div>
                <div style={{ padding: isMobile ? "10px 12px" : "12px 14px", flexGrow: 1, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                    <Pill>{r.camera}</Pill>
                    <span style={{ fontSize: 11, color: T.accent2 }}>▶ Video</span>
                  </div>
                  <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: T.muted2, display: "flex", gap: 10, flexWrap: "wrap" }}>
                    <span>📅 {d}</span>
                    <span>⏰ {t.slice(0, 5)}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* No onMove passed — Move button will not appear in SearchTab lightbox */}
      {lightbox && <Lightbox meta={lightbox} onClose={() => setLightbox(null)} onDelete={handleDeleteSnapshot} />}
    </div>
  );
}

// ─── VisitorDetail ────────────────────────────────────────────────────────────
function VisitorDetail({ cluster, onBack, onRefresh }) {
  const { isMobile } = useBreakpoint();
  const [lightbox, setLightbox] = useState(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [deleting, setDeleting] = useState(false);
  const [showRename, setShowRename] = useState(false);
  const [showMerge, setShowMerge] = useState(false);
  const [showMove, setShowMove] = useState(false);
  const [renameVal, setRenameVal] = useState("");
  const [mergeTarget, setMergeTarget] = useState("");
  const [moveTarget, setMoveTarget] = useState("");
  const [movingSnap, setMovingSnap] = useState(null);
  const [allClusters, setAllClusters] = useState([]);

  const c = cluster;
  const allPaths = c.source_paths || [];
  const isNamed = c.person_name !== "unknown";
  const newest = latestPath(allPaths);
  const allSorted = allPaths.map(p => ({ p, k: getPathSortKey(p) })).sort((a, b) => a.k.localeCompare(b.k));
  const firstPath = allSorted[0]?.p;
  const lastPath = allSorted[allSorted.length - 1]?.p;
  const dateRange = allSorted.length > 1
    ? `${parsePathDate(firstPath)} – ${parsePathDate(lastPath)}`
    : (firstPath ? parsePathDate(firstPath) : "—");
  const lastSeen = newest ? `${parsePathDate(newest)} · ${parsePathTime(newest).slice(0, 5)}` : "—";

  const toggleSelect = (p) => setSelected(prev => {
    const next = new Set(prev); next.has(p) ? next.delete(p) : next.add(p); return next;
  });

  const handleDeleteSelected = async () => {
    if (!selected.size || !window.confirm(`Permanently delete ${selected.size} snapshot(s)?`)) return;
    setDeleting(true);
    for (const path of selected) { try { await api.deleteCrop(path); } catch {} }
    setDeleting(false); setSelectMode(false); setSelected(new Set()); onRefresh();
  };

  const handleDeleteCluster = async () => {
    if (!window.confirm(`Delete all detections for ${isNamed ? c.person_name : c.cluster_id}?`)) return;
    await api.deleteCluster(c.cluster_id); onRefresh(); onBack();
  };

  const handleRename = async () => {
    if (!renameVal.trim()) return;
    await api.nameCluster(c.cluster_id, renameVal.trim());
    setShowRename(false); onRefresh();
  };

  const openMerge = async () => {
    const res    = await api.getClusterStats();
    const others = (res.clusters || []).filter(cl => cl.cluster_id !== c.cluster_id);
    setAllClusters(others); setMergeTarget(others[0]?.cluster_id || ""); setShowMerge(true);
  };

  const handleMerge = async () => {
    if (!mergeTarget || !window.confirm("This cannot be undone. Merge?")) return;
    await api.mergeClusters(c.cluster_id, mergeTarget);
    setShowMerge(false); onRefresh(); onBack();
  };

  // ── Move snapshot to a different cluster ───────────────────────────────────
  const openMove = async (imagePath) => {
    const res    = await api.getClusterStats();
    const others = (res.clusters || []).filter(cl => cl.cluster_id !== c.cluster_id);
    setAllClusters(others);
    setMoveTarget(others[0]?.cluster_id || "");
    setMovingSnap(imagePath);
    setShowMove(true);
  };

  const handleMove = async () => {
    if (!moveTarget || !movingSnap) return;
    const target = allClusters.find(cl => cl.cluster_id === moveTarget);
    await api.updateSnapshotCluster(movingSnap, moveTarget, target?.person_name || "unknown");
    setShowMove(false);
    setMovingSnap(null);
    setLightbox(null);
    onRefresh();
  };
  // ──────────────────────────────────────────────────────────────────────────

  const handleDeleteCrop = async () => {
    if (!lightbox || !window.confirm("Permanently delete this crop detection?")) return;
    try { await api.deleteCrop(lightbox.image_path); setLightbox(null); onRefresh(); }
    catch (e) { alert(e.message); }
  };

  const groups = groupPathsByDate(allPaths);
  const inputStyle = {
    width: "100%", padding: "9px 12px", borderRadius: 7, fontSize: 13,
    background: T.s2, border: `1px solid ${T.border2}`, color: T.text,
    fontFamily: "'IBM Plex Sans', sans-serif", marginBottom: 14, outline: "none",
  };

  return (
    <div style={{ width: "100%" }}>
      <div style={{ marginBottom: 14 }}>
        <Btn variant="ghost" onClick={onBack} style={{ fontSize: 12 }}>← Back</Btn>
      </div>

      <Panel style={{ padding: isMobile ? 14 : 22, marginBottom: 14 }}>
        {/* Crop thumbnails */}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
          {c.crop_paths?.slice(0, isMobile ? 4 : 8).map(p => (
            <img key={p} src={api.imageUrl(p)} alt="crop"
              style={{ width: isMobile ? 40 : 52, height: isMobile ? 58 : 76, objectFit: "cover", borderRadius: 5, border: `1px solid ${T.border2}` }}
              onError={e => { e.target.style.display = "none"; }} />
          ))}
        </div>
        {/* Name */}
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
          <h2 style={{ fontSize: isMobile ? 17 : 20, fontWeight: 700, color: T.text, margin: 0, wordBreak: "break-word" }}>
            {isNamed ? c.person_name : "unknown"}
          </h2>
          {isNamed && <Pill color={T.green}>Named</Pill>}
          <Pill>{c.count} detections</Pill>
        </div>
        {/* Fluid Info grid */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 12, marginBottom: 16 }}>
          {[["Camera(s)", c.cameras.join(", ")], ["Date Range", dateRange], ["Snapshots", allPaths.length], ["Last Seen", lastSeen]].map(([l, v]) => (
            <div key={l} style={{ minWidth: 0 }}>
              <div style={{ fontSize: 10, color: T.muted, textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "'IBM Plex Mono', monospace", marginBottom: 2 }}>{l}</div>
              <div style={{ fontSize: 11, color: T.text, fontFamily: "'IBM Plex Mono', monospace", wordBreak: "break-word" }}>{v}</div>
            </div>
          ))}
        </div>
        {/* Actions */}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <Btn variant="ghost" onClick={() => { setRenameVal(isNamed ? c.person_name : ""); setShowRename(true); }}
            style={{ fontSize: 11, padding: "7px 12px", color: T.accent2, borderColor: "rgba(96,165,250,0.3)" }}>
            ✏ {isNamed ? "Rename" : "Name"}
          </Btn>
          <Btn variant="ghost" onClick={openMerge}
            style={{ fontSize: 11, padding: "7px 12px", color: T.amber, borderColor: "rgba(245,158,11,0.3)" }}>
            ⇄ Merge
          </Btn>
          <Btn variant="ghost" onClick={handleDeleteCluster}
            style={{ fontSize: 11, padding: "7px 12px", color: T.red, borderColor: "rgba(239,68,68,0.3)" }}>
            🗑 Delete
          </Btn>
        </div>
      </Panel>

      <Panel style={{ padding: isMobile ? 14 : 20 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
          <SectionLabel>Snapshot History</SectionLabel>
          {!selectMode ? (
            <Btn variant="ghost" onClick={() => setSelectMode(true)}
              style={{ fontSize: 11, padding: "6px 12px", color: T.accent2, borderColor: "rgba(96,165,250,0.3)" }}>
              ☑ Select to Delete
            </Btn>
          ) : (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <Btn variant="ghost" onClick={() => setSelected(new Set(allPaths))} style={{ fontSize: 11, padding: "6px 10px" }}>All</Btn>
              <Btn variant="ghost" onClick={() => setSelected(new Set())} style={{ fontSize: 11, padding: "6px 10px" }}>Clear</Btn>
              <Btn variant="danger" disabled={!selected.size || deleting} onClick={handleDeleteSelected} style={{ fontSize: 11, padding: "6px 12px" }}>
                {deleting ? "…" : `🗑 (${selected.size})`}
              </Btn>
              <Btn variant="ghost" onClick={() => { setSelectMode(false); setSelected(new Set()); }} style={{ fontSize: 11, padding: "6px 10px" }}>✕</Btn>
            </div>
          )}
        </div>

        {groups.map(([date, paths]) => {
          const sorted = [...paths].sort((a, b) => getPathSortKey(b).localeCompare(getPathSortKey(a)));
          return (
            <div key={date}>
              <div style={{
                fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: T.muted,
                textTransform: "uppercase", letterSpacing: "0.1em",
                padding: "6px 0 8px", borderBottom: `1px solid ${T.border}`,
                marginBottom: 10, marginTop: 14,
                display: "flex", alignItems: "center", gap: 8,
              }}>
                <div style={{ width: 7, height: 7, borderRadius: "50%", background: T.accent, flexShrink: 0 }} />
                {date} · {paths.length} snap{paths.length !== 1 ? "s" : ""}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(100px, 1fr))", gap: 8, marginBottom: 6 }}>
                {sorted.map(p => {
                  const t = parsePathTime(p);
                  const isSel = selected.has(p);
                  return (
                    <div key={p}
                      onClick={() => {
                        if (selectMode) toggleSelect(p);
                        else setLightbox({ image_path: p, camera: c.cameras[0], date, time: t, similarity: 0 });
                      }}
                      style={{
                        position: "relative", cursor: "pointer", borderRadius: 5,
                        outline: (selectMode && isSel) ? `3px solid ${T.accent}` : "none",
                        outlineOffset: 2,
                      }}
                    >
                      <div style={{ paddingTop: "75%", position: "relative" }}>
                        <img src={api.imageUrl(p)} alt="snap"
                          style={{
                            position: "absolute", top: 0, left: 0, width: "100%", height: "100%",
                            objectFit: "cover", borderRadius: 5, border: `1px solid ${T.border2}`,
                            opacity: selectMode ? (isSel ? 1 : 0.5) : 1,
                            transition: "opacity .15s", display: "block",
                          }}
                          onError={e => { e.target.parentElement.style.display = "none"; }} />
                      </div>
                      <div style={{
                        position: "absolute", bottom: 4, left: 4,
                        background: "rgba(0,0,0,0.68)", color: "#fff",
                        fontSize: 9, padding: "2px 5px", borderRadius: 3,
                        fontFamily: "'IBM Plex Mono', monospace",
                      }}>{t.slice(0, 5)}</div>
                      {selectMode && (
                        <div style={{
                          position: "absolute", top: 4, right: 4,
                          width: 20, height: 20, borderRadius: "50%",
                          background: isSel ? T.accent : T.surface,
                          border: `2px solid ${isSel ? T.accent : T.border2}`,
                          display: "flex", alignItems: "center", justifyContent: "center",
                        }}>
                          {isSel && (
                            <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
                              <polyline points="2,6 5,9 10,3" stroke="white" strokeWidth="2"
                                strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </Panel>

      {lightbox && (
        <Lightbox
          meta={lightbox}
          onClose={() => setLightbox(null)}
          onDelete={handleDeleteCrop}
          onMove={() => openMove(lightbox.image_path)}
        />
      )}

      {showRename && (
        <Modal title="Name this person" subtitle={c.cluster_id} onClose={() => setShowRename(false)}>
          <input value={renameVal} onChange={e => setRenameVal(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleRename()}
            placeholder="e.g. Neighbor, Delivery Driver…" autoFocus style={inputStyle} />
          <div style={{ display: "flex", gap: 10 }}>
            <Btn onClick={handleRename} style={{ flex: 1, padding: "9px" }}>Save</Btn>
            <Btn variant="ghost" onClick={() => setShowRename(false)} style={{ flex: 1, padding: "9px" }}>Cancel</Btn>
          </div>
        </Modal>
      )}

      {showMerge && (
        <Modal title="Merge Cluster" onClose={() => setShowMerge(false)}>
          <div style={{ fontSize: 12, color: T.muted2, marginBottom: 12 }}>
            Merge <strong style={{ color: T.text }}>{isNamed ? c.person_name : c.cluster_id}</strong> into:
          </div>
          <select value={mergeTarget} onChange={e => setMergeTarget(e.target.value)} style={inputStyle}>
            {allClusters.map(cl => (
              <option key={cl.cluster_id} value={cl.cluster_id}>
                {cl.person_name !== "unknown" ? cl.person_name : cl.cluster_id} ({cl.count})
              </option>
            ))}
          </select>
          <div style={{ display: "flex", gap: 10 }}>
            <Btn onClick={handleMerge} style={{ flex: 1, padding: "9px", background: T.amber, color: "#000" }}>Merge</Btn>
            <Btn variant="ghost" onClick={() => setShowMerge(false)} style={{ flex: 1, padding: "9px" }}>Cancel</Btn>
          </div>
        </Modal>
      )}

      {showMove && (
        <Modal title="Move Snapshot" subtitle={movingSnap} onClose={() => { setShowMove(false); setMovingSnap(null); }}>
          <div style={{ fontSize: 12, color: T.muted2, marginBottom: 12 }}>
            Reassign this snapshot to a different cluster:
          </div>
          <select value={moveTarget} onChange={e => setMoveTarget(e.target.value)} style={inputStyle}>
            {allClusters.map(cl => (
              <option key={cl.cluster_id} value={cl.cluster_id}>
                {cl.person_name !== "unknown" ? cl.person_name : cl.cluster_id} ({cl.count})
              </option>
            ))}
          </select>
          <div style={{ display: "flex", gap: 10 }}>
            <Btn
              onClick={handleMove}
              disabled={!moveTarget}
              style={{ flex: 1, padding: "9px", background: T.purple, color: "#fff" }}
            >
              ↗ Move
            </Btn>
            <Btn variant="ghost" onClick={() => { setShowMove(false); setMovingSnap(null); }} style={{ flex: 1, padding: "9px" }}>Cancel</Btn>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ─── VisitorsTab ──────────────────────────────────────────────────────────────
function VisitorsTab() {
  const { isMobile } = useBreakpoint();
  const [clusters, setClusters] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try { const data = await api.getClusterStats(); setClusters(data.clusters || []); setStats(data.stats || {}); }
    catch { } setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleRefresh = async () => {
    const data = await api.getClusterStats(); setClusters(data.clusters || []); setStats(data.stats || {});
  };

  const handleRunClustering = async () => {
    try { const res = await api.runClustering(); alert(`Done! Found ${res.clusters} clusters. ${res.noise} unmatched.`); load(); }
    catch (e) { alert("Clustering failed: " + e.message); }
  };

  if (detail !== null && clusters[detail]) {
    return <VisitorDetail cluster={clusters[detail]} onBack={() => setDetail(null)} onRefresh={handleRefresh} />;
  }

  const named = clusters.filter(c => c.person_name !== "unknown").length;
  const topVisit = clusters[0]?.count || 0;

  return (
    <div style={{ width: "100%" }}>
      <Panel style={{
        padding: isMobile ? 14 : 18, marginBottom: 14,
        display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10,
      }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: T.text }}>Person Clusters</div>
          {!isMobile && <div style={{ fontSize: 12, color: T.muted, marginTop: 2 }}>Group detected persons by appearance similarity</div>}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Btn onClick={handleRunClustering} style={{ fontSize: isMobile ? 12 : 13 }}>⚙ {isMobile ? "Cluster" : "Run Clustering"}</Btn>
          <Btn variant="ghost" onClick={load} style={{ fontSize: 13 }}>↻</Btn>
        </div>
      </Panel>

      {stats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10, marginBottom: 14 }}>
          <StatCard val={clusters.length} label="Persons" color={T.accent} />
          <StatCard val={named} label="Named" color={T.green} />
          <StatCard val={stats.total_crops || 0} label="Detections" color={T.amber} />
          <StatCard val={topVisit} label="Top" color={T.purple} />
        </div>
      )}

      {loading && <Loader text="Loading visitors…" />}
      {!loading && clusters.length === 0 && (
        <div style={{ textAlign: "center", padding: "60px 0", fontSize: 13, color: T.muted }}>
          Click "Cluster" to group detected persons.
        </div>
      )}

      {!loading && clusters.length > 0 && (
        /* Fluid Grid for Visitor Profiles */
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 12 }}>
          {clusters.map((c, i) => {
            const isNamed  = c.person_name !== "unknown";
            const thumbSrc = c.crop_paths?.[0] ? api.imageUrl(c.crop_paths[0])
              : c.source_paths?.[0] ? api.imageUrl(c.source_paths[0]) : null;
            const newest   = latestPath(c.source_paths || []);
            const lastSeen = newest ? `${parsePathDate(newest)} ${parsePathTime(newest).slice(0, 5)}` : "—";
            const cams     = c.cameras.slice(0, 2).join(", ") + (c.cameras.length > 2 ? ` +${c.cameras.length - 2}` : "");

            return (
              <div key={c.cluster_id} onClick={() => setDetail(i)}
                style={{
                  background: T.surface, border: `1px solid ${T.border}`,
                  borderRadius: 10, overflow: "hidden", cursor: "pointer",
                  transition: "border-color .2s", display: "flex", flexDirection: "column"
                }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = T.accent; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = T.border; }}
              >
                <div style={{ position: "relative", paddingTop: "125%", background: T.s2 }}>
                  {thumbSrc ? (
                    <img src={thumbSrc} alt="person"
                      style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", objectFit: "cover", objectPosition: "top" }}
                      onError={e => { e.target.style.display = "none"; }} />
                  ) : (
                    <div style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 36 }}>👤</div>
                  )}
                  <div style={{
                    position: "absolute", top: 6, right: 6,
                    background: "rgba(37,99,235,0.9)", color: "#fff",
                    fontSize: 10, fontWeight: 700, fontFamily: "'IBM Plex Mono', monospace",
                    padding: "2px 7px", borderRadius: 20,
                  }}>{c.count}×</div>
                  {isNamed && (
                    <div style={{
                      position: "absolute", bottom: 0, left: 0, right: 0, padding: "8px 10px",
                      background: "linear-gradient(to top, rgba(0,0,0,0.65), transparent)",
                      color: "#fff", fontSize: 12, fontWeight: 600,
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis"
                    }}>{c.person_name}</div>
                  )}
                </div>
                <div style={{ padding: "10px 12px", flexGrow: 1, display: "flex", flexDirection: "column", justifyContent: "center" }}>
                  <div style={{ fontWeight: 600, fontSize: 12, color: T.text, marginBottom: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {isNamed ? c.person_name : "unknown"}
                  </div>
                  {!isMobile && (
                    <div style={{ fontSize: 10, color: T.muted2, display: "flex", flexDirection: "column", gap: 2 }}>
                      <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>📹 {cams}</span>
                      <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>⏰ {lastSeen}</span>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── StatsTab ─────────────────────────────────────────────────────────────────
function StatsTab() {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getClusterStats().then(d => { setData(d); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  if (loading) return <Loader text="Loading statistics…" />;
  if (!data)   return <div style={{ color: T.red, textAlign: "center", padding: 40 }}>Failed to load stats.</div>;

  const { clusters = [], stats = {} } = data;

  const hourCounts   = new Array(24).fill(0);
  const dayCounts    = {};
  const camPersonMap = {};
  clusters.forEach(c => {
    (c.source_paths || []).forEach(p => {
      const h = parsePathHour(p);
      if (h !== null) hourCounts[h]++;
      try { const d = parsePathDate(p); dayCounts[d] = (dayCounts[d] || 0) + 1; } catch {}
    });
    (c.cameras || []).forEach(cam => {
      if (!camPersonMap[cam]) camPersonMap[cam] = new Set();
      camPersonMap[cam].add(c.cluster_id);
    });
  });

  const maxHour  = Math.max(...hourCounts, 1);
  const peakHour = hourCounts.indexOf(Math.max(...hourCounts));

  const dowLabels = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
  const dowCounts = new Array(7).fill(0);
  Object.entries(dayCounts).forEach(([d, cnt]) => {
    try { const [dd,mm,yyyy] = d.split("/"); dowCounts[new Date(`${yyyy}-${mm}-${dd}T12:00:00`).getDay()] += cnt; } catch {}
  });
  const maxDow = Math.max(...dowCounts, 1);

  const namedCount    = clusters.filter(c => c.person_name !== "unknown").length;
  const unknownCount  = clusters.length - namedCount;
  const identifyRate  = clusters.length ? Math.round(namedCount / clusters.length * 100) : 0;
  const avgDetections = clusters.length ? Math.round(clusters.reduce((s, c) => s + c.count, 0) / clusters.length) : 0;

  const recentDays = Object.entries(dayCounts)
    .map(([d, cnt]) => { const [dd,mm,yyyy] = d.split("/"); return { display: d, sortKey: `${yyyy}-${mm}-${dd}`, cnt }; })
    .sort((a, b) => a.sortKey.localeCompare(b.sortKey)).slice(-14);
  const maxDay = Math.max(...recentDays.map(x => x.cnt), 1);

  const cameraRows = Object.entries(stats.camera_counts || {}).sort((a, b) => b[1] - a[1]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, width: "100%" }}>
      {/* Fluid Grids for Stats Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10 }}>
        <StatCard val={stats.total_images   || 0} label="Snapshots"  color={T.text} />
        <StatCard val={stats.total_crops    || 0} label="Detections" color={T.accent} />
        <StatCard val={stats.total_clusters || 0} label="Persons"    color={T.purple} />
        <StatCard val={`${identifyRate}%`}         label="ID Rate"    color={T.green} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10 }}>
        <StatCard val={`${String(peakHour).padStart(2,"0")}:00`} label="Peak Hour"  color={T.amber} />
        <StatCard val={avgDetections}  label="Avg / Person" color={T.text} />
        <StatCard val={namedCount}     label="Named"        color={T.green} />
        <StatCard val={unknownCount}   label="unknown"      color={T.muted2} />
      </div>

      {/* Fluid Grid for Charts/Lists */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
        <Panel style={{ padding: 16 }}>
          <SectionLabel>Hourly Activity</SectionLabel>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 1, height: 72 }}>
            {hourCounts.map((v, h) => (
              <div key={h} title={`${String(h).padStart(2,"0")}:00 · ${v}`}
                style={{
                  flex: 1, borderRadius: "3px 3px 0 0", minWidth: 2,
                  height: Math.max(4, Math.round(v / maxHour * 68)),
                  background: h === peakHour ? T.accent : T.border,
                  border: `1px solid ${h === peakHour ? T.accent : T.border2}`,
                }} />
            ))}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: T.muted, marginTop: 4 }}>
            {["00","06","12","18","23"].map(l => <span key={l}>{l}:00</span>)}
          </div>
        </Panel>
        
        <Panel style={{ padding: 16 }}>
          <SectionLabel>Day of Week</SectionLabel>
          <div style={{ display: "flex", gap: "2%", alignItems: "flex-end", height: 72 }}>
            {dowCounts.map((v, d) => (
              <div key={d} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
                <div title={`${dowLabels[d]}: ${v}`}
                  style={{
                    width: "100%", borderRadius: "3px 3px 0 0",
                    height: Math.max(4, Math.round(v / maxDow * 64)),
                    background: T.purple, opacity: 0.3 + 0.7 * (v / maxDow),
                  }} />
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: T.muted }}>
                  {dowLabels[d].slice(0, 1)}
                </span>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      {recentDays.length > 1 && (
        <Panel style={{ padding: 16 }}>
          <SectionLabel>Daily Trend (last {recentDays.length} days)</SectionLabel>
          <div style={{ display: "flex", gap: 2, alignItems: "flex-end", height: 64 }}>
            {recentDays.map(({ display, cnt }) => (
              <div key={display} title={`${display}: ${cnt}`}
                style={{
                  flex: 1, minWidth: 2, borderRadius: "2px 2px 0 0",
                  height: Math.max(3, Math.round(cnt / maxDay * 56)),
                  background: T.green, opacity: 0.3 + 0.7 * (cnt / maxDay),
                }} />
            ))}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: T.muted, marginTop: 4 }}>
            <span>{recentDays[0]?.display}</span>
            <span>{recentDays[recentDays.length - 1]?.display}</span>
          </div>
        </Panel>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
        <Panel style={{ padding: 16 }}>
          <SectionLabel>Snapshots by Camera</SectionLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {cameraRows.map(([cam, count]) => (
              <div key={cam}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4, flexWrap: "wrap" }}>
                  <Pill>{cam}</Pill>
                  <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                    <span style={{ fontSize: 10, color: T.muted }}>{camPersonMap[cam]?.size || 0} persons</span>
                    <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 700, color: T.text }}>{count}</span>
                  </div>
                </div>
                <div style={{ height: 5, background: T.s2, borderRadius: 3, overflow: "hidden" }}>
                  <div style={{ height: "100%", borderRadius: 3, background: T.accent, width: `${Math.round(count / stats.total_images * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        </Panel>
        <Panel style={{ padding: 16 }}>
          <SectionLabel>Most Frequent Visitors</SectionLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {clusters.slice(0, 7).map((c, i) => {
              const isN = c.person_name !== "unknown";
              const max = clusters[0]?.count || 1;
              return (
                <div key={c.cluster_id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: T.muted, width: 12, textAlign: "right", flexShrink: 0 }}>{i + 1}</span>
                  {c.source_paths?.[0] && (
                    <img src={api.imageUrl(c.source_paths[0])} alt="person"
                      style={{ width: 28, height: 38, objectFit: "cover", borderRadius: 4, border: `1px solid ${T.border2}`, flexShrink: 0 }}
                      onError={e => { e.target.style.display = "none"; }} />
                  )}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 11, fontWeight: 500, color: isN ? T.text : T.muted2, marginBottom: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {isN ? c.person_name : c.cluster_id}
                    </div>
                    <div style={{ height: 4, background: T.s2, borderRadius: 2, overflow: "hidden" }}>
                      <div style={{ height: "100%", borderRadius: 2, background: isN ? T.green : T.muted, width: `${Math.round(c.count / max * 100)}%` }} />
                    </div>
                  </div>
                  <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 700, color: T.accent2, flexShrink: 0 }}>{c.count}×</span>
                </div>
              );
            })}
          </div>
        </Panel>
      </div>

      {clusters.length > 0 && (
        <Panel style={{ padding: 16, overflow: "hidden" }}>
          <SectionLabel>Visitor Schedule (top {Math.min(clusters.length, 12)})</SectionLabel>
          <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch", paddingBottom: 8 }}>
            <table style={{ borderCollapse: "collapse", minWidth: 500, width: "100%" }}>
              <thead>
                <tr>
                  <th style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: T.muted, fontWeight: 500, textAlign: "left", paddingBottom: 6, paddingRight: 10, whiteSpace: "nowrap" }}>Person</th>
                  {Array.from({ length: 24 }, (_, h) => (
                    <th key={h} style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 8, color: T.muted, fontWeight: 400, paddingBottom: 6, minWidth: 16 }}>
                      {String(h).padStart(2, "0")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {clusters.slice(0, 12).map(c => {
                  const hrs = {};
                  (c.source_paths || []).forEach(p => { const h = parsePathHour(p); if (h !== null) hrs[h] = (hrs[h] || 0) + 1; });
                  const maxV = Math.max(...Object.values(hrs), 1);
                  return (
                    <tr key={c.cluster_id}>
                      <td style={{ paddingRight: 10, paddingBottom: 3, whiteSpace: "nowrap" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                          {c.crop_paths?.[0] && (
                            <img src={api.imageUrl(c.crop_paths[0])} alt="crop"
                              style={{ width: 16, height: 22, objectFit: "cover", borderRadius: 2, border: `1px solid ${T.border2}`, flexShrink: 0 }}
                              onError={e => { e.target.style.display = "none"; }} />
                          )}
                          <span style={{ fontSize: 10, color: T.text, maxWidth: 100, overflow: "hidden", textOverflow: "ellipsis" }}>
                            {c.person_name !== "unknown" ? c.person_name : c.cluster_id}
                          </span>
                        </div>
                      </td>
                      {Array.from({ length: 24 }, (_, h) => {
                        const cnt = hrs[h] || 0;
                        return (
                          <td key={h} style={{ paddingBottom: 3 }}>
                            <div title={`${String(h).padStart(2,"0")}:00 · ${cnt}`}
                              style={{
                                width: 12, height: 12, margin: "0 auto", borderRadius: 2,
                                background: cnt ? T.accent : "#f1f5f9",
                                opacity: cnt ? (0.25 + 0.75 * cnt / maxV) : 1,
                                border: `1px solid ${cnt ? "transparent" : T.border}`,
                              }} />
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 10 }}>
            <span style={{ fontSize: 10, color: T.muted }}>Low</span>
            {[0.15, 0.4, 0.65, 0.85, 1.0].map(o => (
              <div key={o} style={{ width: 14, height: 14, borderRadius: 2, background: T.accent, opacity: o, border: `1px solid ${T.border2}` }} />
            ))}
            <span style={{ fontSize: 10, color: T.muted }}>High</span>
          </div>
        </Panel>
      )}
    </div>
  );
}

// ─── App root ─────────────────────────────────────────────────────────────────
export default function App() {
  const { isMobile } = useBreakpoint();
  const [tab, setTab]   = useState("search");
  const [meta, setMeta] = useState(null);

  useEffect(() => { api.getMetadata().then(setMeta).catch(() => {}); }, []);

  const tabs = [
    { id: "search",   label: isMobile ? "🔍" : "🔍 Search" },
    { id: "visitors", label: isMobile ? "👤" : "👤 Visitors" },
    { id: "stats",    label: isMobile ? "📊" : "📊 Statistics" },
  ];

  return (
    <div style={{ fontFamily: "'IBM Plex Sans', sans-serif", background: T.bg, color: T.text, minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body { width: 100%; height: 100%; overflow-x: hidden; }
        body { background: ${T.bg}; }
        input, select, option { color: ${T.text}; background: ${T.s2}; max-width: 100%; }
        input::placeholder { color: ${T.muted}; }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: ${T.bg}; }
        ::-webkit-scrollbar-thumb { background: ${T.border2}; border-radius: 3px; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
      `}</style>

      {/* Header */}
      <header style={{
        background: T.surface, borderBottom: `1px solid ${T.border}`,
        position: "sticky", top: 0, zIndex: 50,
      }}>
        <div style={{
          maxWidth: 1200, margin: "0 auto", width: "100%",
          padding: isMobile ? "10px 14px" : "14px 24px",
          display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 30, height: 30, background: T.accent, borderRadius: 7, flexShrink: 0,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
                <circle cx="12" cy="12" r="3"/>
                <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/>
              </svg>
            </div>
            <div>
              <div style={{ fontSize: isMobile ? 13 : 14, fontWeight: 600, color: T.text }}>CCTV Search & DVR</div>
              <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: T.muted }}>
                {meta ? `${meta.total} images indexed` : "Connecting…"}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: T.muted }}>
            <div style={{ width: 7, height: 7, borderRadius: "50%", background: T.green, animation: "pulse 2s ease-in-out infinite" }} />
            {!isMobile && "System Online"}
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main style={{ maxWidth: 1200, width: "100%", margin: "0 auto", flex: 1, padding: isMobile ? "14px 12px 80px" : "24px", display: "flex", flexDirection: "column" }}>
        
        {/* Tab bar */}
        <div style={{
          display: "flex", gap: 4,
          background: T.surface, border: `1px solid ${T.border}`,
          borderRadius: 8, padding: 4, marginBottom: 18,
          width: isMobile ? "100%" : "auto",
          alignSelf: "flex-start"
        }}>
          {tabs.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              style={{
                flex: 1,
                padding: isMobile ? "10px 0" : "7px 18px",
                fontSize: isMobile ? 20 : 13, fontWeight: 500,
                borderRadius: 5, border: "none", cursor: "pointer",
                fontFamily: "'IBM Plex Sans', sans-serif", transition: "all .15s",
                background: tab === t.id ? T.accent    : "transparent",
                color:      tab === t.id ? "#fff"      : T.muted2,
                boxShadow:  tab === t.id ? "0 2px 8px rgba(37,99,235,0.3)" : "none",
                textAlign: "center",
              }}>
              {t.label}
            </button>
          ))}
        </div>

        {tab === "search"   && <SearchTab cameras={meta?.cameras || []} dates={meta?.dates || []} />}
        {tab === "visitors" && <VisitorsTab />}
        {tab === "stats"    && <StatsTab />}
      </main>
    </div>
  );
}