/**
 * Synthetic component fixture. Never part of the production entry point.
 *
 * Mounts the ticket's reserved rule line with the shared order-rules
 * evaluator, the stop-loss not-filled chip with Exit now, and the Live
 * acknowledgement. No backend: every "order" here is only evaluated, Exit now
 * only opens a ticket, and accepting Live only moves on to the PIN step.
 */
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import { LiveAcknowledgementDialog } from "../src/components/LiveAcknowledgementDialog";
import { OrderRuleLine } from "../src/components/orders/OrderRuleLine";
import { StopLossNotFilledChip } from "../src/components/orders/StopLossNotFilledChip";
import { pendingLiveAcknowledgement } from "../src/lib/liveAcknowledgement";
import { evaluateOrderRules, hasBlockingRule } from "../src/lib/orderRules";
import { exitNowTicket, isStopLossTriggeredNotFilled } from "../src/lib/stopLossState";
import "../src/index.css";

const ON = "2026-11-22";

function Ticket() {
  const [symbol, setSymbol] = useState("NIFTY25NOV2624000CE");
  const [exchange, setExchange] = useState("NFO");
  const [orderType, setOrderType] = useState("LIMIT");
  const [price, setPrice] = useState("100");
  const [trigger, setTrigger] = useState("");
  const results = evaluateOrderRules({
    symbol,
    exchange,
    orderType,
    price: Number(price) || null,
    triggerPrice: Number(trigger) || null,
    lastPrice: 100,
    broker: "practice",
    brokerName: "Practice",
  }, ON);
  return (
    <form aria-label="Ticket" className="space-y-2" onSubmit={(event) => event.preventDefault()}>
      <label className="block">Symbol <input aria-label="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} /></label>
      <label className="block">Exchange <input aria-label="Exchange" value={exchange} onChange={(e) => setExchange(e.target.value)} /></label>
      <label className="block">Type
        <select aria-label="Type" value={orderType} onChange={(e) => setOrderType(e.target.value)}>
          {["MARKET", "LIMIT", "SL", "SL-M"].map((type) => <option key={type}>{type}</option>)}
        </select>
      </label>
      <label className="block">Price <input aria-label="Price" value={price} onChange={(e) => setPrice(e.target.value)} /></label>
      <label className="block">Trigger <input aria-label="Trigger" value={trigger} onChange={(e) => setTrigger(e.target.value)} /></label>
      <OrderRuleLine id="orderpad-qty-error" results={results} />
      <button type="submit" disabled={hasBlockingRule(results)}>Place</button>
    </form>
  );
}

const TRIGGERED_STOP = {
  symbol: "NIFTY25NOV2624000CE", exchange: "NFO", action: "SELL", quantity: 150,
  orderType: "SL", status: "PENDING", stop_triggered: true, product: "MIS",
};
const POSITION = { symbol: "NIFTY25NOV2624000CE", exchange: "NFO", quantity: 150, ltp: 41.3, product: "MIS" };

function Book() {
  const [stop, setStop] = useState(TRIGGERED_STOP);
  const [opened, setOpened] = useState<string>("");
  useEffect(() => {
    const listener = (event: Event) => setOpened(JSON.stringify((event as CustomEvent).detail));
    window.addEventListener("flinttrade:addWidget", listener);
    return () => window.removeEventListener("flinttrade:addWidget", listener);
  }, []);
  return (
    <section aria-label="Positions" className="space-y-2">
      <div>
        {POSITION.symbol}{" "}
        {isStopLossTriggeredNotFilled(stop) ? (
          <StopLossNotFilledChip symbol={POSITION.symbol} ticket={() => exitNowTicket(POSITION, { ltp: POSITION.ltp })} />
        ) : null}
      </div>
      <button type="button" onClick={() => setStop({ ...stop, status: "COMPLETE" })}>Stop fills</button>
      <output aria-label="Opened ticket">{opened}</output>
    </section>
  );
}

function LiveSwitch() {
  const [text, setText] = useState("");
  const [step, setStep] = useState("Practice");
  const next = () => {
    setText("");
    setStep("PIN");
  };
  return (
    <section aria-label="Mode" className="space-y-2">
      <button
        type="button"
        onClick={() => {
          const pending = pendingLiveAcknowledgement();
          if (pending) setText(pending);
          else next();
        }}
      >
        Live
      </button>
      <output aria-label="Mode step">{step}</output>
      <LiveAcknowledgementDialog text={text} onCancel={() => setText("")} onAccept={next} />
    </section>
  );
}

createRoot(document.getElementById("root")!).render(
  <main className="dark bg-surface-base text-text-primary min-h-screen p-6 max-w-3xl mx-auto space-y-6">
    <Ticket />
    <Book />
    <LiveSwitch />
  </main>,
);
