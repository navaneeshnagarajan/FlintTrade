/**
 * TradingSection — default exchange, product type, order type, and quantity.
 */

import { FieldRow, SelectInput, SegmentControl, TextInput, SectionTitle } from "./shared";

interface TradingSettings {
  exchange: string;
  product: "MIS" | "NRML" | "CNC";
  orderType: "MARKET" | "LIMIT" | "SL" | "SL-M";
  quantity: string;
}

interface TradingSectionProps {
  settings: TradingSettings;
  onChange: (field: keyof TradingSettings, value: string) => void;
}

export function TradingSection({ settings, onChange }: TradingSectionProps) {
  return (
    <div className="space-y-5">
      <SectionTitle>Trading Defaults</SectionTitle>

      <FieldRow label="Default Exchange">
        <SelectInput
          value={settings.exchange}
          onChange={(v) => onChange("exchange", v)}
          aria-label="Default exchange"
          options={[
            { value: "NSE", label: "NSE — National Stock Exchange" },
            { value: "NFO", label: "NFO — NSE F&O"                },
            { value: "BSE", label: "BSE — Bombay Stock Exchange"   },
            { value: "BFO", label: "BFO — BSE F&O"                },
            { value: "MCX", label: "MCX — Multi Commodity Exchange"},
            { value: "CDS", label: "CDS — Currency Derivatives"   },
          ]}
        />
      </FieldRow>

      <FieldRow
        label="Default Product"
        hint="MIS = intraday, NRML = overnight F&O, CNC = delivery equity."
      >
        <SegmentControl
          value={settings.product}
          onChange={(v) => onChange("product", v)}
          aria-label="Default product type"
          options={[
            { value: "MIS",  label: "MIS"  },
            { value: "NRML", label: "NRML" },
            { value: "CNC",  label: "CNC"  },
          ]}
        />
      </FieldRow>

      <FieldRow label="Default Order Type">
        <SegmentControl
          value={settings.orderType}
          onChange={(v) => onChange("orderType", v)}
          aria-label="Default order type"
          options={[
            { value: "MARKET", label: "Market" },
            { value: "LIMIT",  label: "Limit"  },
            { value: "SL",     label: "SL"     },
            { value: "SL-M",   label: "SL-M"   },
          ]}
        />
      </FieldRow>

      <FieldRow
        label="Default Quantity"
        hint="Pre-filled quantity in order forms. Can be overridden per order."
      >
        <TextInput
          value={settings.quantity}
          onChange={(v) => onChange("quantity", v)}
          placeholder="1"
          type="number"
          aria-label="Default order quantity"
        />
      </FieldRow>
    </div>
  );
}
