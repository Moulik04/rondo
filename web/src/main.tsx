import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import "@fontsource-variable/archivo/wdth.css";
import "./shell/tokens.css";
import "./shell/shell.css";
import { Home } from "./shell/Home";
import { Layout } from "./shell/Layout";
import { NotFound } from "./shell/NotFound";
import { ScoutHome } from "./scout/ScoutHome";
import { ValueHome } from "./value/ValueHome";

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { index: true, element: <Home /> },
      { path: "value", element: <ValueHome /> },
      { path: "scout", element: <ScoutHome /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
