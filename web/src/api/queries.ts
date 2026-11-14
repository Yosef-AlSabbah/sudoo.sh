// Every read of the API as a TanStack Query hook. The live event stream (live.ts) keeps these caches current, so
// most of them never need to ask again.

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./client";
import type {
  Billing,
  Receipt,
  Account,
  CatalogPlugin,
  CatalogPluginDetail,
  InstalledPlugin,
  MarketplaceStatus,
  PluginNotice,
  Purchase,
  AuditEntry,
  Backup,
  Credentials,
  DeployKey,
  DocPage,
  DocsContents,
  Instance,
  Job,
  Metrics,
  MetricsHistory,
  Plan,
  Quota,
  RoleInfo,
  Server,
  Session,
  Setting,
  Token,
  User,
  Version,
} from "./types";

export const keys = {
  session: ["session"] as const,
  instances: ["instances"] as const,
  instance: (name: string) => ["instance", name] as const,
  jobs: (instance?: string) => ["jobs", instance ?? null] as const,
  job: (id: string) => ["job", id] as const,
  jobLog: (id: string) => ["job-log", id] as const,
  metrics: ["metrics"] as const,
  history: ["metrics-history"] as const,
  settings: ["settings"] as const,
  plugins: ["plugins"] as const,
  pluginNotices: ["plugins", "notices"] as const,
  marketplace: ["marketplace"] as const,
  catalog: (query: string) => ["marketplace", "catalog", query] as const,
  purchases: ["marketplace", "purchases"] as const,
};

export const useSession = () =>
  useQuery({
    queryKey: keys.session,
    queryFn: async () => {
      try {
        return await api.get<Session>("/session");
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: Infinity,
    retry: false,
  });

export const useInstances = () =>
  useQuery({ queryKey: keys.instances, queryFn: () => api.get<Instance[]>("/instances?limit=500") });

export const useInstance = (name: string) =>
  useQuery({ queryKey: keys.instance(name), queryFn: () => api.get<Instance>(`/instances/${name}`) });

export const useJobs = (instance?: string) =>
  useQuery({
    queryKey: keys.jobs(instance),
    queryFn: () => api.get<Job[]>(`/jobs?limit=40${instance ? `&instance=${encodeURIComponent(instance)}` : ""}`),
  });

export const useJob = (id: string | null) =>
  useQuery({ queryKey: keys.job(id ?? ""), queryFn: () => api.get<Job>(`/jobs/${id}`), enabled: !!id });

export interface JobLog {
  text: string;
  next: number;
}
export const useJobLog = (id: string | null) =>
  useQuery({
    queryKey: keys.jobLog(id ?? ""),
    enabled: !!id,
    staleTime: Infinity,
    queryFn: async (): Promise<JobLog> => {
      const page = await api.page<{ text: string }>(`/jobs/${id}/log?offset=0`);
      return { text: page.data.text, next: Number(page.meta?.next_offset ?? 0) };
    },
  });

export const useMetrics = () => useQuery({ queryKey: keys.metrics, queryFn: () => api.get<Metrics>("/metrics") });
export const useHistory = () =>
  useQuery({
    queryKey: keys.history,
    queryFn: () => api.get<MetricsHistory>("/metrics/history?minutes=60"),
    staleTime: Infinity,
  });

export const useServer = () => useQuery({ queryKey: ["server"], queryFn: () => api.get<Server>("/server") });
export const useSettings = () => useQuery({ queryKey: keys.settings, queryFn: () => api.get<Setting[]>("/settings") });
export const useVersions = () =>
  useQuery({ queryKey: ["versions"], queryFn: () => api.get<Version[]>("/versions"), staleTime: 600_000 });
export const useQuota = () => useQuery({ queryKey: ["quota"], queryFn: () => api.get<Quota>("/instance-quota") });
export const useAccount = () => useQuery({ queryKey: ["account"], queryFn: () => api.get<Account>("/account") });
export const useRoles = () =>
  useQuery({ queryKey: ["roles"], queryFn: () => api.get<{ roles: RoleInfo[] }>("/roles"), staleTime: Infinity });
export const useSetup = () =>
  useQuery({ queryKey: ["setup"], queryFn: () => api.get<{ needed: boolean; contact: string }>("/setup"), retry: false });
export const useDocs = () =>
  useQuery({ queryKey: ["docs"], queryFn: () => api.get<DocsContents>("/docs"), staleTime: Infinity });
export const useDocPage = (path: string) =>
  useQuery({ queryKey: ["docs", path], queryFn: () => api.get<DocPage>(`/docs/${path}`), staleTime: Infinity, enabled: !!path });
export const useUsers = () => useQuery({ queryKey: ["users"], queryFn: () => api.get<User[]>("/users") });
export const useTokens = () => useQuery({ queryKey: ["tokens"], queryFn: () => api.get<Token[]>("/tokens") });
export const useBackups = () => useQuery({ queryKey: ["backups"], queryFn: () => api.get<Backup[]>("/backups") });
export const useDeployKeys = () =>
  useQuery({ queryKey: ["deploy-keys"], queryFn: () => api.get<DeployKey[]>("/deploy-keys") });
export const useAudit = (limit: number) =>
  useQuery({
    queryKey: ["audit", limit],
    queryFn: () => api.get<AuditEntry[]>(`/audit?limit=${limit}`),
    placeholderData: keepPreviousData,
  });
export const useCredentials = (name: string, enabled: boolean) =>
  useQuery({
    queryKey: ["credentials", name],
    queryFn: () => api.get<Credentials>(`/instances/${name}/credentials`),
    enabled,
    staleTime: Infinity,
  });
export const useOdooLog = (name: string, lines: number) =>
  useQuery({
    queryKey: ["odoo-log", name, lines],
    queryFn: () => api.get<{ text: string }>(`/instances/${name}/logs?lines=${lines}`),
  });
export const usePlan = (repo: string, branch: string, name: string) =>
  useQuery({
    queryKey: ["plan", repo, branch, name],
    queryFn: () =>
      api.get<Plan>(
        `/instance-plan?repo=${encodeURIComponent(repo)}&branch=${encodeURIComponent(branch)}&name=${encodeURIComponent(name)}`,
      ),
    placeholderData: keepPreviousData,
  });

export const usePlugins = () =>
  useQuery({ queryKey: keys.plugins, queryFn: () => api.get<InstalledPlugin[]>("/plugins") });
export const usePluginNotices = (enabled: boolean) =>
  useQuery({ queryKey: keys.pluginNotices, queryFn: () => api.get<PluginNotice[]>("/plugins/notices"), enabled, staleTime: 300_000 });
export const useMarketplace = () =>
  useQuery({ queryKey: keys.marketplace, queryFn: () => api.get<MarketplaceStatus>("/marketplace") });
export const useCatalog = (query: string, enabled: boolean) =>
  useQuery({
    queryKey: keys.catalog(query),
    queryFn: () => api.get<CatalogPlugin[]>(`/marketplace/catalog?${query}`),
    enabled,
    retry: false,
    placeholderData: keepPreviousData,
  });
export const useCategories = (enabled: boolean) =>
  useQuery({
    queryKey: ["marketplace", "categories"],
    queryFn: () => api.get<{ type: string; count: number }[]>("/marketplace/categories"),
    enabled,
    retry: false,
    staleTime: 600_000,
  });
export const useCatalogPlugin = (id: string | null) =>
  useQuery({
    queryKey: ["marketplace", "plugin", id],
    queryFn: () => api.get<CatalogPluginDetail>(`/marketplace/catalog/${id}`),
    enabled: !!id,
    retry: false,
  });
export const useBilling = (enabled: boolean) =>
  useQuery({ queryKey: ["marketplace", "billing"], queryFn: () => api.get<Billing>("/marketplace/billing"), enabled, retry: false });
export const useReceipts = (enabled: boolean) =>
  useQuery({ queryKey: ["marketplace", "receipts"], queryFn: () => api.get<Receipt[]>("/marketplace/receipts"), enabled, retry: false });
export const usePurchases = (enabled: boolean) =>
  useQuery({ queryKey: keys.purchases, queryFn: () => api.get<Purchase[]>("/marketplace/purchases"), enabled, retry: false });

/** A mutation that refreshes the given queries afterwards. */
export function useCall<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>, refresh: readonly (readonly unknown[])[] = []) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(refresh.map((queryKey) => client.invalidateQueries({ queryKey }))),
  });
}
