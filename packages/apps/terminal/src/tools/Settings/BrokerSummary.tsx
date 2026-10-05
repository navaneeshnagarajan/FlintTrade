/** Plain presentation of the already-loaded account snapshot. */
export function BrokerSummary({ connectedAccounts }: { connectedAccounts: number }) {
  return (
    <div className="space-y-1 text-sm text-text-secondary">
      <p className="font-medium text-text-primary">
        {connectedAccounts === 0
          ? "No connected broker accounts are listed."
          : `${connectedAccounts} connected broker ${connectedAccounts === 1 ? "account is" : "accounts are"} listed.`}
      </p>
      <p>Connecting an account does not enable live orders. Trading permissions and safety checks still apply.</p>
    </div>
  );
}
