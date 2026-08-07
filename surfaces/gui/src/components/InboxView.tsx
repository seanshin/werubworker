import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getConnectors,
  getInbox,
  getInboxRouting,
  getPersonas,
  getRecentChannels,
  getUnrouted,
  resolveInboxItem,
  type InboxItem,
  type Persona,
  type RecentChannel,
} from "../api";
import { Icon } from "./Icon";
import { InboxItemCard } from "./InboxItemCard";
import { InboxConfigure } from "./InboxConfigure";
import { PanelHead } from "./IntegrationsView";
import { shortPersonaName } from "../personaScope";

const ICON_FOR: Record<string, "diamond" | "chat" | "code"> = {
  cowork: "diamond",
  chat: "chat",
  code: "code",
};

const KIND_TABS: { key: string; labelKey: string }[] = [
  { key: "all", labelKey: "session:inbox.all" },
  { key: "approval", labelKey: "session:inbox.approvalsFilter" },
  { key: "question", labelKey: "session:inbox.questionsFilter" },
];

const CHIP = (active: boolean) =>
  "text-[11.5px] px-2.5 py-1 rounded-full border " +
  (active
    ? "border-accent text-accent bg-accentSoft"
    : "border-line text-muted hover:border-lineStrong");

// Page-level tabs: underline style, one visual level ABOVE the filter chips.
const TAB = (active: boolean) =>
  "pb-2 -mb-px text-[13px] border-b-2 flex items-center gap-1.5 " +
  (active
    ? "text-ink font-medium border-accent"
    : "text-muted border-transparent hover:text-ink");

export function InboxView({
  onOpenSession,
}: {
  onOpenSession: (sessionId: string, workspace: string, agent: string) => void;
}) {
  const { t } = useTranslation(["session"]);
  const [tab, setTab] = useState<"pending" | "configure">("pending");
  const [items, setItems] = useState<InboxItem[]>([]);
  const [personas, setPersonas] = useState<Persona[] | null>(null);
  const [routing, setRouting] = useState<string | null>(null);
  const [slackConnected, setSlackConnected] = useState(false);
  const [recent, setRecent] = useState<RecentChannel[]>([]);
  const [unroutedCount, setUnroutedCount] = useState(0);
  const [kind, setKind] = useState<string>("all");
  const [personaFilter, setPersonaFilter] = useState<string>("all");

  const load = () => {
    getInbox(undefined, "pending").then(setItems).catch(() => {});
    getUnrouted().then((u) => setUnroutedCount(u.length)).catch(() => setUnroutedCount(0));
  };
  const loadRouting = () =>
    getInboxRouting()
      .then((bindings) => {
        const bound = bindings.find((b) => b.channel);
        setRouting(bound ? `${bound.channel}:${bound.target}` : null);
      })
      .catch(() => setRouting(null));
  useEffect(() => {
    load();
    loadRouting();
    getPersonas().then(setPersonas).catch(() => {});
    getConnectors()
      .then((cs) => setSlackConnected(!!cs.find((c) => c.name === "slack" && c.connected)))
      .catch(() => {});
    getRecentChannels().then(setRecent).catch(() => setRecent([]));
    const timer = setInterval(() => {
      load();
      loadRouting();
    }, 4000);
    return () => clearInterval(timer);
  }, []);

  const resolve = async (id: string, resolution: string) => {
    await resolveInboxItem(id, resolution);
    load();
  };

  const personasWithItems = useMemo(() => {
    const ids = [...new Set(items.map((i) => i.session_agent).filter(Boolean))] as string[];
    return ids.map((id) => ({
      id,
      label: shortPersonaName(personas?.find((p) => p.id === id)?.name, id),
    }));
  }, [items, personas]);

  const visible = items.filter(
    (it) =>
      (kind === "all" || it.kind === kind) &&
      (personaFilter === "all" || it.session_agent === personaFilter),
  );

  const sessionChip = (it: InboxItem) => {
    const exists = it.session_exists !== false;
    const persona = personas?.find((x) => x.id === it.session_agent);
    const chipLabel = it.session_title || it.session_id;
    const iconKey = persona ? ICON_FOR[persona.icon] : undefined;
    const chipIcon = iconKey || "diamond";
    const chipCls = "inbox-chip-ico ico-" + (persona?.icon || "cowork");
    const chipTitle = exists ? chipLabel : t("session:inbox.sessionUnavailable");
    return (
      <button className="inbox-session-chip" title={chipTitle} disabled={!exists}
        onClick={() => exists && onOpenSession(it.session_id, it.session_workspace || "", it.session_agent || "cowork")}>
        <span className={chipCls}><Icon name={chipIcon} size={11} /></span>
        <span className="inbox-chip-label">{chipLabel}</span>
        {exists && <Icon name="chevronRight" size={13} className="inbox-chip-go" />}
      </button>
    );
  };

  const routingName = routing ? recent.find((c) => c.channel === routing)?.name : undefined;
  const routingLabel = routingName ? `#${routingName}` : routing;

  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-4xl mx-auto px-7 py-6">
          <PanelHead
            title={t("session:inbox.title")}
            sub={t("session:inbox.sub")}
          />

          <div className="flex gap-5 border-b border-line mb-4">
            <button
              className={TAB(tab === "pending")}
              data-testid="inbox-tab-pending"
              onClick={() => {
                setTab("pending");
                loadRouting();
                load();
              }}
            >
              {t("session:inbox.pending")}
              {items.length > 0 && (
                <span className="text-[11px] px-1.5 rounded-full bg-accentSoft text-accent leading-4">
                  {items.length}
                </span>
              )}
            </button>
            <button
              className={TAB(tab === "configure")}
              data-testid="inbox-tab-configure"
              onClick={() => setTab("configure")}
            >
              {t("session:inbox.configureTab")}
              {unroutedCount > 0 && (
                <span className="text-[11px] px-1.5 rounded-full bg-warnSoft text-warnInk leading-4">
                  {unroutedCount}
                </span>
              )}
            </button>
          </div>

          {tab === "configure" ? (
            <InboxConfigure />
          ) : (
            <>
              <div className="text-[12px] text-faint -mt-1 mb-4" data-testid="inbox-routing">
                {routing ? (
                  <span>
                    {t("session:inbox.alsoDelivered")}{" "}
                    <span className="text-muted" title={routing}>
                      {routingLabel}
                    </span>
                    {t("session:inbox.repliesResolve")}
                  </span>
                ) : slackConnected ? (
                  <span>{t("session:inbox.deliveredHereOnly")}</span>
                ) : (
                  <span>
                    {t("session:inbox.connectSlackHint")}
                  </span>
                )}
                <button
                  className="text-accent hover:underline"
                  data-testid="inbox-route-configure"
                  onClick={() => setTab("configure")}
                >
                  {t("session:inbox.configureLink")}
                </button>
              </div>

              <div className="flex items-center gap-2 flex-wrap mb-4" data-testid="inbox-filters">
                {KIND_TABS.map((kt) => (
                  <button key={kt.key} className={CHIP(kind === kt.key)} onClick={() => setKind(kt.key)}>
                    {t(kt.labelKey)}
                  </button>
                ))}
                {personasWithItems.length > 1 && (
                  <>
                    <span className="w-px h-4 bg-line mx-1" />
                    <button
                      className={CHIP(personaFilter === "all")}
                      onClick={() => setPersonaFilter("all")}
                    >
                      {t("session:inbox.allCoworkers")}
                    </button>
                    {personasWithItems.map((p) => (
                      <button
                        key={p.id}
                        className={CHIP(personaFilter === p.id)}
                        onClick={() => setPersonaFilter(p.id)}
                      >
                        {p.label}
                      </button>
                    ))}
                  </>
                )}
              </div>

              {visible.length === 0 ? (
                <div className="manage-empty">
                  {items.length === 0 ? t("session:inbox.nothingPending") : t("session:inbox.nothingFilter")}
                </div>
              ) : null}

              <div className="space-y-4">
                {visible.map((it) => (
                  <InboxItemCard key={it.id} item={it} onResolve={resolve} chip={sessionChip(it)} />
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
