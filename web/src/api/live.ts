// The live event stream (GET /api/v1/events): every change arrives as it happens and is written straight into
// the query caches, so pages update without asking. EventSource reconnects by itself and resumes where it stopped.

import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { keys, type JobLog } from "./queries";
import type { Columns, Instance, Job, Metrics, MetricsHistory } from "./types";

export type LiveState = "connecting" | "open" | "closed";

const HISTORY_SECONDS = 3600;

function upsert<T>(list: T[] | undefined, item: T, same: (a: T) => boolean, prepend = false): T[] | undefined {
  if (!list) return list;
  const index = list.findIndex(same);
  if (index === -1) return prepend ? [item, ...list] : [...list, item];
  const copy = list.slice();
  copy[index] = item;
  return copy;
}

function appendColumns(columns: Columns | undefined, t: number, values: Record<string, unknown>): Columns {
  const base: Columns = columns ?? ({ t: [] } as unknown as Columns);
  const keep = base.t.findIndex((time) => time >= t - HISTORY_SECONDS);
  const from = keep === -1 ? base.t.length : keep;
  const next: Columns = { t: [...base.t.slice(from), t] } as Columns;
  for (const key of new Set([...Object.keys(base), ...Object.keys(values)])) {
    if (key === "t") continue;
    const old = (base[key] ?? base.t.map(() => null)).slice(from);
    const value = values[key];
    next[key] = [...old, typeof value === "number" ? value : null];
  }
  return next;
}

function handle(client: QueryClient, topic: string, key: string, data: unknown) {
  switch (topic) {
    case "instance": {
      const instance = data as Instance;
      client.setQueryData<Instance[]>(keys.instances, (list) =>
        upsert(list, instance, (i) => i.name === instance.name)?.sort((a, b) => a.name.localeCompare(b.name)),
      );
      client.setQueryData<Instance>(keys.instance(instance.name), (old) => (old ? { ...old, ...instance } : old));
      break;
    }
    case "instance.deleted":
      client.setQueryData<Instance[]>(keys.instances, (list) => list?.filter((i) => i.name !== key));
      client.removeQueries({ queryKey: keys.instance(key) });
      break;
    case "job": {
      const job = data as Job;
      client.setQueryData(keys.job(job.id), job);
      for (const scope of [undefined, job.instance]) {
        client.setQueryData<Job[]>(keys.jobs(scope), (list) => upsert(list, job, (j) => j.id === job.id, true));
      }
      if (job.status === "success" || job.status === "failed") {
        if (job.kind.startsWith("plugin")) client.invalidateQueries({ queryKey: keys.plugins });
        else client.invalidateQueries({ queryKey: keys.instance(job.instance) });
        if (job.kind === "backup" || job.kind === "delete") client.invalidateQueries({ queryKey: ["backups"] });
      }
      break;
    }
    case "job.output": {
      const piece = data as { job: string; offset: number; next_offset: number; text: string };
      const current = client.getQueryData<JobLog>(keys.jobLog(piece.job));
      if (!current) break;
      if (current.next === piece.offset) {
        client.setQueryData<JobLog>(keys.jobLog(piece.job), { text: current.text + piece.text, next: piece.next_offset });
      } else if (current.next < piece.offset) {
        client.invalidateQueries({ queryKey: keys.jobLog(piece.job) });
      }
      break;
    }
    case "metrics": {
      const metrics = data as Metrics;
      client.setQueryData(keys.metrics, metrics);
      const t = metrics.at ?? Math.floor(Date.now() / 1000);
      client.setQueryData<MetricsHistory>(keys.history, (history) => {
        if (!history) return history;
        const instances: Record<string, Columns> = {};
        for (const [name, figures] of Object.entries(metrics.instances)) {
          instances[name] = appendColumns(history.instances[name], t, figures as unknown as Record<string, unknown>);
        }
        return { server: appendColumns(history.server, t, metrics.server), instances };
      });
      break;
    }
    case "settings":
      client.invalidateQueries({ queryKey: keys.settings });
      client.invalidateQueries({ queryKey: ["account"] });
      client.invalidateQueries({ queryKey: ["quota"] });
      break;
    case "plugins":
      client.invalidateQueries({ queryKey: keys.plugins });
      break;
    case "marketplace":
      client.invalidateQueries({ queryKey: keys.marketplace });
      client.invalidateQueries({ queryKey: keys.plugins });
      break;
    case "reset":
      client.invalidateQueries();
      break;
  }
}

const TOPICS = ["instance", "instance.deleted", "job", "job.output", "metrics", "settings", "plugins", "marketplace", "reset"];

export interface Sync {
  state: LiveState;
  /** when the last event arrived (ms); the server sends figures every METRICS_INTERVAL_SECONDS */
  lastAt: number | null;
}

export function useLiveEvents(enabled: boolean): Sync {
  const client = useQueryClient();
  const [sync, setSync] = useState<Sync>({ state: "connecting", lastAt: null });
  useEffect(() => {
    if (!enabled) return;
    const source = new EventSource("/api/v1/events");
    source.onopen = () => setSync((s) => ({ state: "open", lastAt: s.lastAt ?? Date.now() }));
    source.onerror = () =>
      setSync((s) => ({ ...s, state: source.readyState === EventSource.CLOSED ? "closed" : "connecting" }));
    for (const topic of TOPICS) {
      source.addEventListener(topic, (message) => {
        setSync({ state: "open", lastAt: Date.now() });
        try {
          const { key, data } = JSON.parse((message as MessageEvent<string>).data);
          handle(client, topic, key, data);
        } catch {
          /* a malformed event is skipped; the next one carries the full state again */
        }
      });
    }
    return () => source.close();
  }, [client, enabled]);
  return sync;
}
