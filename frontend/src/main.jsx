import React from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import Root from "./App.jsx";

const container = document.getElementById("root");
createRoot(container).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);