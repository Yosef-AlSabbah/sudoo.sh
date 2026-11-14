// The documents of /api/v1, as docs/PANEL_API.md describes them. Times are ISO 8601 strings in UTC.

export type Role = "super_admin" | "admin" | "maintainer" | "developer" | "viewer";
export type Permission =
  | "instances.view"
  | "instances.logs"
  | "instances.update"
  | "instances.operate"
  | "instances.create"
  | "instances.restore"
  | "instances.delete"
  | "instances.credentials"
  | "backups.manage"
  | "github.manage"
  | "accounts.manage"
  | "tokens.manage"
  | "audit.view"
  | "plugins.view"
  | "settings.manage";

export interface Profile {
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  phone: string | null;
}
export type InstanceStatus = "online" | "starting" | "busy" | "paused" | "switched_off" | "stopped" | "unknown";
export type JobStatus = "queued" | "running" | "success" | "failed";

export interface Envelope<T> {
  data: T;
  meta?: { total?: number; count?: number; limit?: number; offset?: number; [key: string]: unknown };
}

export interface Session extends Profile {
  user: string;
  display_name: string;
  role: Role;
  role_label: string;
  permissions: Permission[];
  csrf_token: string;
  restricted: "password" | "second_factor" | null;
  must_set_up_second_factor: boolean;
  brand_color: string;
}

export interface RoleInfo {
  name: Role;
  label: string;
  description: string;
  permissions: Permission[];
}

export interface SecondFactorChallenge {
  methods: { name: string; label: string }[];
  sent_to?: string;
}

export interface JobRef {
  id: string;
  action: string;
  status: JobStatus;
  progress_percent: number | null;
}

export interface Job extends JobRef {
  instance: string;
  kind: string;
  requested_by: string;
  started_at: string | null;
  finished_at: string | null;
  steps: { title: string; status: "running" | "done" | "failed" }[];
  notes: { text: string; level: "info" | "warning" }[];
  error: string | null;
}

export interface Usage {
  cpu_percent: number;
  memory_bytes: number;
  memory_limit_bytes?: number;
  memory_percent?: number | null;
  requests_per_minute?: number;
  error_rate_percent?: number | null;
  response_ms_avg?: number | null;
  response_ms_p95?: number | null;
  uptime_seconds?: number | null;
  disk_bytes?: number | null;
}

export interface Instance {
  name: string;
  status: InstanceStatus;
  url: string | null;
  odoo: { version: string; edition: "community" | "enterprise"; database: string };
  git: {
    repository: string | null;
    branch: string;
    branch_deleted_on_github: boolean;
    commit: { sha: string; subject: string; author: string; age: string } | null;
  };
  settings: { auto_update: boolean; auto_upgrade: boolean; auto_pause: boolean; delete_after_days: number };
  usage: Usage;
  uptime: string | null;
  gateway_error: string | null;
  created_at: string | null;
  last_visit_at: string | null;
  pauses_at: string | null;
  expires_at: string | null;
  current_job: JobRef | null;
  created_by: string | null;
  // only on GET /instances/<name>
  disk?: { database_bytes: number | null; files_bytes: number | null };
  recent_commits?: { sha: string; subject: string; when: string; author: string }[];
  submodules?: { path: string; sha: string; url: string }[];
  recent_jobs?: JobRef[];
  backups?: InstanceBackup[];
  /** the backup "Restore the latest backup" puts back */
  restorable_backup?: string | null;
}

export interface Credentials {
  login: string;
  admin_password: string;
  master_password: string;
  ports: Record<string, number>;
}

export interface ServerFigures {
  cpu_percent: number;
  cores: number;
  load_1m: number;
  memory_used_bytes: number;
  memory_total_bytes: number;
  memory_percent: number;
  disk_used_bytes: number;
  disk_total_bytes: number;
  disk_percent: number;
  uptime_seconds: number;
  instances_running: number;
  instances_total: number;
}

export interface Metrics {
  at: number | null;
  interval_seconds: number;
  server: Partial<ServerFigures>;
  instances: Record<string, Usage & { running: boolean }>;
}

export type Columns = { t: number[] } & Record<string, (number | null)[]>;

export interface MetricsHistory {
  server: Columns;
  instances: Record<string, Columns>;
}

export interface Server {
  version: string;
  panel_url: string | null;
  plugins: { exposure: string; enterprise_source: string; update_triggers: string[] };
  metrics: Partial<ServerFigures>;
  live_clients: number;
}

export interface Setting {
  key: string;
  env: string;
  value: string | number | boolean;
  env_value: string | number | boolean;
  changed_in_panel: boolean;
  editable: boolean;
  applies: "now" | "restart" | "env";
  pending_restart: boolean;
  secret: boolean;
  type: "boolean" | "integer" | "number" | "string";
  minimum: number | null;
  description: string | null;
}

export interface Version {
  version: string;
  enterprise: boolean;
}

export interface Plan {
  name: string;
  database: string;
  login: string;
  defaults: { delete_after_days: number; auto_update: boolean; auto_upgrade: boolean; auto_pause: boolean };
}

export interface Quota {
  instances: number;
  max_instances: number | null;
  own_instances: number;
  max_instances_per_user: number | null;
  cooldown_minutes: number | null;
  next_creation_at: number | null;
}

export interface Factor {
  name: string;
  label: string;
  enrolled: boolean;
  added_at: string | null;
}

export interface Account extends Profile {
  name: string;
  display_name: string;
  role: Role;
  role_label: string;
  email: string | null;
  password_managed_here: boolean;
  second_factors: Factor[];
  second_factor_required: boolean;
  require_second_factor: "none" | "admins" | "everyone";
}

export interface User extends Profile {
  name: string;
  display_name: string;
  role: Role;
  role_label: string;
  last_sign_in_at: string | null;
  password_changed_at: string | null;
  must_change_password: boolean;
  second_factors: string[];
}

export interface DocsContents {
  index: string;
  sections: { title: string; pages: { path: string; title: string }[] }[];
}

export interface DocPage {
  path: string;
  title: string;
  html: string;
  headings: { level: number; id: string; text: string }[];
}

export interface Token {
  id: string;
  name: string;
  scope: "read" | "write";
  created: number;
  created_by: string;
  last_used: number | null;
}

export type BackupKind = "manual" | "daily" | "deletion" | "before-restore";
export interface Backup {
  file: string;
  instance: string;
  db: string;
  kind: BackupKind;
  size: number;
  created: number;
}

/** A backup as an instance lists it. */
export interface InstanceBackup {
  file: string;
  kind: BackupKind;
  database: string;
  size_bytes: number;
  created_at: string;
}

export interface DeployKey {
  repo: string;
  spelling: string;
  public_key: string;
  created: number;
  github_url: string;
}

export interface AuditEntry {
  ts: number;
  user: string;
  ip: string | null;
  event: string;
  ok: boolean;
  instance?: string;
  detail?: string;
}

export interface RepoAccess {
  repositories: { url: string; role: "main" | "submodule"; ok: boolean; problem: string | null }[];
  all_ok: boolean;
}

// ---------------------------------------------------------------- plugins and the marketplace (docs/MARKETPLACE.md)

export interface Publisher {
  name: string;
  slug: string;
  verified: boolean;
  official: boolean;
}

export interface PricePlan {
  id: string;
  kind: "monthly" | "yearly" | "fixed_term";
  price_cents: number;
  currency: string;
  period_days: number | null;
}

export interface PluginVersionInfo {
  version: string;
  min_sudoo_version?: string;
  max_sudoo_version?: string | null;
  published_at?: string | null;
}

export type CatalogAction = "install" | "update" | "installed" | "buy" | "renew" | "incompatible";

/** One plugin of GET /marketplace/catalog: the hub's catalogue for this panel. */
export interface CatalogPlugin {
  id: string;
  name: string;
  description: string;
  type: string;
  tier: "free" | "paid";
  tags: string[];
  icon_url?: string | null;
  avg_rating: number;
  rating_count?: number;
  install_count: number;
  publisher: Publisher | null;
  requires: { id: string; version: string | null }[];
  plans: PricePlan[];
  latest_version: PluginVersionInfo | null;
  compatible_version: PluginVersionInfo | null;
  installed_version: string | null;
  license: { state: string; expires_at: string | null; grace_until: string | null } | null;
  action: CatalogAction;
}

/** GET /marketplace/catalog/<id>: the plugin's public page. */
export interface CatalogPluginDetail {
  id: string;
  homepage?: string | null;
  permissions: string[];
}

export interface Billing {
  payments_enabled: boolean;
  linked: boolean;
  account_name: string | null;
  purchases_allowed: boolean;
  monthly_limit_cents: number | null;
  spent_this_month_cents: number | null;
  remaining_cents: number | null;
  currency: string;
  card: { brand: string; last4: string; exp_month: number; exp_year: number; expired: boolean } | null;
  manage_url: string | null;
}

export type LicencePhase = "active" | "expiring" | "grace" | "ended" | "no_lease" | "unlicensed";

export interface InstalledPlugin {
  id: string;
  name: string;
  version: string;
  type: string | null;
  tier: "free" | "paid";
  description: string;
  publisher: Publisher | null;
  permissions: string[];
  enabled: boolean;
  status: "active" | "disabled" | "modified" | "blocked" | "switched_off" | "unlicensed";
  loaded: boolean;
  restart_pending: boolean;
  licence: {
    state: string | null;
    standing: string | null;
    expires_at: string | null;
    grace_until: string | null;
    phase: LicencePhase | null;
  } | null;
  latest_version: string | null;
  update_available: boolean;
  installed_at: string | null;
  installed_by: string | null;
}

export interface PluginNotice {
  plugin: string | null;
  kind: string;
  level: "info" | "warning" | "danger";
  text: string;
  date: string | null;
}

export interface MarketplaceStatus {
  enabled: boolean;
  hub_url: string;
  installation_id: string | null;
  registered: boolean;
  reachable: boolean | null;
  error: string | null;
  error_code: string | null;
  hub_status: string | null;
  linked: { account_name: string | null; linked_at: string | null } | null;
  last_heartbeat_at: string | null;
  next_heartbeat_at: string | null;
  lease_expires_at: string | null;
  lease_valid: boolean;
  lease_ending_soon: boolean;
}

export interface Purchase {
  id: string;
  plugin_id: string | null;
  plugin_name: string | null;
  plan_id: string | null;
  plan_kind: string | null;
  amount_cents: number | null;
  currency: string | null;
  status: "succeeded" | "processing" | "checkout_required" | "failed" | "expired" | null;
  method: "saved_card" | "checkout" | null;
  reason: string | null;
  checkout_url: string | null;
  receipt_number: string | null;
  requested_by: { name: string | null; email: string | null };
  created_at: string | null;
  completed_at: string | null;
}

export interface Receipt {
  id: string;
  kind: "receipt" | "credit_note";
  number: string;
  issued_at: string | null;
  plugin_id: string | null;
  plugin_name: string | null;
  plan_kind: string | null;
  payment_kind: "purchase" | "renewal" | null;
  total_cents: number;
  currency: string;
  requested_by_name: string | null;
}
