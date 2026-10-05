import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
// All styles load here, shared first, so which rule wins never depends on which screen loaded first
import "./styles.css";
import "./app.css";
import "./auth/auth.css";
import "./components/public-page.css";
import "./jobs/schedule.css";
import "./jobs/job-editor.css";
import "./jobs/tracking.css";
import "./booking/booking.css";

createRoot(document.getElementById("root")).render(<App />);
