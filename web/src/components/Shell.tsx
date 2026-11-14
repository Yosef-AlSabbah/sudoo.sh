import { useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  ChevronRight,
  ChevronsUpDown,
  DatabaseBackup,
  FolderGit2,
  KeyRound,
  LayoutGrid,
  LogOut,
  Menu as MenuIcon,
  Monitor,
  Moon,
  Plus,
  Puzzle,
  ScrollText,
  Settings2,
  Sun,
  UserRound,
  Users,
} from "lucide-react";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from "react-router";
import { api, setCsrfToken } from "@/api/client";
import { useLiveEvents, type Sync } from "@/api/live";
import { keys, useInstances, useMetrics, usePluginNotices, useSession } from "@/api/queries";
import type { Permission, Session } from "@/api/types";
import { percent } from "@/lib/format";
import { applyBrandColor, applyTheme, storedTheme, type ThemeChoice } from "@/lib/theme";
import { Brand } from "./ui/Brand";
import { Button, Callout, Spinner } from "./ui/basics";
import { Menu, useToast } from "./ui/overlay";

const SessionContext = createContext<Session | null>(null);
export const useMe = () => useContext(SessionContext)!;
/** Whether the signed-in role includes a permission (the backend checks it again on every request). */
export const useCan = () => {
  const me = useMe();
  return (permission: Permission) => me.permissions.includes(permission);
};

const RESTRICTED_PAGE = { password: "/change-password", second_factor: "/setup-second-factor" } as const;

/** Pages that need a signed-in session; sends everyone else to the sign-in page. */
export function RequireSession() {
  const { data: session, isPending } = useSession();
  const location = useLocation();
  useEffect(() => applyBrandColor(session?.brand_color), [session?.brand_color]);
  if (isPending)
    return (
      <div style={{ display: "grid", placeItems: "center", height: "100vh" }}>
        <Spinner />
      </div>
    );
  if (!session) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  setCsrfToken(session.csrf_token);
  const task = session.restricted ? RESTRICTED_PAGE[session.restricted] : null;
  if (task && location.pathname !== task) return <Navigate to={task} replace />;
  return (
    <SessionContext.Provider value={session}>
      <Outlet />
    </SessionContext.Provider>
  );
}

export function RequirePermission({ permission, children }: { permission: Permission; children: ReactNode }) {
  return useCan()(permission) ? <>{children}</> : <Navigate to="/" replace />;
}

export function useSignOut() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  return async () => {
    await api.del("/session").catch(() => undefined);
    client.setQueryData(keys.session, null);
    client.clear();
    navigate("/login");
    toast("info", "Signed out");
  };
}

function NavItem({ to, icon, children, end, count }: { to: string; icon: ReactNode; children: ReactNode; end?: boolean; count?: number }) {
  return (
    <NavLink to={to} end={end} viewTransition className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
      {icon}
      <span>{children}</span>
      {count != null && <span className="count">{count}</span>}
    </NavLink>
  );
}

function ThemeButton() {
  const [theme, setTheme] = useState<ThemeChoice>(storedTheme);
  const next: Record<ThemeChoice, ThemeChoice> = { system: "light", light: "dark", dark: "system" };
  const icon = { system: <Monitor />, light: <Sun />, dark: <Moon /> }[theme];
  const label = { system: "System theme", light: "Light theme", dark: "Dark theme" }[theme];
  return (
    <Button
      variant="ghost"
      size="sm"
      icon={icon}
      title={label}
      aria-label={label}
      onClick={() => {
        applyTheme(next[theme]);
        setTheme(next[theme]);
      }}
    />
  );
}

function Sidebar({ open }: { open: boolean }) {
  const me = useMe();
  const can = useCan();
  const { data: instances } = useInstances();
  const signOut = useSignOut();
  const operations = can("backups.manage") || can("audit.view") || can("github.manage");
  const administration = can("settings.manage") || can("accounts.manage") || can("tokens.manage") || can("plugins.view");
  return (
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <Brand />
      <div className="nav-group">Workspace</div>
      <nav>
        <NavItem to="/" end icon={<LayoutGrid />} count={instances?.length}>
          Instances
        </NavItem>
        {can("instances.create") && (
          <NavItem to="/new" icon={<Plus />}>
            New instance
          </NavItem>
        )}
        <NavItem to="/help" icon={<BookOpen />}>
          Help
        </NavItem>
      </nav>
      {operations && (
        <>
          <div className="nav-group">Operations</div>
          <nav>
            {can("backups.manage") && (
              <NavItem to="/backups" icon={<DatabaseBackup />}>
                Backups
              </NavItem>
            )}
            {can("github.manage") && (
              <NavItem to="/github" icon={<FolderGit2 />}>
                GitHub access
              </NavItem>
            )}
            {can("audit.view") && (
              <NavItem to="/activity" icon={<ScrollText />}>
                Audit log
              </NavItem>
            )}
          </nav>
        </>
      )}
      {administration && (
        <>
          <div className="nav-group">Administration</div>
          <nav>
            {can("settings.manage") && (
              <NavItem to="/settings" icon={<Settings2 />}>
                Settings
              </NavItem>
            )}
            {can("plugins.view") && (
              <NavItem to="/plugins" icon={<Puzzle />}>
                Plugins
              </NavItem>
            )}
            {can("accounts.manage") && (
              <NavItem to="/accounts" icon={<Users />}>
                Accounts
              </NavItem>
            )}
            {can("tokens.manage") && (
              <NavItem to="/tokens" icon={<KeyRound />}>
                API tokens
              </NavItem>
            )}
          </nav>
        </>
      )}
      <div className="sidebar-foot">
        <Menu
          align="left"
          trigger={(toggle) => (
            <button className="user-card" onClick={toggle}>
              <span className="avatar">{(me.first_name?.[0] ?? me.user[0]) + (me.last_name?.[0] ?? "")}</span>
              <span className="who">
                <span className="name truncate">{me.display_name}</span>
                <br />
                <span className="role">{me.role_label}</span>
              </span>
              <ChevronsUpDown />
            </button>
          )}
        >
          {(close) => (
            <>
              <Link to="/account" viewTransition onClick={close}>
                <UserRound /> My account
              </Link>
              <hr />
              <button className="danger" onClick={signOut}>
                <LogOut /> Sign out
              </button>
            </>
          )}
        </Menu>
        <div className="row" style={{ padding: "0 8px" }}>
          <span className="xsmall faint">Sudoo.sh</span>
          <span className="spacer" />
          <ThemeButton />
        </div>
      </div>
    </aside>
  );
}

/** Nothing while connected; a small notice only while the connection to the server is lost. */
function Reconnecting({ sync }: { sync: Sync }) {
  const [lost, setLost] = useState(false);
  useEffect(() => {
    if (sync.state === "open") {
      setLost(false);
      return;
    }
    const timer = setTimeout(() => setLost(true), 3000); // short drops pass unnoticed
    return () => clearTimeout(timer);
  }, [sync.state]);
  if (!lost) return null;
  return (
    <div className="reconnecting" role="status">
      <span className="spinner" />
      {sync.state === "closed" ? "Signed out. Reload to sign in again" : "Reconnecting"}
    </div>
  );
}

const CRUMBS: Record<string, string> = {
  "": "Instances",
  new: "New instance",
  settings: "Settings",
  plugins: "Plugins",
  accounts: "Accounts",
  tokens: "API tokens",
  backups: "Backups",
  activity: "Audit log",
  github: "GitHub access",
  account: "My account",
  help: "Help",
};

function Topbar({ onMenu }: { onMenu: () => void }) {
  const location = useLocation();
  const { data: metrics } = useMetrics();
  const parts = location.pathname.split("/").filter(Boolean);
  const server = metrics?.server;
  return (
    <header className="topbar">
      <Button className="menu-button" variant="ghost" icon={<MenuIcon />} onClick={onMenu} aria-label="Menu" />
      <div className="crumbs">
        {parts[0] === "i" && parts[1] ? (
          <>
            <Link to="/" viewTransition>
              Instances
            </Link>
            <ChevronRight />
            <span className="current truncate">{parts[1]}</span>
          </>
        ) : (
          <span className="current">{CRUMBS[parts[0] ?? ""] ?? "Sudoo.sh"}</span>
        )}
      </div>
      <span className="spacer" />
      {server?.cpu_percent != null && (
        <span className="meter hide-sm" title="The server's processor and memory, now">
          CPU <b>{percent(server.cpu_percent)}</b> &nbsp; Memory <b>{percent(server.memory_percent)}</b>
        </span>
      )}
    </header>
  );
}

/** Banners about plugins that need attention: a licence ending, in its grace period or ended, changed files. */
function PluginNotices() {
  const can = useCan();
  const { pathname } = useLocation();
  const { data: notices } = usePluginNotices(can("plugins.view"));
  if (!notices?.length) return null;
  const tone = (level: string) => (level === "danger" ? "danger" : level === "warning" ? "warning" : "info");
  return (
    <div className="notices" role="status">
      {notices.slice(0, 3).map((notice, i) => (
        <Callout key={`${notice.plugin}-${notice.kind}-${i}`} tone={tone(notice.level)}>
          {notice.text}
          {!pathname.startsWith("/plugins") && (
            <>
              {" "}
              <Link to="/plugins/installed" viewTransition>Open Plugins</Link>
            </>
          )}
        </Callout>
      ))}
    </div>
  );
}

/** The frame of every signed-in page: sidebar, top bar, live updates. */
export function Shell() {
  const sync = useLiveEvents(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => setMenuOpen(false), [pathname]);
  return (
    <div className="shell">
      <Sidebar open={menuOpen} />
      {menuOpen && <div className="sidebar-scrim" onClick={() => setMenuOpen(false)} />}
      <div className="main">
        <Topbar onMenu={() => setMenuOpen(true)} />
        <Reconnecting sync={sync} />
        <PluginNotices />
        <Outlet />
      </div>
    </div>
  );
}

export function Page({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return (
    <main className="page" style={wide ? { maxWidth: 1600 } : undefined}>
      {children}
    </main>
  );
}

export function PageHead({ title, children, actions }: { title: ReactNode; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div className="titles">
        <h1>{title}</h1>
        {children && <p>{children}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}
