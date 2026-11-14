import { useQueryClient } from "@tanstack/react-query";
import { Mail, Plug, Puzzle, RefreshCcw, RotateCcw, Send, ServerCog } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { api, errorText } from "@/api/client";
import { keys, useCall, useSettings } from "@/api/queries";
import type { Setting } from "@/api/types";
import { MarketplaceSettings } from "@/components/Marketplace";
import { Page, PageHead, useMe } from "@/components/Shell";
import { Button, Callout, Skeleton, Switch, Tag } from "@/components/ui/basics";
import { Modal, useToast } from "@/components/ui/overlay";

const GROUPS: { title: string; text: string; keys: string[] }[] = [
  { title: "Sign-in and security", text: "Second factors and how long a session lasts before signing in again", keys: ["require_second_factor", "session_idle_minutes", "session_max_hours"] },
  { title: "E-mail", text: "The mailbox that sends sign-in codes, for example a Gmail account with an app password", keys: ["mail_from", "smtp_host", "smtp_port", "smtp_security", "smtp_username", "smtp_password", "mail_templates_dir"] },
  { title: "Limits", text: "Requests per minute, and how many instances, how often. 0 turns a limit off", keys: ["rate_limit_reads_per_minute", "rate_limit_changes_per_minute", "max_instances", "max_instances_per_user", "create_cooldown_minutes"] },
  { title: "New instances", text: "What a new instance starts with; each instance can change its own", keys: ["auto_pause", "idle_hours", "auto_update", "auto_upgrade", "delete_after_days", "odoo_admin_password"] },
  { title: "Backups", text: "Each instance used during the day is backed up once, at this time; it keeps only its latest daily backup", keys: ["daily_backups", "daily_backup_time", "timezone"] },
  { title: "Odoo versions and images", text: "Which versions are offered and where Odoo and PostgreSQL come from", keys: ["odoo_versions", "odoo_min_version", "odoo_image", "postgres_image"] },
  { title: "Enterprise add-ons", text: "Where the Enterprise add-ons of each version are", keys: ["enterprise_path", "enterprise_git_url", "enterprise_git_branch", "enterprise_marker"] },
  { title: "Code updates and monitoring", text: "How often GitHub is checked and figures are measured", keys: ["poll_minutes", "github_webhook_secret", "metrics_interval_seconds", "cloudflared_image"] },
  { title: "Contact and appearance", text: "Who people are told to contact, and the accent colour of the panel and its e-mails", keys: ["admin_contact_name", "admin_contact_email", "admin_contact_phone", "brand_color"] },
];
const PLUGINS = { title: "Plugins", text: "Each chooses a plugin; a change applies when the panel restarts", keys: ["mailer", "second_factors", "update_triggers", "enterprise_source", "auth", "rate_limiter"] };

const TITLES: Record<string, string> = {
  require_second_factor: "Second factor required for",
  session_idle_minutes: "Sign out after inactivity, minutes",
  session_max_hours: "Longest session, hours",
  mail_from: "Sender",
  smtp_host: "Mail server",
  smtp_port: "Port",
  smtp_security: "Encryption",
  smtp_username: "User name",
  smtp_password: "Password",
  mail_templates_dir: "Own e-mail templates folder",
  rate_limit_reads_per_minute: "Reading requests per minute",
  rate_limit_changes_per_minute: "Changing requests per minute",
  max_instances: "Instances on this server",
  max_instances_per_user: "Instances per person",
  create_cooldown_minutes: "Minutes between two creations",
  auto_pause: "Pause when idle",
  idle_hours: "Pause after, hours without visits",
  auto_update: "Get new code automatically",
  auto_upgrade: "Upgrade changed modules",
  delete_after_days: "Lifetime, days",
  odoo_admin_password: "Odoo admin password",
  odoo_versions: "Versions offered",
  odoo_min_version: "Oldest version offered",
  odoo_image: "Odoo image",
  postgres_image: "PostgreSQL image",
  enterprise_path: "Folder",
  enterprise_git_url: "Git repository",
  enterprise_git_branch: "Branch of a version",
  enterprise_marker: "Module that proves the add-ons are there",
  poll_minutes: "Check GitHub every, minutes",
  github_webhook_secret: "GitHub webhook secret",
  metrics_interval_seconds: "Measure every, seconds",
  cloudflared_image: "Cloudflare connector image",
  admin_contact_name: "Contact name",
  admin_contact_email: "Contact e-mail",
  admin_contact_phone: "Contact phone",
  brand_color: "Accent colour",
  marketplace: "Use the marketplace",
  mailer: "Mailer",
  second_factors: "Second factors offered",
  update_triggers: "Update triggers",
  enterprise_source: "Enterprise source",
  auth: "Authenticator",
  rate_limiter: "Rate limiter",
};

const CHOICES: Record<string, [string, string][]> = {
  require_second_factor: [["none", "Nobody"], ["admins", "Super admins and administrators"], ["everyone", "Everyone"]],
  smtp_security: [["starttls", "STARTTLS (port 587)"], ["ssl", "SSL (port 465)"], ["none", "None"]],
  mailer: [["smtp", "SMTP"], ["none", "No e-mail"]],
  enterprise_source: [["folder", "Folder"], ["git", "Git repository"], ["none", "None (Community only)"]],
};

type Value = string | number | boolean;

function Editor({ setting, value, onChange }: { setting: Setting; value: Value; onChange: (value: Value) => void }) {
  if (setting.secret)
    return (
      <input
        className="input"
        type="password"
        autoComplete="new-password"
        placeholder={setting.value ? "Set. Type to replace it" : "Not set"}
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  const choices = CHOICES[setting.key];
  if (choices)
    return (
      <select className="select" value={String(value)} onChange={(e) => onChange(e.target.value)}>
        {choices.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
      </select>
    );
  if (setting.key === "brand_color")
    return (
      <div className="row">
        <input type="color" aria-label="Pick a colour" value={String(value)} onChange={(e) => onChange(e.target.value)}
          style={{ width: 40, height: 36, padding: 2, border: "1px solid var(--hairline-strong)", borderRadius: 8, background: "var(--surface)" }} />
        <input className="input mono" value={String(value)} onChange={(e) => onChange(e.target.value)} />
      </div>
    );
  if (setting.type === "boolean") return <div style={{ justifySelf: "end" }}><Switch checked={Boolean(value)} onChange={onChange} /></div>;
  if (setting.type === "integer" || setting.type === "number")
    return (
      <input className="input tabular" type="number" min={setting.minimum ?? undefined} step={setting.type === "integer" ? 1 : "any"} value={String(value)}
        onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} />
    );
  return <input className="input" value={String(value)} onChange={(e) => onChange(e.target.value)} />;
}

function Section({ title, text, icon, actions, children }: { title: string; text: string; icon?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      <div className="card-head">
        {icon}
        <div className="spacer">
          <h2>{title}</h2>
          <div className="sub">{text}</div>
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

function TestEmail({ onClose }: { onClose: () => void }) {
  const me = useMe();
  const toast = useToast();
  const [to, setTo] = useState(me.email ?? "");
  const [busy, setBusy] = useState(false);
  const send = async () => {
    setBusy(true);
    try {
      await api.post("/settings/test-email", { to });
      toast("success", "Test e-mail sent", `Check ${to}, and its spam folder the first time`);
      onClose();
    } catch (error) {
      toast("error", "Not sent", errorText(error));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title="Send a test e-mail" description="Uses the saved mail settings" onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" icon={<Send />} loading={busy} disabled={!to} onClick={send}>Send</Button></>}>
      <input className="input" type="email" autoFocus value={to} onChange={(e) => setTo(e.target.value)} />
    </Modal>
  );
}

export function SettingsPage() {
  const { data: settings, isPending } = useSettings();
  const toast = useToast();
  const client = useQueryClient();
  const [draft, setDraft] = useState<Record<string, Value>>({});
  const [testing, setTesting] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const byKey = useMemo(() => Object.fromEntries((settings ?? []).map((s) => [s.key, s])), [settings]);
  const dirty = Object.keys(draft).filter((k) => byKey[k] && (byKey[k]!.secret ? draft[k] !== "" : draft[k] !== byKey[k]!.value));
  const save = useCall((values: Record<string, Value>) => api.patch<Setting[]>("/settings", values), [keys.settings, keys.session]);
  const reset = useCall((key: string) => api.del(`/settings/${key}`), [keys.settings, keys.session]);
  const pending = (settings ?? []).some((s) => s.pending_restart);

  const submit = () =>
    save.mutate(Object.fromEntries(dirty.map((k) => [k, draft[k]!])), {
      onSuccess: () => {
        setDraft({});
        toast("success", "Settings saved");
      },
      onError: (error) => toast("error", "Not saved", errorText(error)),
    });

  const restart = async () => {
    setRestarting(true);
    try {
      await api.post("/server/restart");
      toast("info", "Restarting", "The panel is back in a few seconds");
      setTimeout(async () => {
        for (let i = 0; i < 30; i++) {
          if (await fetch("/healthz").then((r) => r.ok).catch(() => false)) break;
          await new Promise((r) => setTimeout(r, 1000));
        }
        await client.invalidateQueries();
        setRestarting(false);
        toast("success", "The panel restarted");
      }, 2500);
    } catch (error) {
      setRestarting(false);
      toast("error", "Not restarted", errorText(error));
    }
  };

  const rows = (keysOf: string[]) =>
    keysOf.map((key) => {
      const setting = byKey[key];
      if (!setting) return null;
      const value = key in draft ? draft[key]! : setting.secret ? "" : setting.value;
      return (
        <div className="settings-row" key={key}>
          <div>
            <div className="name">
              {TITLES[key] ?? key}
              {setting.secret && <Tag tone={setting.value ? "positive" : undefined}>{setting.value ? "set" : "not set"}</Tag>}
              {setting.pending_restart && <Tag tone="caution">applies after a restart</Tag>}
            </div>
            <div className="desc">{setting.description}</div>
            <div className="env">
              <span>{setting.env}</span>
              {setting.changed_in_panel && !setting.secret && <span>· .env {String(setting.env_value) || "empty"}</span>}
              {setting.changed_in_panel && (
                <Button size="sm" variant="ghost" icon={<RotateCcw />} style={{ height: 24 }} loading={reset.isPending && reset.variables === key}
                  onClick={() => reset.mutate(key, { onSuccess: () => toast("success", `${TITLES[key] ?? key} is back to .env`) })}>
                  Use .env
                </Button>
              )}
            </div>
          </div>
          <Editor setting={setting} value={value} onChange={(v) => setDraft((d) => ({ ...d, [key]: v }))} />
        </div>
      );
    });

  return (
    <Page>
      <PageHead title="Settings">
        Changes apply at once and are kept on top of the server's <code>.env</code>. Use .env brings back its value. Passwords are stored encrypted and never shown.
      </PageHead>
      {isPending ? (
        <Skeleton height={400} />
      ) : (
        <div className="stack">
          {GROUPS.map((group) => (
            <Section
              key={group.title}
              title={group.title}
              text={group.text}
              icon={group.title === "E-mail" ? <Mail /> : undefined}
              actions={group.title === "E-mail" && <Button size="sm" icon={<Send />} onClick={() => setTesting(true)}>Send a test</Button>}
            >
              {rows(group.keys)}
            </Section>
          ))}
          <Section title={PLUGINS.title} text={PLUGINS.text} icon={<Plug />}
            actions={<Button size="sm" variant={pending ? "primary" : "default"} icon={<RefreshCcw />} loading={restarting} onClick={restart}>Restart the panel</Button>}>
            {pending && <div style={{ padding: "12px 20px 0" }}><Callout tone="warning">Some changes wait for a restart. Instances, links and the web app keep running while the panel restarts.</Callout></div>}
            {rows(PLUGINS.keys)}
          </Section>
          <Section title="Marketplace" text="Plugins from Sudoo.sh: the connection to the hub, and linking this panel to an account on app.sudoo.sh" icon={<Puzzle />}
            actions={<Link className="btn sm" to="/plugins" viewTransition>Open Plugins</Link>}>
            {rows(["marketplace"])}
            <MarketplaceSettings />
          </Section>
          <Section title="Server" text="Folders, ports and how the panel is reached. Change these in /opt/odoo/manager/.env" icon={<ServerCog />}>
            <div className="table-wrap">
              <table className="table">
                <tbody>
                  {(settings ?? []).filter((s) => s.applies === "env").map((s) => (
                    <tr key={s.key}>
                      <td className="mono small nowrap">{s.env}</td>
                      <td className="mono small">{String(s.value) || <span className="faint">empty</span>}</td>
                      <td className="small muted">{s.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
          {dirty.length > 0 && (
            <div className="save-bar">
              <span className="spacer">{dirty.length} unsaved {dirty.length === 1 ? "change" : "changes"}</span>
              <Button variant="ghost" onClick={() => setDraft({})}>Discard</Button>
              <Button variant="primary" loading={save.isPending} onClick={submit}>Save</Button>
            </div>
          )}
        </div>
      )}
      {testing && <TestEmail onClose={() => setTesting(false)} />}
    </Page>
  );
}
