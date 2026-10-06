import { Page, PageBody, PageHeader } from "@/components/layout/Page";
import { AccountStatusPanel } from "@/components/account/AccountStatusPanel";
import { BrokerRateLimitsPanel } from "@/components/account/BrokerRateLimitsPanel";

/** Native-session mirroring requires its own approved transport and safety design. */
export default function DittoRoute() {
  return (
    <Page>
      <PageHeader title="Ditto" />
      <PageBody>
        <div className="space-y-4">
          <div role="status" className="rounded border border-border-default p-4 text-sm text-text-secondary">
            Position mirroring and account-level Ditto risk controls are unavailable.
            Native-session mirroring needs a supported transport and execution-safety design.
            Manage your native broker sessions in Settings → Brokers.
          </div>
          <AccountStatusPanel />
          <BrokerRateLimitsPanel />
        </div>
      </PageBody>
    </Page>
  );
}
