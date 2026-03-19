import React from "react";
import ReactDOM from "react-dom/client";
import { Provider as JotaiProvider } from "jotai";
import { QueryProvider } from "./providers/QueryProvider";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <JotaiProvider>
      <QueryProvider>
        <App />
      </QueryProvider>
    </JotaiProvider>
  </React.StrictMode>
);
