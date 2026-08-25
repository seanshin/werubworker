import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const CARD = "rounded-xl2 border border-line bg-panel";

interface TopoNode {
  id: string;
  label: string;
  type: string; // "server" | "service" | "local"
  host?: string;
  status: string;
  x?: number;
  y?: number;
}

interface TopoEdge {
  source: string;
  target: string;
  type: string;
}

const STATUS_COLORS: Record<string, string> = {
  healthy: "#22c55e",
  ok: "#22c55e",
  degraded: "#f59e0b",
  unhealthy: "#ef4444",
  down: "#ef4444",
  unknown: "#6b7280",
};

const NODE_COLORS: Record<string, string> = {
  local: "var(--accent)",
  server: "#3b82f6",
  service: "#8b5cf6",
};

export function TopologyView() {
  const { t } = useTranslation(["session"]);
  const [nodes, setNodes] = useState<TopoNode[]>([]);
  const [edges, setEdges] = useState<TopoEdge[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState<TopoNode | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const fetchTopology = useCallback(() => {
    setLoading(true);
    fetch("/v1/dashboard/topology")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.ok) {
          // Simple force-directed layout
          const laid = layoutNodes(d.nodes || [], d.edges || []);
          setNodes(laid);
          setEdges(d.edges || []);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchTopology();
  }, [fetchTopology]);

  return (
    <div className="flex flex-col h-full gap-3 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t("session:topology.title")}</h2>
        <button
          onClick={fetchTopology}
          disabled={loading}
          className="text-xs px-2 py-1 rounded bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50"
        >
          {loading ? t("session:topology.loading") : t("session:topology.refresh")}
        </button>
      </div>

      <div className="flex gap-3 flex-1 min-h-0">
        {/* SVG Canvas */}
        <div className={CARD + " flex-1 relative overflow-hidden"}>
          {nodes.length === 0 ? (
            <div className="flex items-center justify-center h-full text-muted text-sm">
              {loading ? t("session:topology.loadingCanvas") : t("session:topology.empty")}
            </div>
          ) : (
            <svg ref={svgRef} width="100%" height="100%" viewBox="0 0 800 600">
              {/* Edges */}
              {edges.map((e, i) => {
                const src = nodes.find((n) => n.id === e.source);
                const tgt = nodes.find((n) => n.id === e.target);
                if (!src?.x || !tgt?.x) return null;
                return (
                  <line
                    key={i}
                    x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
                    stroke="var(--line)" strokeWidth="2" strokeDasharray="6 3"
                  />
                );
              })}
              {/* Nodes */}
              {nodes.map((n) => (
                <g
                  key={n.id}
                  transform={`translate(${n.x ?? 0}, ${n.y ?? 0})`}
                  onClick={() => setSelectedNode(n)}
                  style={{ cursor: "pointer" }}
                >
                  <circle
                    r={n.type === "local" ? 28 : n.type === "server" ? 24 : 18}
                    fill={NODE_COLORS[n.type] || "#6b7280"}
                    opacity={0.15}
                    stroke={NODE_COLORS[n.type] || "#6b7280"}
                    strokeWidth="2"
                  />
                  {/* Status indicator */}
                  <circle
                    r="5" cx={n.type === "local" ? 20 : 16} cy={n.type === "local" ? -20 : -16}
                    fill={STATUS_COLORS[n.status] || STATUS_COLORS.unknown}
                  />
                  <text
                    y={n.type === "local" ? 40 : 34}
                    textAnchor="middle" fill="var(--ink)"
                    fontSize="11" fontWeight="500"
                  >
                    {n.label}
                  </text>
                  {/* Type icon text */}
                  <text
                    textAnchor="middle" dominantBaseline="middle"
                    fill={NODE_COLORS[n.type] || "#6b7280"}
                    fontSize={n.type === "local" ? "16" : "12"} fontWeight="700"
                  >
                    {n.type === "local" ? "\u25CF" : n.type === "server" ? "\u2B21" : "\u25C6"}
                  </text>
                </g>
              ))}
            </svg>
          )}
        </div>

        {/* Detail Panel */}
        {selectedNode && (
          <div className={CARD + " w-64 p-4"}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold text-sm">{selectedNode.label}</h3>
              <button onClick={() => setSelectedNode(null)} className="text-muted hover:text-ink text-xs">✕</button>
            </div>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-muted">{t("session:topology.type")}</span>
                <span>{t(`session:topology.type${selectedNode.type === "local" ? "Local" : selectedNode.type === "server" ? "Server" : "Service"}`)}</span>
              </div>
              {selectedNode.host && (
                <div className="flex justify-between">
                  <span className="text-muted">{t("session:topology.host")}</span>
                  <span>{selectedNode.host}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-muted">{t("session:topology.status")}</span>
                <span style={{ color: STATUS_COLORS[selectedNode.status] || STATUS_COLORS.unknown }}>
                  {t(`session:topology.nodeStatus.${selectedNode.status}`, { defaultValue: selectedNode.status })}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">{t("session:topology.connections")}</span>
                <span>{t("session:topology.connectionCount", { count: edges.filter((e) => e.source === selectedNode.id || e.target === selectedNode.id).length })}</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex gap-4 text-xs text-muted">
        <span><span style={{ color: NODE_COLORS.local }}>{"\u25CF"}</span> {t("session:topology.typeLocal")}</span>
        <span><span style={{ color: NODE_COLORS.server }}>{"\u2B21"}</span> {t("session:topology.typeServer")}</span>
        <span><span style={{ color: NODE_COLORS.service }}>{"\u25C6"}</span> {t("session:topology.typeService")}</span>
        <span className="ml-auto">
          <span className="inline-block w-2 h-2 rounded-full bg-green-500 mr-1" />{t("session:topology.legendOk")}
          <span className="inline-block w-2 h-2 rounded-full bg-yellow-500 ml-2 mr-1" />{t("session:topology.legendWarn")}
          <span className="inline-block w-2 h-2 rounded-full bg-red-500 ml-2 mr-1" />{t("session:topology.legendDown")}
        </span>
      </div>
    </div>
  );
}

/** Simple circular layout with type-based grouping */
function layoutNodes(nodes: TopoNode[], edges: TopoEdge[]): TopoNode[] {
  const cx = 400, cy = 300;
  const localNodes = nodes.filter((n) => n.type === "local");
  const serverNodes = nodes.filter((n) => n.type === "server");
  const serviceNodes = nodes.filter((n) => n.type === "service");

  // Place local at center
  localNodes.forEach((n) => { n.x = cx; n.y = cy; });

  // Servers in inner ring
  serverNodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(1, serverNodes.length) - Math.PI / 2;
    n.x = cx + Math.cos(angle) * 150;
    n.y = cy + Math.sin(angle) * 120;
  });

  // Services in outer ring near their connected server
  serviceNodes.forEach((n, i) => {
    const connectedEdge = edges.find((e) => e.target === n.id);
    const parentServer = connectedEdge ? serverNodes.find((s) => s.id === connectedEdge.source) || localNodes[0] : localNodes[0];
    const px = parentServer?.x ?? cx;
    const py = parentServer?.y ?? cy;
    const angle = (2 * Math.PI * i) / Math.max(1, serviceNodes.length);
    n.x = px + Math.cos(angle) * 80;
    n.y = py + Math.sin(angle) * 60;
  });

  return [...localNodes, ...serverNodes, ...serviceNodes];
}
