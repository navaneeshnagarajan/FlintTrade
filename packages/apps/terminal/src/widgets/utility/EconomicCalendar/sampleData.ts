/**
 * Sample data for EconomicCalendarWidget — explore/disconnected mode.
 * Events are illustrative only, not real financial data.
 */

import { toIstIsoDate } from "@/lib/ist";

export type Impact = "high" | "medium" | "low";
export type Country = "IN" | "US" | "EU" | "GB" | "JP" | "CN";

export interface EconomicEvent {
  id: string;
  date: string;          // ISO date YYYY-MM-DD
  timeIst: string;       // HH:MM IST
  name: string;
  country: Country;
  impact: Impact;
  previous?: string;
  forecast?: string;
  actual?: string;       // Only for past events
}

/**
 * An IST calendar date, offset by whole days from today.
 *
 * Must agree with the widget's ``istToday()`` comparison, or the offset-0 event
 * loses its "Today" heading and renders as past.
 *
 * @param offset - Days from today; negative for the past.
 * @returns The ISO date ``YYYY-MM-DD`` of that IST day.
 */
function isoDate(offset: number): string {
  return toIstIsoDate(new Date(Date.now() + offset * 86_400_000));
}

export const COUNTRY_FLAGS: Record<Country, string> = {
  IN: "🇮🇳",
  US: "🇺🇸",
  EU: "🇪🇺",
  GB: "🇬🇧",
  JP: "🇯🇵",
  CN: "🇨🇳",
};

export const COUNTRY_LABELS: Record<Country, string> = {
  IN: "India",
  US: "US",
  EU: "Europe",
  GB: "UK",
  JP: "Japan",
  CN: "China",
};

export const SAMPLE_EVENTS: EconomicEvent[] = [
  // Past events
  {
    id: "e1",
    date: isoDate(-6),
    timeIst: "11:30",
    name: "RBI MPC Policy Rate",
    country: "IN",
    impact: "high",
    previous: "6.50%",
    forecast: "6.50%",
    actual: "6.50%",
  },
  {
    id: "e2",
    date: isoDate(-5),
    timeIst: "18:00",
    name: "US Non-Farm Payrolls",
    country: "US",
    impact: "high",
    previous: "275K",
    forecast: "200K",
    actual: "256K",
  },
  {
    id: "e3",
    date: isoDate(-4),
    timeIst: "14:30",
    name: "US CPI (YoY)",
    country: "US",
    impact: "high",
    previous: "3.1%",
    forecast: "2.9%",
    actual: "3.0%",
  },
  {
    id: "e4",
    date: isoDate(-3),
    timeIst: "20:00",
    name: "US FOMC Meeting Minutes",
    country: "US",
    impact: "high",
    previous: "-",
    forecast: "-",
    actual: "Released",
  },
  {
    id: "e5",
    date: isoDate(-2),
    timeIst: "12:00",
    name: "India WPI Inflation",
    country: "IN",
    impact: "medium",
    previous: "0.53%",
    forecast: "0.70%",
    actual: "0.65%",
  },
  {
    id: "e6",
    date: isoDate(-1),
    timeIst: "09:00",
    name: "India CPI Inflation",
    country: "IN",
    impact: "high",
    previous: "5.22%",
    forecast: "4.90%",
    actual: "4.85%",
  },
  // Today / upcoming
  {
    id: "e7",
    date: isoDate(0),
    timeIst: "17:30",
    name: "ECB Interest Rate Decision",
    country: "EU",
    impact: "high",
    previous: "4.00%",
    forecast: "3.75%",
  },
  {
    id: "e8",
    date: isoDate(1),
    timeIst: "14:30",
    name: "US Initial Jobless Claims",
    country: "US",
    impact: "medium",
    previous: "211K",
    forecast: "215K",
  },
  {
    id: "e9",
    date: isoDate(2),
    timeIst: "18:00",
    name: "US GDP (QoQ)",
    country: "US",
    impact: "high",
    previous: "3.1%",
    forecast: "2.8%",
  },
  {
    id: "e10",
    date: isoDate(3),
    timeIst: "09:00",
    name: "India PMI Manufacturing",
    country: "IN",
    impact: "medium",
    previous: "56.4",
    forecast: "56.0",
  },
  {
    id: "e11",
    date: isoDate(5),
    timeIst: "19:30",
    name: "US PCE Price Index (YoY)",
    country: "US",
    impact: "high",
    previous: "2.6%",
    forecast: "2.5%",
  },
  {
    id: "e12",
    date: isoDate(7),
    timeIst: "11:30",
    name: "RBI MPC Minutes",
    country: "IN",
    impact: "medium",
    previous: "-",
    forecast: "-",
  },
  {
    id: "e13",
    date: isoDate(8),
    timeIst: "20:00",
    name: "US ISM Manufacturing PMI",
    country: "US",
    impact: "medium",
    previous: "47.8",
    forecast: "48.5",
  },
  {
    id: "e14",
    date: isoDate(10),
    timeIst: "14:30",
    name: "UK CPI (YoY)",
    country: "GB",
    impact: "high",
    previous: "3.2%",
    forecast: "3.0%",
  },
  {
    id: "e15",
    date: isoDate(14),
    timeIst: "12:00",
    name: "India IIP Industrial Output",
    country: "IN",
    impact: "medium",
    previous: "3.2%",
    forecast: "4.0%",
  },
];
