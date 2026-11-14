// The connection to the Sudoo.sh marketplace: shown on Settings (Marketplace) and inside the Plugins page.

import { useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, Link2, RefreshCcw, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { api, errorText } from "@/api/client";
import { keys, useMarketplace } from "@/api/queries";
import type { MarketplaceStatus, Publisher } from "@/api/types";
import { ago, dateTime } from "@/lib/format";
import { useCan } from "./Shell";
import { Button, Callout, Field, Skeleton, Tag } from "./ui/basics";
import { useToast } from "./ui/overlay";

/** Official (Sudoo.sh's own plugins) or Verified (Sudoo.sh checked who the publisher is). */
export function PublisherBadge({ publisher }: { publisher: Publisher | null }) {
  if (!publisher) return <span className="faint">Unknown publisher</span>;
  return (
    <span className="publisher">
      <span className="truncate">{publisher.name}</span>
      {publisher.official ? (
        <Tag tone="accent" icon={<ShieldCheck />}>Official</Tag>
      ) : publisher.verified ? (
        <Tag icon={<BadgeCheck />}>Verified</Tag>
      ) : null}
    </span>
  );
}

/** Why the marketplace cannot be used right now, in the person's words; null when it can. */
export function marketplaceProblem(status: MarketplaceStatus | undefined): { tone: "warning" | "danger"; text: string } | null {
  if (!status) return null;
  if (!status.enabled) return { tone: "warning", text: "The marketplace is switched off on this panel. A super admin can switch it on in Settings, Marketplace." };
  if (status.hub_status === "integrity_violation")
    return { tone: "danger", text: "The marketplace refuses this panel: its core files differ from the released version. Every plugin is switched off until the panel is reinstalled." };
  if (status.hub_status === "installation_suspended")
    return { tone: "danger", text: "This panel is suspended on the marketplace, so every plugin is switched off. Contact Sudoo.sh support." };
  if (status.reachable === false)
    return {
      tone: "warning",
      text: `The marketplace cannot be reached right now${status.lease_valid ? "" : ", and the panel has not reached it for 7 days, so paid plugins are switched off"}. Instances and installed plugins keep working; the panel tries again every 15 minutes.`,
    };
  return null;
}

export function LinkForm({ onLinked }: { onLinked?: () => void }) {
  const client = useQueryClient();
  const toast = useToast();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const link = async () => {
    setBusy(true);
    try {
      const linked = await api.post<{ account_name: string }>("/marketplace/link", { code: code.trim() });
      toast("success", "Panel linked", `It now belongs to ${linked.account_name} on app.sudoo.sh`);
      setCode("");
      await client.invalidateQueries({ queryKey: keys.marketplace });
      onLinked?.();
    } catch (error) {
      toast("error", "Not linked", errorText(error));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Field label="Link code" hint="On app.sudoo.sh, open Servers and choose Link a server. The code works once, for 15 minutes.">
      <div className="row">
        <input
          className="input mono"
          autoComplete="one-time-code"
          spellCheck={false}
          placeholder="ABCD-1234"
          maxLength={20}
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && code.trim().length >= 8 && link()}
        />
        <Button variant="primary" icon={<Link2 />} loading={busy} disabled={code.trim().length < 8} onClick={link}>
          Link
        </Button>
      </div>
    </Field>
  );
}

/** Settings, Marketplace: the connection, the lease, and linking to an account. */
export function MarketplaceSettings() {
  const { data: status, isPending } = useMarketplace();
  const can = useCan();
  const client = useQueryClient();
  const toast = useToast();
  const [sending, setSending] = useState(false);
  if (isPending) return <div className="card-body"><Skeleton height={120} /></div>;
  if (!status) return null;
  const problem = marketplaceProblem(status);
  const heartbeat = async () => {
    setSending(true);
    try {
      await api.post("/marketplace/heartbeat");
      toast("success", "The marketplace answered");
    } catch (error) {
      toast("error", "No answer", errorText(error));
    } finally {
      await client.invalidateQueries({ queryKey: keys.marketplace });
      setSending(false);
    }
  };
  return (
    <div className="card-body stack">
      {problem && <Callout tone={problem.tone}>{problem.text}</Callout>}
      <dl className="dl">
        <dt>Hub</dt>
        <dd className="mono small">{status.hub_url}</dd>
        <dt>This installation</dt>
        <dd className="mono small">{status.installation_id ?? "—"}</dd>
        <dt>Last heartbeat</dt>
        <dd>
          {status.last_heartbeat_at ? `${ago(status.last_heartbeat_at)} · ${dateTime(status.last_heartbeat_at)}` : "None yet"}
        </dd>
        <dt>Lease</dt>
        <dd>
          {status.lease_valid ? (
            <>
              Valid until {dateTime(status.lease_expires_at)}
              {status.lease_ending_soon && <> <Tag tone="caution">ends soon</Tag></>}
            </>
          ) : (
            <span className="muted">None: paid plugins cannot run until the next heartbeat passes</span>
          )}
        </dd>
        <dt>Account</dt>
        <dd>{status.linked?.account_name ? <>Linked to <b>{status.linked.account_name}</b></> : <span className="muted">Not linked. Free plugins need no account; paid ones do</span>}</dd>
      </dl>
      {can("settings.manage") && status.enabled && (
        <>
          {!status.linked?.account_name && <LinkForm />}
          <div className="row">
            <Button size="sm" icon={<RefreshCcw />} loading={sending} onClick={heartbeat}>
              Send a heartbeat now
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
